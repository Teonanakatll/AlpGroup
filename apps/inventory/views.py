"""
API. Вьюхи тонкие: чтение идёт через модели и selectors.py, операции через services.py.
Справочники и списки только для чтения (POST, PUT, DELETE вернут 405); менять данные
можно только операциями ниже (выдача, приём, потери, списание, ремонт, отмена).
"""
from rest_framework import viewsets
from rest_framework.generics import get_object_or_404
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sites.models import Site

from . import selectors, services
from .models import Category, HandTool, HandToolMovement, Tool, ToolMovement
from .serializers import (
    CancelBatchSerializer, CancelMovementSerializer, CategorySerializer,
    HandToolMovementSerializer, HandToolSerializer, OnSiteHandToolSerializer,
    ReceiveFromServicingSerializer, ServicingSerializer, SiteOperationSerializer,
    SiteSerializer, ToolMovementSerializer, ToolSerializer, WriteOffSerializer,
)


def _history_response(viewset, rows, serializer_class):
    """История с постраничной выдачей: журнал со временем разрастается."""
    page = viewset.paginate_queryset(rows)
    return viewset.get_paginated_response(serializer_class(page, many=True).data)


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.order_by("name")
    serializer_class = CategorySerializer


class ToolViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Штучный инструмент.
    Фильтры в адресе: ?status=available|issued|servicing|missing|written_off, ?category=<id>.
    """
    serializer_class = ToolSerializer

    def get_queryset(self):
        rows = Tool.objects.select_related("category", "current_site").order_by("name")
        params = self.request.query_params
        if params.get("status"):
            rows = rows.filter(status=params["status"])
        if params.get("category"):
            rows = rows.filter(category=params["category"])
        return rows

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """История позиции: все операции, новые сверху, отменённые помечены."""
        return _history_response(
            self, selectors.tool_history(self.get_object()), ToolMovementSerializer,
        )


class HandToolViewSet(viewsets.ReadOnlyModelViewSet):
    """Ручной инструмент (количеством). Фильтр: ?category=<id>."""
    serializer_class = HandToolSerializer

    def get_queryset(self):
        rows = HandTool.objects.select_related("category").order_by("name")
        if self.request.query_params.get("category"):
            rows = rows.filter(category=self.request.query_params["category"])
        return rows

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        return _history_response(
            self, selectors.hand_tool_history(self.get_object()), HandToolMovementSerializer,
        )


class SiteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Site.objects.select_related("work_type").order_by("name")
    serializer_class = SiteSerializer

    @action(detail=True, methods=["get"], url_path="on-site")
    def on_site(self, request, pk=None):
        """Что числится на объекте сейчас (для формы приёма и отчётов)."""
        site = self.get_object()
        hand_pairs = [
            {"hand_tool": hand_tool, "quantity": quantity}
            for hand_tool, quantity in selectors.hand_tools_on_site(site)
        ]
        return Response({
            "tools": ToolSerializer(selectors.tools_on_site(site), many=True).data,
            "hand_tools": OnSiteHandToolSerializer(hand_pairs, many=True).data,
        })


class AvailableView(APIView):
    """Что сейчас можно выдать (для формы выдачи). Без страниц: это список для выбора."""

    def get(self, request):
        return Response({
            "tools": ToolSerializer(selectors.available_tools(), many=True).data,
            "hand_tools": HandToolSerializer(selectors.available_hand_tools(), many=True).data,
        })


# ---------------------------------------------------------------------------
# Операции (меняют данные, всё через services.py)
# ---------------------------------------------------------------------------

class OperationView(APIView):
    """
    Общий ход операции: проверить JSON, вызвать service, вернуть результат.

    Два вида отказа, оба с кодом 400:
    - неверный формат (нет объекта, количество 0, такого id нет): {"site": ["..."], ...};
    - правила учёта (инструмент уже выдан, не хватает на складе):
      {"detail": "Операция отклонена.", "errors": ["строка на каждую проблему", ...]}.
    Успех: perform() возвращает тело ответа. Для операций над набором это {"batch": "<uuid>"}:
    по нему набор потом можно найти или отменить.
    """
    serializer_class = None
    success_status = 201

    def perform(self, user, serializer):
        """Вызвать нужный service и вернуть тело ответа (словарь). Определяется в наследниках."""
        raise NotImplementedError

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            body = self.perform(request.user, serializer)
        except services.ServiceError as error:
            # В тексте ошибки по строке на каждую проблемную позицию (всё или ничего).
            return Response(
                {"detail": "Операция отклонена.", "errors": str(error).splitlines()},
                status=400,
            )
        return Response(body, status=self.success_status)


class IssueView(OperationView):
    """Выдать набор на объект."""
    serializer_class = SiteOperationSerializer

    def perform(self, user, serializer):
        return {"batch": services.issue_to_site(user=user, **serializer.service_kwargs())}


class ReceiveView(OperationView):
    """Принять набор с объекта на склад."""
    serializer_class = SiteOperationSerializer

    def perform(self, user, serializer):
        return {"batch": services.receive_from_site(user=user, **serializer.service_kwargs())}


class ReceiveFromServicingView(OperationView):
    """Принять штучные позиции из ремонта на склад."""
    serializer_class = ReceiveFromServicingSerializer

    def perform(self, user, serializer):
        data = serializer.validated_data
        batch = services.receive_from_servicing(
            user=user, tools=data["tools"], taken_by=data["taken_by"], note=data["note"],
        )
        return {"batch": batch}


class MissingView(OperationView):
    """Отметить позиции не найденными на объекте."""
    serializer_class = SiteOperationSerializer

    def perform(self, user, serializer):
        return {"batch": services.mark_missing(user=user, **serializer.service_kwargs())}


class WriteOffView(OperationView):
    """Списать позиции со склада (без site) или с объекта (с site)."""
    serializer_class = WriteOffSerializer

    def perform(self, user, serializer):
        return {"batch": services.write_off(user=user, **serializer.service_kwargs())}


class ServicingView(OperationView):
    """Отправить штучные позиции в ремонт со склада (без site) или с объекта (с site)."""
    serializer_class = ServicingSerializer

    def perform(self, user, serializer):
        data = serializer.validated_data
        batch = services.send_to_servicing(
            user=user, tools=data["tools"], site=data.get("site"),
            taken_by=data["taken_by"], note=data["note"],
        )
        return {"batch": batch}


class CancelBatchView(OperationView):
    """Отменить набор целиком (всё или ничего)."""
    serializer_class = CancelBatchSerializer
    success_status = 200

    def perform(self, user, serializer):
        batch = serializer.validated_data["batch"]
        services.cancel_batch(user=user, batch=batch)
        return {"batch": batch, "cancelled": True}


class CancelMovementView(OperationView):
    """Отменить одну строку журнала; остальные строки её набора не трогаются."""
    serializer_class = CancelMovementSerializer
    success_status = 200

    def perform(self, user, serializer):
        data = serializer.validated_data
        model = ToolMovement if data["kind"] == "tool" else HandToolMovement
        movement = get_object_or_404(model, pk=data["id"])  # нет такой строки: ответ 404
        services.cancel_movement(user=user, movement=movement)
        return {"kind": data["kind"], "id": movement.pk, "cancelled": True}

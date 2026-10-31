"""
API только для чтения. Вьюхи тонкие: берут данные из моделей и selectors.py и отдают JSON.
Ничего не меняют, поэтому ReadOnly* (запросы POST, PUT, DELETE вернут 405).
"""
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sites.models import Site

from . import selectors
from .models import Category, HandTool, Tool
from .serializers import (
    CategorySerializer, HandToolMovementSerializer, HandToolSerializer,
    OnSiteHandToolSerializer, SiteSerializer, ToolMovementSerializer, ToolSerializer,
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

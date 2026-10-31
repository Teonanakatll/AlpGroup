"""
Сериализаторы для API (пока только чтение).

Сериализатор превращает объект из базы в JSON. Логики учёта здесь нет:
статусы, остатки и «числится на объекте» уже посчитаны в моделях и selectors.py.
"""
from rest_framework import serializers

from apps.sites.models import Site

from .models import Category, HandTool, HandToolMovement, Tool, ToolMovement


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ("id", "name", "parent")


class SiteSerializer(serializers.ModelSerializer):
    # allow_null: у объекта вид работ может быть не указан, тогда в JSON будет null
    work_type_name = serializers.CharField(source="work_type.name", read_only=True, allow_null=True)

    class Meta:
        model = Site
        fields = ("id", "name", "work_type", "work_type_name")


class ToolSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    current_site_name = serializers.CharField(source="current_site.name", read_only=True, allow_null=True)

    class Meta:
        model = Tool
        fields = (
            "id", "name", "category", "category_name",
            "status", "status_display", "current_site", "current_site_name",
            "note", "on_balance_date",
        )


class HandToolSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    # available это свойство модели (total − issued), не поле базы
    available = serializers.IntegerField(read_only=True)

    class Meta:
        model = HandTool
        fields = ("id", "name", "category", "category_name", "total", "issued", "available", "note")


class OnSiteHandToolSerializer(serializers.Serializer):
    """Ручной инструмент на объекте: сама позиция и сколько её штук там числится."""
    hand_tool = HandToolSerializer()
    quantity = serializers.IntegerField()


class _MovementSerializer(serializers.ModelSerializer):
    """Общие поля строки журнала; у штучного и ручного инструмента они одинаковые."""
    type_display = serializers.CharField(source="get_type_display", read_only=True)
    site_name = serializers.CharField(source="site.name", read_only=True, allow_null=True)
    created_by_name = serializers.CharField(source="created_by.get_username", read_only=True)
    cancelled_by_name = serializers.CharField(
        source="cancelled_by.get_username", read_only=True, allow_null=True,
    )

    common_fields = (
        "id", "batch", "type", "type_display", "site", "site_name", "taken_by",
        "created_at", "created_by", "created_by_name",
        "is_cancelled", "cancelled_by", "cancelled_by_name", "cancelled_at", "note",
    )


class ToolMovementSerializer(_MovementSerializer):
    class Meta:
        model = ToolMovement
        fields = _MovementSerializer.common_fields


class HandToolMovementSerializer(_MovementSerializer):
    class Meta:
        model = HandToolMovement
        fields = _MovementSerializer.common_fields + ("quantity",)


# ---------------------------------------------------------------------------
# Входные данные операций. Только разбор и проверка формата JSON;
# правила учёта проверяет services.py.
# ---------------------------------------------------------------------------

class HandToolItemSerializer(serializers.Serializer):
    """Одна строка ручного инструмента в наборе: что и сколько."""
    hand_tool = serializers.PrimaryKeyRelatedField(queryset=HandTool.objects.all())
    quantity = serializers.IntegerField(min_value=1)


class _PositionsSerializer(serializers.Serializer):
    """Набор позиций операции: штучные по id и ручной инструмент с количеством."""
    tools = serializers.PrimaryKeyRelatedField(queryset=Tool.objects.all(), many=True, required=False)
    hand_tools = HandToolItemSerializer(many=True, required=False)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")

    def positions_kwargs(self):
        """Позиции и примечание в том виде, как их ждут функции services.py."""
        data = self.validated_data
        return {
            "tools": data.get("tools", []),
            "hand_tools": [(item["hand_tool"], item["quantity"]) for item in data.get("hand_tools", [])],
            "note": data["note"],
        }


class SiteOperationSerializer(_PositionsSerializer):
    """
    Выдача, приём с объекта, «не найден»: операции на объекте. Пример тела запроса:
    {"site": 1, "tools": [3, 4], "hand_tools": [{"hand_tool": 7, "quantity": 5}], "note": ""}
    """
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.all())
    taken_by = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")

    def service_kwargs(self):
        data = self.validated_data
        return {**self.positions_kwargs(), "site": data["site"], "taken_by": data["taken_by"]}


class WriteOffSerializer(_PositionsSerializer):
    """
    Списание. Без site (или с "site": null) это списание со склада, с site списание с объекта.
    """
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.all(), required=False, allow_null=True)

    def service_kwargs(self):
        return {**self.positions_kwargs(), "site": self.validated_data.get("site")}


class _ToolsOnlySerializer(serializers.Serializer):
    """Операции только над штучным инструментом (ремонт): {"tools": [3, 4]}."""
    tools = serializers.PrimaryKeyRelatedField(queryset=Tool.objects.all(), many=True)
    taken_by = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class ReceiveFromServicingSerializer(_ToolsOnlySerializer):
    """Приём штучных позиций из ремонта на склад."""


class ServicingSerializer(_ToolsOnlySerializer):
    """Отправка в ремонт. Без site со склада, с site с объекта."""
    site = serializers.PrimaryKeyRelatedField(queryset=Site.objects.all(), required=False, allow_null=True)


class CancelBatchSerializer(serializers.Serializer):
    """Отмена набора целиком: {"batch": "<uuid>"}."""
    batch = serializers.UUIDField()


class CancelMovementSerializer(serializers.Serializer):
    """Отмена одной строки журнала: {"kind": "tool" или "hand_tool", "id": 15}."""
    kind = serializers.ChoiceField(choices=["tool", "hand_tool"])
    id = serializers.IntegerField(min_value=1)

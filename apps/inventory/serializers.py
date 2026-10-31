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

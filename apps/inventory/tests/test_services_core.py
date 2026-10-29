"""Каркас services.py: пересчёт из журнала и постановка на баланс."""
import pytest
from django.db import IntegrityError

from apps.inventory import services
from apps.inventory.models import (
    BaseMovement, HandToolMovement, Tool, ToolMovement,
)

Type = BaseMovement.Type


# --- постановка штучной позиции на баланс ---------------------------------

def test_register_tool_creates_tool_and_journal_row(user, category):
    tool = services.register_tool(user=user, name="Перфоратор", category=category)

    assert tool.status == Tool.Status.AVAILABLE
    assert tool.current_site is None
    rows = ToolMovement.objects.filter(tool=tool)
    assert rows.count() == 1
    assert rows.get().type == Type.ADDED
    assert rows.get().batch is not None


def test_register_tool_is_atomic(category):
    # Без пользователя запись в журнал невозможна (created_by обязателен).
    # Позиция тоже не должна остаться в базе: всё в одной транзакции.
    with pytest.raises(IntegrityError):
        services.register_tool(user=None, name="Болгарка", category=category)
    assert not Tool.objects.filter(name="Болгарка").exists()


# --- пересчёт штучной позиции ---------------------------------------------

def test_recalc_tool_follows_last_active_movement(user, category, site):
    tool = services.register_tool(user=user, name="Дрель", category=category)

    ToolMovement.objects.create(tool=tool, type=Type.ISSUED, site=site, created_by=user)
    services.recalc_tool(tool)
    assert tool.status == Tool.Status.ISSUED
    assert tool.current_site == site

    ToolMovement.objects.create(tool=tool, type=Type.RETURNED, site=site, created_by=user)
    services.recalc_tool(tool)
    assert tool.status == Tool.Status.AVAILABLE
    assert tool.current_site is None


def test_recalc_tool_ignores_cancelled_movements(user, category, site):
    tool = services.register_tool(user=user, name="Дрель", category=category)
    issued = ToolMovement.objects.create(tool=tool, type=Type.ISSUED, site=site, created_by=user)
    services.recalc_tool(tool)
    assert tool.status == Tool.Status.ISSUED

    issued.is_cancelled = True
    issued.save()
    services.recalc_tool(tool)

    assert tool.status == Tool.Status.AVAILABLE
    assert tool.current_site is None


@pytest.mark.parametrize("movement_type, expected", [
    (Type.WRITTEN_OFF, Tool.Status.WRITTEN_OFF),
    (Type.SERVICING, Tool.Status.SERVICING),
    (Type.MISSING, Tool.Status.MISSING),
])
def test_recalc_tool_maps_every_type_to_status(user, category, site, movement_type, expected):
    tool = services.register_tool(user=user, name="Лебёдка", category=category)
    ToolMovement.objects.create(tool=tool, type=movement_type, site=site, created_by=user)

    services.recalc_tool(tool)

    assert tool.status == expected
    assert tool.current_site is None


# --- ручной инструмент: приход --------------------------------------------

def test_add_hand_tool_stock_increases_total(user, hand_tool):
    services.add_hand_tool_stock(user=user, hand_tool=hand_tool, quantity=10)
    services.add_hand_tool_stock(user=user, hand_tool=hand_tool, quantity=5, note="докупили")

    hand_tool.refresh_from_db()
    assert hand_tool.total == 15
    assert hand_tool.issued == 0
    assert hand_tool.available == 15
    assert HandToolMovement.objects.filter(hand_tool=hand_tool, type=Type.ADDED).count() == 2


@pytest.mark.parametrize("quantity", [0, -3])
def test_add_hand_tool_stock_rejects_non_positive(user, hand_tool, quantity):
    with pytest.raises(services.ServiceError):
        services.add_hand_tool_stock(user=user, hand_tool=hand_tool, quantity=quantity)
    assert not HandToolMovement.objects.filter(hand_tool=hand_tool).exists()


# --- пересчёт ручного инструмента -----------------------------------------

def test_recalc_hand_tool_counts_issued_minus_returned(user, hand_tool, site):
    services.add_hand_tool_stock(user=user, hand_tool=hand_tool, quantity=10)
    HandToolMovement.objects.create(
        hand_tool=hand_tool, type=Type.ISSUED, site=site, quantity=6, created_by=user)
    HandToolMovement.objects.create(
        hand_tool=hand_tool, type=Type.RETURNED, site=site, quantity=2, created_by=user)

    services.recalc_hand_tool(hand_tool)

    assert (hand_tool.total, hand_tool.issued, hand_tool.available) == (10, 4, 6)


def test_recalc_hand_tool_ignores_cancelled(user, hand_tool, site):
    services.add_hand_tool_stock(user=user, hand_tool=hand_tool, quantity=10)
    issued = HandToolMovement.objects.create(
        hand_tool=hand_tool, type=Type.ISSUED, site=site, quantity=6, created_by=user)
    issued.is_cancelled = True
    issued.save()

    services.recalc_hand_tool(hand_tool)

    assert hand_tool.issued == 0

"""Отмена: services.cancel_batch и services.cancel_movement."""
import uuid

import pytest
from django.utils import timezone

from apps.inventory import selectors, services
from apps.inventory.models import (
    BaseMovement, HandToolMovement, Tool, ToolMovement,
)

Type = BaseMovement.Type


def active(model, **filters):
    """Действующие (неотменённые) строки журнала."""
    return model.objects.filter(is_cancelled=False, **filters)


# --- отмена выдачи и приёма ------------------------------------------------

def test_cancel_issue_returns_tool_to_warehouse(user, tool, site):
    batch = services.issue_to_site(user=user, site=site, tools=[tool])

    services.cancel_batch(user=user, batch=batch)

    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE
    assert tool.current_site is None
    # запись не удалена, только помечена
    row = ToolMovement.objects.get(tool=tool, type=Type.ISSUED)
    assert row.is_cancelled is True


def test_cancelled_issue_can_be_repeated(user, tool, site):
    batch = services.issue_to_site(user=user, site=site, tools=[tool])
    services.cancel_batch(user=user, batch=batch)

    services.issue_to_site(user=user, site=site, tools=[tool])

    tool.refresh_from_db()
    assert tool.status == Tool.Status.ISSUED
    assert ToolMovement.objects.filter(tool=tool, type=Type.ISSUED).count() == 2
    assert active(ToolMovement, tool=tool, type=Type.ISSUED).count() == 1


def test_cancel_receive_puts_tool_back_on_site(user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])
    receive_batch = services.receive_from_site(user=user, site=site, tools=[tool])

    services.cancel_batch(user=user, batch=receive_batch)

    tool.refresh_from_db()
    assert tool.status == Tool.Status.ISSUED
    assert tool.current_site == site


def test_cancel_issue_set_restores_both_journals(user, tool, stocked_hand_tool, site):
    batch = services.issue_to_site(
        user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 4)],
    )

    services.cancel_batch(user=user, batch=batch)

    tool.refresh_from_db()
    stocked_hand_tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE
    assert (stocked_hand_tool.total, stocked_hand_tool.issued) == (10, 0)
    assert selectors.hand_tool_on_site(stocked_hand_tool, site) == 0
    assert not active(ToolMovement, type=Type.ISSUED).exists()
    assert not active(HandToolMovement, type=Type.ISSUED).exists()


def test_cancel_hand_tool_receive_restores_issued(user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 6)])
    receive_batch = services.receive_from_site(
        user=user, site=site, hand_tools=[(stocked_hand_tool, 4)])

    services.cancel_batch(user=user, batch=receive_batch)

    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 6
    assert selectors.hand_tool_on_site(stocked_hand_tool, site) == 6


# --- отмена потери, списания, ремонта --------------------------------------

def test_cancel_missing_returns_tool_to_site(user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])
    missing_batch = services.mark_missing(user=user, site=site, tools=[tool])

    services.cancel_batch(user=user, batch=missing_batch)

    tool.refresh_from_db()
    assert tool.status == Tool.Status.ISSUED
    assert tool.current_site == site


def test_cancel_write_off_of_missing_tool_returns_to_missing(user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])
    services.mark_missing(user=user, site=site, tools=[tool])
    write_off_batch = services.write_off(user=user, tools=[tool])

    services.cancel_batch(user=user, batch=write_off_batch)

    tool.refresh_from_db()
    assert tool.status == Tool.Status.MISSING


def test_cancel_servicing_from_site_returns_tool_to_site(user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])
    servicing_batch = services.send_to_servicing(user=user, site=site, tools=[tool])

    services.cancel_batch(user=user, batch=servicing_batch)

    tool.refresh_from_db()
    assert tool.status == Tool.Status.ISSUED
    assert tool.current_site == site


def test_cancel_hand_tool_loss_restores_total(user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 6)])
    loss_batch = services.mark_missing(user=user, site=site, hand_tools=[(stocked_hand_tool, 2)])
    stocked_hand_tool.refresh_from_db()
    assert (stocked_hand_tool.total, stocked_hand_tool.issued) == (8, 4)

    services.cancel_batch(user=user, batch=loss_batch)

    stocked_hand_tool.refresh_from_db()
    assert (stocked_hand_tool.total, stocked_hand_tool.issued) == (10, 6)


# --- запреты: ничего не должно измениться ----------------------------------

def test_cannot_cancel_not_last_operation(user, tool, site):
    issue_batch = services.issue_to_site(user=user, site=site, tools=[tool])
    services.receive_from_site(user=user, site=site, tools=[tool])

    with pytest.raises(services.ServiceError) as exc:
        services.cancel_batch(user=user, batch=issue_batch)

    assert "только последнюю" in str(exc.value)
    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE
    assert active(ToolMovement, tool=tool, type=Type.ISSUED).count() == 1


def test_cancel_not_last_operation_ok_after_cancelling_later_one(user, tool, site):
    # Отменяем по порядку: сначала приём, потом выдачу.
    issue_batch = services.issue_to_site(user=user, site=site, tools=[tool])
    receive_batch = services.receive_from_site(user=user, site=site, tools=[tool])

    services.cancel_batch(user=user, batch=receive_batch)
    services.cancel_batch(user=user, batch=issue_batch)

    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE
    assert tool.current_site is None


def test_cancel_set_is_all_or_nothing(user, category, stocked_hand_tool, site):
    # Набор: перфоратор и молотки. Потом молотки принимают отдельной операцией,
    # и набор отменить нельзя; перфоратор при этом тоже должен остаться выданным.
    perforator = services.register_tool(user=user, name="Перфоратор", category=category)
    issue_batch = services.issue_to_site(
        user=user, site=site, tools=[perforator], hand_tools=[(stocked_hand_tool, 5)],
    )
    services.receive_from_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 2)])

    with pytest.raises(services.ServiceError):
        services.cancel_batch(user=user, batch=issue_batch)

    perforator.refresh_from_db()
    stocked_hand_tool.refresh_from_db()
    assert perforator.status == Tool.Status.ISSUED
    assert perforator.current_site == site
    assert stocked_hand_tool.issued == 3
    assert active(ToolMovement, tool=perforator, type=Type.ISSUED).count() == 1
    assert active(HandToolMovement, type=Type.ISSUED).count() == 1


def test_error_lists_every_problem(user, category, stocked_hand_tool, site):
    perforator = services.register_tool(user=user, name="Перфоратор", category=category)
    issue_batch = services.issue_to_site(
        user=user, site=site, tools=[perforator], hand_tools=[(stocked_hand_tool, 5)],
    )
    services.receive_from_site(user=user, site=site, tools=[perforator])
    services.receive_from_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 1)])

    with pytest.raises(services.ServiceError) as exc:
        services.cancel_batch(user=user, batch=issue_batch)

    assert perforator.name in str(exc.value)
    assert stocked_hand_tool.name in str(exc.value)


def test_cannot_cancel_tool_added_to_balance(user, category):
    tool = services.register_tool(user=user, name="Дрель", category=category)
    added = ToolMovement.objects.get(tool=tool, type=Type.ADDED)

    with pytest.raises(services.ServiceError):
        services.cancel_batch(user=user, batch=added.batch)

    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE
    assert active(ToolMovement, tool=tool, type=Type.ADDED).count() == 1


def test_cannot_cancel_hand_tool_stock_added(user, hand_tool):
    services.add_hand_tool_stock(user=user, hand_tool=hand_tool, quantity=10)
    added = HandToolMovement.objects.get(hand_tool=hand_tool, type=Type.ADDED)

    with pytest.raises(services.ServiceError):
        services.cancel_movement(user=user, movement=added)

    hand_tool.refresh_from_db()
    assert hand_tool.total == 10


def test_cannot_cancel_unknown_batch(user):
    with pytest.raises(services.ServiceError):
        services.cancel_batch(user=user, batch=uuid.uuid4())


def test_cannot_cancel_twice(user, tool, site):
    batch = services.issue_to_site(user=user, site=site, tools=[tool])
    services.cancel_batch(user=user, batch=batch)

    with pytest.raises(services.ServiceError):
        services.cancel_batch(user=user, batch=batch)

    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE


# --- отмена одной записи ---------------------------------------------------

def test_cancel_movement_cancels_only_that_row(user, category, site):
    first = services.register_tool(user=user, name="Дрель", category=category)
    second = services.register_tool(user=user, name="Болгарка", category=category)
    services.issue_to_site(user=user, site=site, tools=[first, second])
    row = ToolMovement.objects.get(tool=first, type=Type.ISSUED)

    services.cancel_movement(user=user, movement=row)

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == Tool.Status.AVAILABLE
    assert second.status == Tool.Status.ISSUED        # остальной набор остался
    assert second.current_site == site


def test_cancel_movement_hand_tool_row(user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 4)])
    row = HandToolMovement.objects.get(hand_tool=stocked_hand_tool, type=Type.ISSUED)

    services.cancel_movement(user=user, movement=row)

    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 0


def test_cancel_movement_respects_last_operation_rule(user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])
    services.receive_from_site(user=user, site=site, tools=[tool])
    issue_row = ToolMovement.objects.get(tool=tool, type=Type.ISSUED)

    with pytest.raises(services.ServiceError):
        services.cancel_movement(user=user, movement=issue_row)


def test_cancel_movement_rejects_other_objects(user):
    with pytest.raises(services.ServiceError):
        services.cancel_movement(user=user, movement=object())


def test_cancelling_rest_of_partially_cancelled_batch_is_ok(user, category, site):
    first = services.register_tool(user=user, name="Дрель", category=category)
    second = services.register_tool(user=user, name="Болгарка", category=category)
    batch = services.issue_to_site(user=user, site=site, tools=[first, second])
    services.cancel_movement(user=user, movement=ToolMovement.objects.get(tool=first, type=Type.ISSUED))

    services.cancel_batch(user=user, batch=batch)    # отменится только оставшаяся строка

    second.refresh_from_db()
    assert second.status == Tool.Status.AVAILABLE


# --- кто и когда отменил ---------------------------------------------------

def test_cancel_records_who_and_when(user, tool, site):
    batch = services.issue_to_site(user=user, site=site, tools=[tool])
    before = timezone.now()

    services.cancel_batch(user=user, batch=batch)

    row = ToolMovement.objects.get(tool=tool, type=Type.ISSUED)
    assert row.cancelled_by == user
    assert before <= row.cancelled_at <= timezone.now()


def test_cancel_movement_records_who_and_when_for_hand_tool(user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 4)])
    row = HandToolMovement.objects.get(hand_tool=stocked_hand_tool, type=Type.ISSUED)

    services.cancel_movement(user=user, movement=row)

    row.refresh_from_db()
    assert row.cancelled_by == user
    assert row.cancelled_at is not None


def test_active_movements_have_no_cancel_info(user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    row = ToolMovement.objects.get(tool=tool, type=Type.ISSUED)

    assert row.cancelled_by is None
    assert row.cancelled_at is None

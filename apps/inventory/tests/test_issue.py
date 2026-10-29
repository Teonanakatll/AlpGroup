"""Выдача набора на объект: services.issue_to_site."""
import pytest

from apps.inventory import services
from apps.inventory.models import (
    BaseMovement, HandToolMovement, Tool, ToolMovement,
)

Type = BaseMovement.Type


# --- удачная выдача --------------------------------------------------------

def test_issue_tool_sets_status_site_and_journal(user, tool, site):
    batch = services.issue_to_site(user=user, site=site, tools=[tool], taken_by="Иванов")

    tool.refresh_from_db()
    assert tool.status == Tool.Status.ISSUED
    assert tool.current_site == site
    row = ToolMovement.objects.get(tool=tool, type=Type.ISSUED)
    assert row.site == site
    assert row.taken_by == "Иванов"
    assert row.created_by == user
    assert row.batch == batch


def test_issue_hand_tool_changes_counters(user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 4)])

    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.total == 10
    assert stocked_hand_tool.issued == 4
    assert stocked_hand_tool.available == 6
    row = HandToolMovement.objects.get(hand_tool=stocked_hand_tool, type=Type.ISSUED)
    assert (row.quantity, row.site) == (4, site)


def test_set_shares_one_batch_across_both_journals(user, tool, stocked_hand_tool, site):
    batch = services.issue_to_site(
        user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 2)],
    )

    assert ToolMovement.objects.get(tool=tool, type=Type.ISSUED).batch == batch
    assert HandToolMovement.objects.get(hand_tool=stocked_hand_tool, type=Type.ISSUED).batch == batch


def test_each_operation_gets_new_batch(user, category, site):
    first = services.register_tool(user=user, name="Дрель", category=category)
    second = services.register_tool(user=user, name="Болгарка", category=category)

    batch_1 = services.issue_to_site(user=user, site=site, tools=[first])
    batch_2 = services.issue_to_site(user=user, site=site, tools=[second])

    assert batch_1 != batch_2


# --- запреты: ничего не должно измениться ----------------------------------

def test_cannot_issue_already_issued_tool(user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    with pytest.raises(services.ServiceError):
        services.issue_to_site(user=user, site=site, tools=[tool])

    assert ToolMovement.objects.filter(tool=tool, type=Type.ISSUED).count() == 1


@pytest.mark.parametrize("movement_type", [Type.WRITTEN_OFF, Type.SERVICING, Type.MISSING])
def test_cannot_issue_tool_that_is_not_available(user, tool, site, movement_type):
    ToolMovement.objects.create(tool=tool, type=movement_type, created_by=user)
    services.recalc_tool(tool)

    with pytest.raises(services.ServiceError):
        services.issue_to_site(user=user, site=site, tools=[tool])

    assert not ToolMovement.objects.filter(tool=tool, type=Type.ISSUED).exists()


def test_checks_real_status_not_stale_object(user, tool, site):
    # Объект tool в памяти «устарел»: на самом деле его уже выдали другой операцией.
    stale = Tool.objects.get(pk=tool.pk)
    services.issue_to_site(user=user, site=site, tools=[tool])
    assert stale.status == Tool.Status.AVAILABLE   # в памяти всё ещё «на складе»

    with pytest.raises(services.ServiceError):
        services.issue_to_site(user=user, site=site, tools=[stale])


def test_cannot_issue_more_hand_tools_than_available(user, stocked_hand_tool, site):
    with pytest.raises(services.ServiceError):
        services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 11)])

    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 0
    assert not HandToolMovement.objects.filter(type=Type.ISSUED).exists()


def test_cannot_issue_hand_tools_beyond_remaining_stock(user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 8)])

    with pytest.raises(services.ServiceError):
        services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 3)])

    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 8


@pytest.mark.parametrize("quantity", [0, -1])
def test_hand_tool_quantity_must_be_positive(user, stocked_hand_tool, site, quantity):
    with pytest.raises(services.ServiceError):
        services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, quantity)])

    assert not HandToolMovement.objects.filter(type=Type.ISSUED).exists()


def test_all_or_nothing(user, tool, stocked_hand_tool, site):
    # Штучный инструмент выдать можно, а ручного просят больше, чем есть:
    # не должно выдаться ничего, в том числе штучный.
    with pytest.raises(services.ServiceError):
        services.issue_to_site(
            user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 99)],
        )

    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE
    assert not ToolMovement.objects.filter(type=Type.ISSUED).exists()
    assert not HandToolMovement.objects.filter(type=Type.ISSUED).exists()


def test_error_lists_every_problem(user, tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])   # теперь tool выдан

    with pytest.raises(services.ServiceError) as exc:
        services.issue_to_site(
            user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 99)],
        )

    message = str(exc.value)
    assert tool.name in message
    assert stocked_hand_tool.name in message


def test_duplicate_position_is_rejected(user, tool, site):
    with pytest.raises(services.ServiceError):
        services.issue_to_site(user=user, site=site, tools=[tool, tool])

    assert not ToolMovement.objects.filter(type=Type.ISSUED).exists()


def test_site_is_required(user, tool):
    with pytest.raises(services.ServiceError):
        services.issue_to_site(user=user, site=None, tools=[tool])


def test_empty_set_is_rejected(user, site):
    with pytest.raises(services.ServiceError):
        services.issue_to_site(user=user, site=site)

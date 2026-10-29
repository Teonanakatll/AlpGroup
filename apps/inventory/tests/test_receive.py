"""Приём: services.receive_from_site и services.receive_from_servicing."""
import pytest

from apps.inventory import selectors, services
from apps.inventory.models import (
    BaseMovement, HandToolMovement, Tool, ToolMovement,
)
from apps.sites.models import Site

Type = BaseMovement.Type


@pytest.fixture
def other_site(db):
    return Site.objects.create(name="Второй объект")


@pytest.fixture
def issued_tool(user, tool, site):
    """Штучная позиция, выданная на объект site."""
    services.issue_to_site(user=user, site=site, tools=[tool])
    tool.refresh_from_db()
    return tool


@pytest.fixture
def servicing_tool(user, tool):
    """Штучная позиция в ремонте."""
    ToolMovement.objects.create(tool=tool, type=Type.SERVICING, created_by=user)
    services.recalc_tool(tool)
    return tool


# --- приём с объекта: удачные случаи ---------------------------------------

def test_receive_tool_returns_it_to_warehouse(user, issued_tool, site):
    batch = services.receive_from_site(user=user, site=site, tools=[issued_tool], taken_by="Петров")

    issued_tool.refresh_from_db()
    assert issued_tool.status == Tool.Status.AVAILABLE
    assert issued_tool.current_site is None
    row = ToolMovement.objects.get(tool=issued_tool, type=Type.RETURNED)
    assert row.site == site            # в журнале видно, откуда принято
    assert row.taken_by == "Петров"
    assert row.batch == batch


def test_received_tool_can_be_issued_again(user, issued_tool, site, other_site):
    # Передача между объектами: приём, затем новая выдача (DECISIONS, раздел 13).
    services.receive_from_site(user=user, site=site, tools=[issued_tool])
    services.issue_to_site(user=user, site=other_site, tools=[issued_tool])

    issued_tool.refresh_from_db()
    assert issued_tool.status == Tool.Status.ISSUED
    assert issued_tool.current_site == other_site


def test_receive_hand_tool_partially(user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 6)])

    services.receive_from_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 4)])

    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 2
    assert stocked_hand_tool.available == 8
    assert selectors.hand_tool_on_site(stocked_hand_tool, site) == 2


def test_receive_set_shares_one_batch(user, issued_tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 5)])

    batch = services.receive_from_site(
        user=user, site=site, tools=[issued_tool], hand_tools=[(stocked_hand_tool, 5)],
    )

    assert ToolMovement.objects.get(tool=issued_tool, type=Type.RETURNED).batch == batch
    assert HandToolMovement.objects.get(
        hand_tool=stocked_hand_tool, type=Type.RETURNED).batch == batch


def test_receive_gets_new_batch_not_issue_batch(user, tool, site):
    issue_batch = services.issue_to_site(user=user, site=site, tools=[tool])

    receive_batch = services.receive_from_site(user=user, site=site, tools=[tool])

    assert receive_batch != issue_batch


# --- приём с объекта: запреты ----------------------------------------------

def test_cannot_receive_tool_that_is_on_warehouse(user, tool, site):
    with pytest.raises(services.ServiceError):
        services.receive_from_site(user=user, site=site, tools=[tool])

    assert not ToolMovement.objects.filter(type=Type.RETURNED).exists()


def test_cannot_receive_tool_from_wrong_site(user, issued_tool, other_site):
    with pytest.raises(services.ServiceError) as exc:
        services.receive_from_site(user=user, site=other_site, tools=[issued_tool])

    assert "не на этом объекте" in str(exc.value)
    issued_tool.refresh_from_db()
    assert issued_tool.status == Tool.Status.ISSUED


def test_cannot_receive_missing_tool(user, issued_tool, site):
    # Правило 13: нельзя принять позицию, числящуюся не найденной.
    ToolMovement.objects.create(tool=issued_tool, type=Type.MISSING, site=site, created_by=user)
    services.recalc_tool(issued_tool)

    with pytest.raises(services.ServiceError):
        services.receive_from_site(user=user, site=site, tools=[issued_tool])

    assert not ToolMovement.objects.filter(type=Type.RETURNED).exists()


def test_checks_real_status_not_stale_object(user, issued_tool, site):
    stale = Tool.objects.get(pk=issued_tool.pk)          # в памяти: «выдан»
    services.receive_from_site(user=user, site=site, tools=[issued_tool])   # уже принят

    with pytest.raises(services.ServiceError):
        services.receive_from_site(user=user, site=site, tools=[stale])


def test_cannot_receive_more_hand_tools_than_on_site(user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 3)])

    with pytest.raises(services.ServiceError):
        services.receive_from_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 4)])

    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 3
    assert not HandToolMovement.objects.filter(type=Type.RETURNED).exists()


def test_hand_tool_count_is_per_site(user, stocked_hand_tool, site, other_site):
    # Всего выдано 8, но на другом объекте только 3: принять 4 с него нельзя.
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 5)])
    services.issue_to_site(user=user, site=other_site, hand_tools=[(stocked_hand_tool, 3)])

    with pytest.raises(services.ServiceError):
        services.receive_from_site(user=user, site=other_site, hand_tools=[(stocked_hand_tool, 4)])

    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 8


@pytest.mark.parametrize("quantity", [0, -1])
def test_receive_hand_tool_quantity_must_be_positive(user, stocked_hand_tool, site, quantity):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 3)])

    with pytest.raises(services.ServiceError):
        services.receive_from_site(user=user, site=site, hand_tools=[(stocked_hand_tool, quantity)])

    assert not HandToolMovement.objects.filter(type=Type.RETURNED).exists()


def test_receive_all_or_nothing(user, issued_tool, stocked_hand_tool, site):
    # Штучный принять можно, а ручного просят больше, чем на объекте: не принимается ничего.
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 2)])

    with pytest.raises(services.ServiceError):
        services.receive_from_site(
            user=user, site=site, tools=[issued_tool], hand_tools=[(stocked_hand_tool, 5)],
        )

    issued_tool.refresh_from_db()
    assert issued_tool.status == Tool.Status.ISSUED
    assert not ToolMovement.objects.filter(type=Type.RETURNED).exists()
    assert not HandToolMovement.objects.filter(type=Type.RETURNED).exists()


def test_receive_duplicate_position_is_rejected(user, issued_tool, site):
    with pytest.raises(services.ServiceError):
        services.receive_from_site(user=user, site=site, tools=[issued_tool, issued_tool])

    assert not ToolMovement.objects.filter(type=Type.RETURNED).exists()


def test_receive_site_is_required(user, issued_tool):
    with pytest.raises(services.ServiceError):
        services.receive_from_site(user=user, site=None, tools=[issued_tool])


def test_receive_empty_set_is_rejected(user, site):
    with pytest.raises(services.ServiceError):
        services.receive_from_site(user=user, site=site)


# --- приём из ремонта ------------------------------------------------------

def test_receive_from_servicing_returns_tool_without_site(user, servicing_tool):
    batch = services.receive_from_servicing(user=user, tools=[servicing_tool], note="отремонтирован")

    servicing_tool.refresh_from_db()
    assert servicing_tool.status == Tool.Status.AVAILABLE
    assert servicing_tool.current_site is None
    row = ToolMovement.objects.get(tool=servicing_tool, type=Type.RETURNED)
    assert row.site is None
    assert row.batch == batch


@pytest.mark.parametrize("make_state", ["available", "issued"])
def test_cannot_receive_from_servicing_if_not_in_service(user, tool, site, make_state):
    if make_state == "issued":
        services.issue_to_site(user=user, site=site, tools=[tool])

    with pytest.raises(services.ServiceError):
        services.receive_from_servicing(user=user, tools=[tool])

    assert not ToolMovement.objects.filter(type=Type.RETURNED).exists()


def test_receive_from_servicing_empty_set_is_rejected(user):
    with pytest.raises(services.ServiceError):
        services.receive_from_servicing(user=user, tools=[])


def test_receive_from_servicing_all_or_nothing(user, servicing_tool, category):
    available = services.register_tool(user=user, name="Дрель", category=category)

    with pytest.raises(services.ServiceError):
        services.receive_from_servicing(user=user, tools=[servicing_tool, available])

    servicing_tool.refresh_from_db()
    assert servicing_tool.status == Tool.Status.SERVICING
    assert not ToolMovement.objects.filter(type=Type.RETURNED).exists()

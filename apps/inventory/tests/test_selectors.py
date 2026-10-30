"""Выборки: selectors.py."""
from datetime import timedelta

from django.utils import timezone

from apps.inventory import selectors, services
from apps.inventory.models import BaseMovement, HandTool, HandToolMovement, ToolMovement
from apps.sites.models import Site

Type = BaseMovement.Type


def test_hand_tool_on_site_is_zero_without_movements(stocked_hand_tool, site):
    assert selectors.hand_tool_on_site(stocked_hand_tool, site) == 0


def test_hand_tool_on_site_counts_each_site_separately(user, stocked_hand_tool, site):
    other_site = Site.objects.create(name="Второй объект")
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 5)])
    services.issue_to_site(user=user, site=other_site, hand_tools=[(stocked_hand_tool, 3)])

    assert selectors.hand_tool_on_site(stocked_hand_tool, site) == 5
    assert selectors.hand_tool_on_site(stocked_hand_tool, other_site) == 3


def test_hand_tool_on_site_sums_several_issues(user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 2)])
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 3)])

    assert selectors.hand_tool_on_site(stocked_hand_tool, site) == 5


def test_hand_tool_on_site_subtracts_returned_missing_written_off(user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 8)])
    for movement_type, quantity in [(Type.RETURNED, 3), (Type.MISSING, 1), (Type.WRITTEN_OFF, 1)]:
        HandToolMovement.objects.create(
            hand_tool=stocked_hand_tool, type=movement_type, site=site,
            quantity=quantity, created_by=user,
        )

    assert selectors.hand_tool_on_site(stocked_hand_tool, site) == 3


def test_hand_tool_on_site_ignores_cancelled(user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 5)])
    HandToolMovement.objects.filter(hand_tool=stocked_hand_tool, type=Type.ISSUED).update(
        is_cancelled=True)

    assert selectors.hand_tool_on_site(stocked_hand_tool, site) == 0


# --- доступно к выдаче -----------------------------------------------------

def test_available_tools_only_on_warehouse(user, category, site):
    on_warehouse = services.register_tool(user=user, name="Аккумулятор", category=category)
    issued = services.register_tool(user=user, name="Дрель", category=category)
    lost = services.register_tool(user=user, name="Болгарка", category=category)
    written_off = services.register_tool(user=user, name="Лебёдка", category=category)
    services.issue_to_site(user=user, site=site, tools=[issued, lost])
    services.mark_missing(user=user, site=site, tools=[lost])
    services.write_off(user=user, tools=[written_off])

    assert list(selectors.available_tools()) == [on_warehouse]


def test_available_tools_returns_servicing_tool_only_after_receive(user, tool):
    services.send_to_servicing(user=user, tools=[tool])
    assert tool not in selectors.available_tools()

    services.receive_from_servicing(user=user, tools=[tool])
    assert tool in selectors.available_tools()


def test_available_hand_tools_only_with_stock_left(user, category, site):
    plenty = HandTool.objects.create(name="Молоток", category=category)
    empty = HandTool.objects.create(name="Отвёртка", category=category)
    HandTool.objects.create(name="Ключ", category=category)         # на балансе 0
    services.add_hand_tool_stock(user=user, hand_tool=plenty, quantity=5)
    services.add_hand_tool_stock(user=user, hand_tool=empty, quantity=2)
    services.issue_to_site(user=user, site=site, hand_tools=[(empty, 2)])    # всё выдано

    assert list(selectors.available_hand_tools()) == [plenty]


# --- числится на объекте ---------------------------------------------------

def test_tools_on_site_only_issued_to_this_site(user, category, site):
    other_site = Site.objects.create(name="Второй объект")
    here = services.register_tool(user=user, name="Дрель", category=category)
    there = services.register_tool(user=user, name="Перфоратор", category=category)
    lost = services.register_tool(user=user, name="Болгарка", category=category)
    returned = services.register_tool(user=user, name="Лебёдка", category=category)
    services.issue_to_site(user=user, site=site, tools=[here, lost, returned])
    services.issue_to_site(user=user, site=other_site, tools=[there])
    services.mark_missing(user=user, site=site, tools=[lost])
    services.receive_from_site(user=user, site=site, tools=[returned])

    assert list(selectors.tools_on_site(site)) == [here]


def test_hand_tools_on_site_lists_quantities(user, category, site):
    other_site = Site.objects.create(name="Второй объект")
    hammer = HandTool.objects.create(name="Молоток", category=category)
    wrench = HandTool.objects.create(name="Ключ", category=category)
    spare = HandTool.objects.create(name="Отвёртка", category=category)
    for item in (hammer, wrench, spare):
        services.add_hand_tool_stock(user=user, hand_tool=item, quantity=10)
    services.issue_to_site(user=user, site=site, hand_tools=[(hammer, 6), (wrench, 3), (spare, 2)])
    services.issue_to_site(user=user, site=other_site, hand_tools=[(hammer, 1)])
    services.receive_from_site(user=user, site=site, hand_tools=[(hammer, 2), (spare, 2)])
    services.mark_missing(user=user, site=site, hand_tools=[(wrench, 1)])

    result = selectors.hand_tools_on_site(site)

    # ключи по алфавиту; отвёртки не осталось (приняли все), молотков 4, ключей 2
    assert [(item.name, qty) for item, qty in result] == [("Ключ", 2), ("Молоток", 4)]


def test_hand_tools_on_site_agrees_with_hand_tool_on_site(user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 7)])
    services.receive_from_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 3)])
    services.write_off(user=user, site=site, hand_tools=[(stocked_hand_tool, 1)])

    (item, quantity), = selectors.hand_tools_on_site(site)

    assert item == stocked_hand_tool
    assert quantity == selectors.hand_tool_on_site(stocked_hand_tool, site) == 3


def test_hand_tools_on_site_ignores_cancelled(user, stocked_hand_tool, site):
    batch = services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 5)])
    services.cancel_batch(user=user, batch=batch)

    assert selectors.hand_tools_on_site(site) == []


# --- история ---------------------------------------------------------------

def test_tool_history_newest_first_and_includes_cancelled(user, tool, site):
    issue_batch = services.issue_to_site(user=user, site=site, tools=[tool])
    services.cancel_batch(user=user, batch=issue_batch)
    services.send_to_servicing(user=user, tools=[tool])

    history = list(selectors.tool_history(tool))

    assert [(row.type, row.is_cancelled) for row in history] == [
        (Type.SERVICING, False), (Type.ISSUED, True), (Type.ADDED, False),
    ]


def test_tool_history_can_hide_cancelled(user, tool, site):
    batch = services.issue_to_site(user=user, site=site, tools=[tool])
    services.cancel_batch(user=user, batch=batch)

    history = list(selectors.tool_history(tool, include_cancelled=False))

    assert [row.type for row in history] == [Type.ADDED]


def test_tool_history_is_only_for_that_tool(user, category, tool):
    other = services.register_tool(user=user, name="Дрель", category=category)

    assert all(row.tool_id == tool.pk for row in selectors.tool_history(tool))
    assert selectors.tool_history(other).count() == 1


def test_hand_tool_history(user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 3)])
    services.receive_from_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 1)])

    history = list(selectors.hand_tool_history(stocked_hand_tool))

    assert [(row.type, row.quantity) for row in history] == [
        (Type.RETURNED, 1), (Type.ISSUED, 3), (Type.ADDED, 10),
    ]


# --- выдано за период ------------------------------------------------------

def test_issued_in_period_filters_by_dates(user, category, site):
    old = services.register_tool(user=user, name="Дрель", category=category)
    recent = services.register_tool(user=user, name="Болгарка", category=category)
    services.issue_to_site(user=user, site=site, tools=[old])
    services.issue_to_site(user=user, site=site, tools=[recent])
    ToolMovement.objects.filter(tool=old, type=Type.ISSUED).update(
        created_at=timezone.now() - timedelta(days=30))
    today = timezone.localdate()

    tool_rows, hand_rows = selectors.issued_in_period(today - timedelta(days=7), today)

    assert [row.tool for row in tool_rows] == [recent]
    assert list(hand_rows) == []


def test_issued_in_period_includes_both_boundary_days(user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])
    today = timezone.localdate()

    tool_rows, _ = selectors.issued_in_period(today, today)

    assert tool_rows.count() == 1


def test_issued_in_period_by_site(user, category, site):
    other_site = Site.objects.create(name="Второй объект")
    first = services.register_tool(user=user, name="Дрель", category=category)
    second = services.register_tool(user=user, name="Болгарка", category=category)
    services.issue_to_site(user=user, site=site, tools=[first])
    services.issue_to_site(user=user, site=other_site, tools=[second])
    today = timezone.localdate()

    tool_rows, _ = selectors.issued_in_period(today, today, site=other_site)

    assert [row.tool for row in tool_rows] == [second]


def test_issued_in_period_skips_cancelled_and_non_issues(user, tool, stocked_hand_tool, site):
    batch = services.issue_to_site(
        user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 2)])
    services.cancel_batch(user=user, batch=batch)
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 3)])
    services.receive_from_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 1)])
    today = timezone.localdate()

    tool_rows, hand_rows = selectors.issued_in_period(today, today)

    assert tool_rows.count() == 0                            # выдача отменена, приёмы не считаются
    assert [row.quantity for row in hand_rows] == [3]

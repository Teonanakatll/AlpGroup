"""Выборки: selectors.py."""
from apps.inventory import selectors, services
from apps.inventory.models import BaseMovement, HandToolMovement
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

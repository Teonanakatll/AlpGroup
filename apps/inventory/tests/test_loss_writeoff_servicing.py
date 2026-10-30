"""Не найден, списание, ремонт: mark_missing, write_off, send_to_servicing."""
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
def issued_hand_tool(user, stocked_hand_tool, site):
    """Ручной инструмент: на балансе 10, на объекте site числится 6."""
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 6)])
    stocked_hand_tool.refresh_from_db()
    return stocked_hand_tool


# ===========================================================================
# mark_missing
# ===========================================================================

def test_mark_tool_missing(user, issued_tool, site):
    batch = services.mark_missing(user=user, site=site, tools=[issued_tool], note="не нашли")

    issued_tool.refresh_from_db()
    assert issued_tool.status == Tool.Status.MISSING
    assert issued_tool.current_site is None
    row = ToolMovement.objects.get(tool=issued_tool, type=Type.MISSING)
    assert (row.site, row.batch, row.note) == (site, batch, "не нашли")


def test_mark_hand_tool_missing_reduces_total_and_issued(user, issued_hand_tool, site):
    services.mark_missing(user=user, site=site, hand_tools=[(issued_hand_tool, 2)])

    issued_hand_tool.refresh_from_db()
    assert (issued_hand_tool.total, issued_hand_tool.issued, issued_hand_tool.available) == (8, 4, 4)
    assert selectors.hand_tool_on_site(issued_hand_tool, site) == 4
    # запись о потере осталась в журнале
    assert HandToolMovement.objects.filter(type=Type.MISSING, quantity=2).count() == 1


def test_cannot_mark_missing_tool_on_warehouse(user, tool, site):
    with pytest.raises(services.ServiceError):
        services.mark_missing(user=user, site=site, tools=[tool])

    assert not ToolMovement.objects.filter(type=Type.MISSING).exists()


def test_cannot_mark_missing_tool_from_wrong_site(user, issued_tool, other_site):
    with pytest.raises(services.ServiceError) as exc:
        services.mark_missing(user=user, site=other_site, tools=[issued_tool])

    assert "не на этом объекте" in str(exc.value)


def test_cannot_mark_missing_more_hand_tools_than_on_site(user, issued_hand_tool, site):
    with pytest.raises(services.ServiceError):
        services.mark_missing(user=user, site=site, hand_tools=[(issued_hand_tool, 7)])

    issued_hand_tool.refresh_from_db()
    assert (issued_hand_tool.total, issued_hand_tool.issued) == (10, 6)
    assert not HandToolMovement.objects.filter(type=Type.MISSING).exists()


def test_mark_missing_site_is_required(user, issued_tool):
    with pytest.raises(services.ServiceError):
        services.mark_missing(user=user, site=None, tools=[issued_tool])


def test_mark_missing_all_or_nothing(user, issued_tool, issued_hand_tool, site):
    with pytest.raises(services.ServiceError):
        services.mark_missing(
            user=user, site=site, tools=[issued_tool], hand_tools=[(issued_hand_tool, 99)],
        )

    issued_tool.refresh_from_db()
    assert issued_tool.status == Tool.Status.ISSUED
    assert not ToolMovement.objects.filter(type=Type.MISSING).exists()


def test_missing_tool_cannot_be_received(user, issued_tool, site):
    # Правило 13 остаётся в силе и после реальной операции, а не только после ручной записи.
    services.mark_missing(user=user, site=site, tools=[issued_tool])

    with pytest.raises(services.ServiceError):
        services.receive_from_site(user=user, site=site, tools=[issued_tool])


# ===========================================================================
# write_off
# ===========================================================================

def test_write_off_tool_from_warehouse(user, tool):
    services.write_off(user=user, tools=[tool], note="сломан безвозвратно")

    tool.refresh_from_db()
    assert tool.status == Tool.Status.WRITTEN_OFF
    assert tool.current_site is None
    assert ToolMovement.objects.get(tool=tool, type=Type.WRITTEN_OFF).site is None


def test_write_off_tool_from_servicing(user, tool):
    services.send_to_servicing(user=user, tools=[tool])

    services.write_off(user=user, tools=[tool])

    tool.refresh_from_db()
    assert tool.status == Tool.Status.WRITTEN_OFF


def test_write_off_tool_from_site(user, issued_tool, site):
    services.write_off(user=user, site=site, tools=[issued_tool])

    issued_tool.refresh_from_db()
    assert issued_tool.status == Tool.Status.WRITTEN_OFF
    assert issued_tool.current_site is None
    assert ToolMovement.objects.get(tool=issued_tool, type=Type.WRITTEN_OFF).site == site


def test_cannot_write_off_issued_tool_as_warehouse(user, issued_tool):
    # Выдан на объект: без указания объекта это не списание со склада.
    with pytest.raises(services.ServiceError):
        services.write_off(user=user, tools=[issued_tool])

    issued_tool.refresh_from_db()
    assert issued_tool.status == Tool.Status.ISSUED


def test_cannot_write_off_available_tool_as_site(user, tool, site):
    with pytest.raises(services.ServiceError):
        services.write_off(user=user, site=site, tools=[tool])

    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE


def test_missing_tool_can_be_written_off(user, issued_tool, site):
    # Потерянное закрывается списанием: «не найден» затем «списан».
    services.mark_missing(user=user, site=site, tools=[issued_tool])

    services.write_off(user=user, tools=[issued_tool], note="потерян, закрыли")

    issued_tool.refresh_from_db()
    assert issued_tool.status == Tool.Status.WRITTEN_OFF
    assert issued_tool.current_site is None
    assert ToolMovement.objects.filter(tool=issued_tool, type=Type.WRITTEN_OFF).count() == 1


def test_missing_tool_cannot_be_issued(user, issued_tool, site, other_site):
    services.mark_missing(user=user, site=site, tools=[issued_tool])

    with pytest.raises(services.ServiceError):
        services.issue_to_site(user=user, site=other_site, tools=[issued_tool])

    issued_tool.refresh_from_db()
    assert issued_tool.status == Tool.Status.MISSING


def test_lost_hand_tools_cannot_be_written_off_again(user, issued_hand_tool, site):
    # На балансе 10, на объекте 6; 2 потеряли: total 8, на складе 4, на объекте 4.
    services.mark_missing(user=user, site=site, hand_tools=[(issued_hand_tool, 2)])

    # Со склада можно списать только то, что там реально лежит (4), потерянные 2 уже вычтены.
    with pytest.raises(services.ServiceError):
        services.write_off(user=user, hand_tools=[(issued_hand_tool, 5)])

    issued_hand_tool.refresh_from_db()
    assert (issued_hand_tool.total, issued_hand_tool.issued) == (8, 4)


def test_cannot_write_off_twice(user, tool):
    services.write_off(user=user, tools=[tool])

    with pytest.raises(services.ServiceError):
        services.write_off(user=user, tools=[tool])

    assert ToolMovement.objects.filter(tool=tool, type=Type.WRITTEN_OFF).count() == 1


def test_write_off_hand_tool_from_warehouse_reduces_only_total(user, issued_hand_tool):
    # на балансе 10, на объекте 6, на складе 4: списываем 3 со склада
    services.write_off(user=user, hand_tools=[(issued_hand_tool, 3)])

    issued_hand_tool.refresh_from_db()
    assert (issued_hand_tool.total, issued_hand_tool.issued, issued_hand_tool.available) == (7, 6, 1)


def test_cannot_write_off_more_hand_tools_than_on_warehouse(user, issued_hand_tool):
    # на складе только 4, остальные 6 на объекте
    with pytest.raises(services.ServiceError):
        services.write_off(user=user, hand_tools=[(issued_hand_tool, 5)])

    issued_hand_tool.refresh_from_db()
    assert issued_hand_tool.total == 10


def test_write_off_hand_tool_from_site_reduces_total_and_issued(user, issued_hand_tool, site):
    services.write_off(user=user, site=site, hand_tools=[(issued_hand_tool, 2)])

    issued_hand_tool.refresh_from_db()
    assert (issued_hand_tool.total, issued_hand_tool.issued, issued_hand_tool.available) == (8, 4, 4)
    assert selectors.hand_tool_on_site(issued_hand_tool, site) == 4


def test_cannot_write_off_more_hand_tools_than_on_site(user, issued_hand_tool, site):
    with pytest.raises(services.ServiceError):
        services.write_off(user=user, site=site, hand_tools=[(issued_hand_tool, 7)])

    issued_hand_tool.refresh_from_db()
    assert (issued_hand_tool.total, issued_hand_tool.issued) == (10, 6)


def test_write_off_set_shares_one_batch(user, tool, issued_hand_tool):
    # Штучный и ручной со склада одной операцией.
    batch = services.write_off(user=user, tools=[tool], hand_tools=[(issued_hand_tool, 1)])

    assert ToolMovement.objects.get(tool=tool, type=Type.WRITTEN_OFF).batch == batch
    assert HandToolMovement.objects.get(type=Type.WRITTEN_OFF).batch == batch


def test_write_off_all_or_nothing(user, tool, issued_hand_tool):
    with pytest.raises(services.ServiceError):
        services.write_off(user=user, tools=[tool], hand_tools=[(issued_hand_tool, 99)])

    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE
    assert not ToolMovement.objects.filter(type=Type.WRITTEN_OFF).exists()


def test_write_off_empty_set_is_rejected(user):
    with pytest.raises(services.ServiceError):
        services.write_off(user=user)


# ===========================================================================
# send_to_servicing
# ===========================================================================

def test_send_tool_to_servicing_from_warehouse(user, tool):
    services.send_to_servicing(user=user, tools=[tool], note="не включается")

    tool.refresh_from_db()
    assert tool.status == Tool.Status.SERVICING
    assert tool.current_site is None
    assert ToolMovement.objects.get(tool=tool, type=Type.SERVICING).site is None


def test_send_tool_to_servicing_from_site(user, issued_tool, site):
    services.send_to_servicing(user=user, site=site, tools=[issued_tool])

    issued_tool.refresh_from_db()
    assert issued_tool.status == Tool.Status.SERVICING
    assert issued_tool.current_site is None
    assert ToolMovement.objects.get(tool=issued_tool, type=Type.SERVICING).site == site


def test_servicing_round_trip(user, tool, site):
    services.send_to_servicing(user=user, tools=[tool])
    services.receive_from_servicing(user=user, tools=[tool])
    services.issue_to_site(user=user, site=site, tools=[tool])

    tool.refresh_from_db()
    assert tool.status == Tool.Status.ISSUED


def test_cannot_send_issued_tool_to_servicing_as_warehouse(user, issued_tool):
    with pytest.raises(services.ServiceError):
        services.send_to_servicing(user=user, tools=[issued_tool])

    assert not ToolMovement.objects.filter(type=Type.SERVICING).exists()


def test_cannot_send_tool_to_servicing_from_wrong_site(user, issued_tool, other_site):
    with pytest.raises(services.ServiceError):
        services.send_to_servicing(user=user, site=other_site, tools=[issued_tool])


def test_cannot_send_servicing_tool_to_servicing_again(user, tool):
    services.send_to_servicing(user=user, tools=[tool])

    with pytest.raises(services.ServiceError):
        services.send_to_servicing(user=user, tools=[tool])

    assert ToolMovement.objects.filter(tool=tool, type=Type.SERVICING).count() == 1


def test_send_to_servicing_all_or_nothing(user, category, issued_tool):
    # issued_tool выдан на объект, а warehouse_tool лежит на складе (отдельная позиция).
    # Без указания объекта выданную отправить нельзя, значит не уйдёт ни одна.
    warehouse_tool = services.register_tool(user=user, name="Дрель", category=category)

    with pytest.raises(services.ServiceError):
        services.send_to_servicing(user=user, tools=[warehouse_tool, issued_tool])

    warehouse_tool.refresh_from_db()
    assert warehouse_tool.status == Tool.Status.AVAILABLE
    assert not ToolMovement.objects.filter(type=Type.SERVICING).exists()


def test_send_to_servicing_empty_set_is_rejected(user):
    with pytest.raises(services.ServiceError):
        services.send_to_servicing(user=user, tools=[])

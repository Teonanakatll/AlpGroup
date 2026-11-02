"""Выборки для главной страницы: сводка склада, последние операции, требует внимания."""
import pytest

from apps.inventory import selectors, services
from apps.inventory.models import HandTool, Tool


@pytest.mark.django_db
def test_summary_of_empty_warehouse():
    summary = selectors.stock_summary()

    assert summary["warehouse"] == summary["issued"] == summary["servicing"] == summary["missing"] == 0
    assert summary["ready_percent"] == 100  # делить не на что: считаем «всё готово»


def test_summary_counts_both_kinds_of_items(user, category, site, tool, stocked_hand_tool):
    second = services.register_tool(user=user, name="Дрель", category=category)
    services.issue_to_site(user=user, site=site, tools=[second], hand_tools=[(stocked_hand_tool, 4)])

    summary = selectors.stock_summary()

    # Склад: перфоратор + 6 из 10 молотков; выдано: дрель + 4 молотка.
    assert (summary["warehouse_tools"], summary["warehouse_hand"], summary["warehouse"]) == (1, 6, 7)
    assert (summary["issued_tools"], summary["issued_hand"], summary["issued"]) == (1, 4, 5)
    assert summary["ready_percent"] == 100


def test_summary_servicing_and_missing_lower_readiness(user, category, site):
    tools = [services.register_tool(user=user, name=f"Инструмент {n}", category=category) for n in range(4)]
    services.send_to_servicing(user=user, tools=[tools[0]])
    services.issue_to_site(user=user, site=site, tools=[tools[1]])
    services.mark_missing(user=user, site=site, tools=[tools[1]])

    summary = selectors.stock_summary()

    assert (summary["servicing"], summary["missing"]) == (1, 1)
    assert summary["warehouse"] == 2
    assert summary["ready_percent"] == 50  # 2 из 4 в строю


def test_summary_ignores_written_off(user, tool):
    services.write_off(user=user, tools=[tool])

    summary = selectors.stock_summary()

    assert summary["warehouse"] == 0
    assert summary["ready_percent"] == 100


def test_recent_entries_groups_set_into_one_entry(user, tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 3)])

    entries = selectors.recent_entries(limit=6)

    # Постановка на баланс (две записи) и выдача набора из двух позиций (одна запись-набор).
    issued = [e for e in entries if e["type_display"] == "Выдан"]
    assert len(issued) == 1
    entry = issued[0]
    assert entry["is_set"] is True and entry["count"] == 2
    assert {row["item"] for row in entry["rows"]} == {"Перфоратор", "Молоток"}
    assert entry["site"] == site.name
    created = [e["created_at"] for e in entries]
    assert created == sorted(created, reverse=True)


def test_recent_entries_respects_limit_and_marks_cancelled(user, tool, site):
    batch = services.issue_to_site(user=user, site=site, tools=[tool])
    services.cancel_batch(user=user, batch=batch)

    entries = selectors.recent_entries(limit=1)

    assert len(entries) == 1
    assert entries[0]["is_cancelled"] is True
    assert entries[0]["is_set"] is False


def test_journal_entries_single_batch_only(user, tool, stocked_hand_tool, site):
    batch = services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 3)])

    entries, has_more = selectors.journal_entries(batch=batch)

    assert has_more is False
    assert len(entries) == 1 and entries[0]["count"] == 2


def test_tools_needing_attention_lists_missing_first(user, category, site):
    broken = services.register_tool(user=user, name="Болгарка", category=category)
    lost = services.register_tool(user=user, name="Дрель", category=category)
    services.register_tool(user=user, name="Исправный", category=category)
    services.send_to_servicing(user=user, tools=[broken])
    services.issue_to_site(user=user, site=site, tools=[lost])
    services.mark_missing(user=user, site=site, tools=[lost])

    rows = selectors.tools_needing_attention()

    assert [tool.name for tool in rows] == ["Дрель", "Болгарка"]
    assert [tool.status for tool in rows] == [Tool.Status.MISSING, Tool.Status.SERVICING]

"""
Тесты админки: закрытые поля, журналы только для чтения и admin actions.

Админка не считает ничего сама, поэтому здесь проверяется главное: действие
доходит до services, результат виден в базе, а отказ services не меняет данные.
Фикстуры admin_client и admin_user даёт pytest-django.
"""
import pytest
from django.contrib import admin
from django.urls import reverse

from apps.inventory.models import HandTool, HandToolMovement, Tool, ToolMovement


def changelist(model_name):
    return reverse(f"admin:inventory_{model_name}_changelist")


def run_action(client, model_name, action, ids, **data):
    """
    Выполнить admin action так, как это делает браузер.

    Без apply приходит только выбор позиций (открывается промежуточная страница),
    с apply=1 приходит заполненная форма.
    """
    payload = {"action": action, "_selected_action": ids, **data}
    return client.post(changelist(model_name), payload)


def text(response):
    return response.content.decode()


# ---------------------------------------------------------------------------
# Закрытые поля и журналы
# ---------------------------------------------------------------------------

def test_counters_and_statuses_are_readonly():
    registry = admin.site._registry
    assert {"status", "current_site", "removed_date"} <= set(registry[Tool].readonly_fields)
    assert {"total", "issued"} <= set(registry[HandTool].readonly_fields)


@pytest.mark.parametrize("model_name", ["toolmovement", "handtoolmovement"])
def test_journals_are_view_only(admin_client, model_name):
    assert admin_client.get(changelist(model_name)).status_code == 200
    # Добавлять записи руками нельзя: журнал дописывает только services.
    add_url = reverse(f"admin:inventory_{model_name}_add")
    assert admin_client.get(add_url).status_code == 403


# ---------------------------------------------------------------------------
# Создание позиции идёт через service
# ---------------------------------------------------------------------------

def test_new_tool_gets_added_entry_in_journal(admin_client, category):
    response = admin_client.post(reverse("admin:inventory_tool_add"), {
        "name": "Болгарка",
        "category": category.pk,
        "note": "",
        "on_balance_date": "2026-10-31",
        # Форма фото (inline) всегда присылает служебные поля, даже если фото нет.
        "photos-TOTAL_FORMS": "0",
        "photos-INITIAL_FORMS": "0",
        "photos-MIN_NUM_FORMS": "0",
        "photos-MAX_NUM_FORMS": "1000",
    })

    assert response.status_code == 302
    tool = Tool.objects.get(name="Болгарка")
    assert tool.status == Tool.Status.AVAILABLE
    # Без записи в журнале позиции быть не должно (DECISIONS, раздел 6).
    assert tool.movements.filter(type=ToolMovement.Type.ADDED).count() == 1


# ---------------------------------------------------------------------------
# Штучный инструмент: выдача и приём
# ---------------------------------------------------------------------------

def test_issue_action_first_step_shows_form_and_changes_nothing(admin_client, tool):
    response = run_action(admin_client, "tool", "issue_action", [tool.pk])

    assert response.status_code == 200
    assert "Выдать на объект" in text(response)
    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE


def test_issue_and_receive_tool_through_admin(admin_client, tool, site):
    issued = run_action(
        admin_client, "tool", "issue_action", [tool.pk],
        apply="1", site=site.pk, taken_by="Иванов", note="",
    )
    assert issued.status_code == 302
    tool.refresh_from_db()
    assert tool.status == Tool.Status.ISSUED
    assert tool.current_site == site

    received = run_action(
        admin_client, "tool", "receive_from_site_action", [tool.pk],
        apply="1", site=site.pk, taken_by="Иванов", note="",
    )
    assert received.status_code == 302
    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE
    assert tool.current_site is None


def test_service_refusal_is_shown_and_nothing_changes(admin_client, user, tool, site):
    from apps.inventory import services
    services.issue_to_site(user=user, site=site, tools=[tool])
    journal_before = ToolMovement.objects.count()

    # Повторная выдача уже выданного инструмента запрещена правилами учёта.
    response = run_action(
        admin_client, "tool", "issue_action", [tool.pk],
        apply="1", site=site.pk, taken_by="", note="",
    )

    assert response.status_code == 200          # форма показана снова, а не редирект
    assert "нельзя выдать" in text(response)    # текст ошибки из services
    assert ToolMovement.objects.count() == journal_before


def test_receive_from_servicing_through_admin(admin_client, user, tool):
    from apps.inventory import services
    services.send_to_servicing(user=user, tools=[tool])

    response = run_action(
        admin_client, "tool", "receive_from_servicing_action", [tool.pk],
        apply="1", taken_by="", note="",
    )

    assert response.status_code == 302
    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE


# ---------------------------------------------------------------------------
# Ручной инструмент: приход, выдача, приём
# ---------------------------------------------------------------------------

def test_add_stock_action(admin_client, hand_tool):
    response = run_action(
        admin_client, "handtool", "add_stock_action", [hand_tool.pk],
        apply="1", note="", **{f"qty_{hand_tool.pk}": 7},
    )

    assert response.status_code == 302
    hand_tool.refresh_from_db()
    assert hand_tool.total == 7
    assert hand_tool.movements.get().type == HandToolMovement.Type.ADDED


def test_issue_and_receive_hand_tool_through_admin(admin_client, stocked_hand_tool, site):
    qty = f"qty_{stocked_hand_tool.pk}"

    run_action(
        admin_client, "handtool", "issue_action", [stocked_hand_tool.pk],
        apply="1", site=site.pk, taken_by="", note="", **{qty: 4},
    )
    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 4

    run_action(
        admin_client, "handtool", "receive_from_site_action", [stocked_hand_tool.pk],
        apply="1", site=site.pk, taken_by="", note="", **{qty: 3},
    )
    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 1
    assert stocked_hand_tool.total == 10


def test_hand_tool_issue_more_than_available_is_refused(admin_client, stocked_hand_tool, site):
    response = run_action(
        admin_client, "handtool", "issue_action", [stocked_hand_tool.pk],
        apply="1", site=site.pk, taken_by="", note="",
        **{f"qty_{stocked_hand_tool.pk}": 11},
    )

    assert response.status_code == 200
    assert "запрошено 11" in text(response)
    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 0


def test_hand_tool_quantity_must_be_positive(admin_client, stocked_hand_tool, site):
    response = run_action(
        admin_client, "handtool", "issue_action", [stocked_hand_tool.pk],
        apply="1", site=site.pk, taken_by="", note="",
        **{f"qty_{stocked_hand_tool.pk}": 0},
    )

    # Это отказ самой формы (min_value=1): до services дело не доходит.
    assert response.status_code == 200
    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 0

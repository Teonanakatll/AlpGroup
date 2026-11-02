"""Страница «На баланс» (apps/web) и сервисы register_tools / register_hand_tool."""
import pytest

from apps.inventory import services
from apps.inventory.models import HandTool, HandToolMovement, Tool, ToolMovement


def post(client, **fields):
    return client.post("/operations/add/", fields)


def test_add_page_requires_login_and_is_in_tabs(client, admin_client):
    assert client.get("/operations/add/").status_code == 302
    html = admin_client.get("/operations/issue/").content.decode()
    assert 'href="/operations/add/"' in html


def test_add_tools_creates_set_with_one_batch(admin_client, category):
    response = post(admin_client, kind="tool", name="  Дрель  ", category=category.pk, quantity=3, note="")

    assert response.status_code == 302
    tools = Tool.objects.filter(name="Дрель")
    assert tools.count() == 3
    rows = ToolMovement.objects.filter(type="added")
    assert rows.count() == 3 and len({r.batch for r in rows}) == 1


def test_add_new_hand_tool(admin_client, category):
    post(admin_client, kind="hand", name="Гвозди", category=category.pk, quantity=200)

    hand = HandTool.objects.get(name="Гвозди")
    assert hand.total == 200 and hand.issued == 0
    assert HandToolMovement.objects.get(hand_tool=hand).quantity == 200


def test_add_stock_to_existing_hand_tool(admin_client, stocked_hand_tool):
    post(admin_client, kind="hand", existing_hand=stocked_hand_tool.pk, quantity=5)

    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.total == 15            # было 10


def test_add_requires_name_and_category(admin_client):
    response = post(admin_client, kind="tool", name="", quantity=1)

    assert response.status_code == 200
    assert Tool.objects.count() == 0
    html = response.content.decode()
    assert "Укажите название." in html and "Выберите категорию." in html


def test_add_tools_limit(admin_client, category):
    response = post(admin_client, kind="tool", name="Дрель", category=category.pk, quantity=51)

    assert response.status_code == 200 and Tool.objects.count() == 0


def test_services_reject_bad_input(user, category):
    with pytest.raises(services.ServiceError):
        services.register_tools(user=user, name=" ", category=category)
    with pytest.raises(services.ServiceError):
        services.register_tools(user=user, name="Дрель", category=category, count=0)
    with pytest.raises(services.ServiceError):
        services.register_hand_tool(user=user, name="Гвозди", category=category, quantity=0)
    assert Tool.objects.count() == 0 and HandTool.objects.count() == 0     # откат: ничего не осталось

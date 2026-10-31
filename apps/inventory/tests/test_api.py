"""
API только для чтения: доступ, списки, фильтры, история, «доступно» и «на объекте».
admin_client (pytest-django) это клиент, уже вошедший как суперпользователь.
"""
from apps.inventory import services


def results(response):
    """Списки отдаются постранично: сами записи лежат в ключе results."""
    return response.json()["results"]


def test_api_requires_login(client):
    assert client.get("/api/tools/").status_code in (401, 403)


def test_api_is_read_only(admin_client, tool):
    assert admin_client.post("/api/tools/", {"name": "x"}).status_code == 405
    assert admin_client.delete(f"/api/tools/{tool.pk}/").status_code == 405


def test_tools_list_and_detail(admin_client, tool):
    listing = results(admin_client.get("/api/tools/"))
    assert [row["name"] for row in listing] == ["Перфоратор"]
    assert listing[0]["status"] == "available"
    assert listing[0]["status_display"] == "На складе"
    assert listing[0]["current_site"] is None
    assert listing[0]["current_site_name"] is None

    detail = admin_client.get(f"/api/tools/{tool.pk}/").json()
    assert detail["category_name"] == "Электроинструмент"


def test_tools_filter_by_status(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    assert results(admin_client.get("/api/tools/?status=available")) == []
    issued = results(admin_client.get("/api/tools/?status=issued"))
    assert [row["id"] for row in issued] == [tool.pk]
    assert issued[0]["current_site_name"] == site.name


def test_tool_history_shows_cancelled(admin_client, user, tool, site):
    batch = services.issue_to_site(user=user, site=site, tools=[tool])
    services.cancel_batch(user=user, batch=batch)

    rows = results(admin_client.get(f"/api/tools/{tool.pk}/history/"))

    assert [row["type"] for row in rows] == ["issued", "added"]  # новые сверху
    assert rows[0]["is_cancelled"] is True
    assert rows[0]["cancelled_by_name"] == user.username
    assert rows[0]["site_name"] == site.name
    assert rows[1]["site_name"] is None  # постановка на баланс без объекта


def test_hand_tools_list_has_available(admin_client, user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 4)])

    row = results(admin_client.get("/api/hand-tools/"))[0]

    assert (row["total"], row["issued"], row["available"]) == (10, 4, 6)


def test_hand_tool_history_has_quantity(admin_client, stocked_hand_tool):
    rows = results(admin_client.get(f"/api/hand-tools/{stocked_hand_tool.pk}/history/"))

    assert rows[0]["type"] == "added"
    assert rows[0]["quantity"] == 10


def test_available_excludes_issued_and_exhausted(admin_client, user, tool, stocked_hand_tool, site):
    services.issue_to_site(
        user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 10)],
    )

    data = admin_client.get("/api/available/").json()

    assert data == {"tools": [], "hand_tools": []}


def test_available_lists_free_items(admin_client, tool, stocked_hand_tool):
    data = admin_client.get("/api/available/").json()

    assert [row["id"] for row in data["tools"]] == [tool.pk]
    assert [row["id"] for row in data["hand_tools"]] == [stocked_hand_tool.pk]


def test_on_site_lists_what_is_there(admin_client, user, tool, stocked_hand_tool, site):
    services.issue_to_site(
        user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 3)],
    )

    data = admin_client.get(f"/api/sites/{site.pk}/on-site/").json()

    assert [row["id"] for row in data["tools"]] == [tool.pk]
    assert data["hand_tools"][0]["quantity"] == 3
    assert data["hand_tools"][0]["hand_tool"]["id"] == stocked_hand_tool.pk


def test_unknown_site_is_404(admin_client):
    assert admin_client.get("/api/sites/999999/on-site/").status_code == 404


def test_sites_and_categories_lists(admin_client, site, category):
    assert [row["name"] for row in results(admin_client.get("/api/sites/"))] == [site.name]
    assert [row["name"] for row in results(admin_client.get("/api/categories/"))] == [category.name]

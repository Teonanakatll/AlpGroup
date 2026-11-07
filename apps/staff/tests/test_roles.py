"""
Роли (SPEC 7.1): кто какую роль получает, кого пускают к операциям на сайте и в API,
и что кнопки операций спрятаны у тех, кому только смотреть.
"""
import pytest
from django.contrib.auth.models import Group

from apps.inventory import services
from apps.inventory.models import Category, Tool, ToolMovement
from apps.sites.models import Site
from apps.staff import roles


@pytest.fixture
def make_user(django_user_model):
    def make(username, role=None):
        user = django_user_model.objects.create_user(username=username, password="x")
        if role:
            roles.assign_role(user, role)
        return user
    return make


@pytest.fixture
def stock(db, admin_user):
    """Одна штучная позиция на складе и объект — чтобы было что выдавать и отменять."""
    category = Category.objects.create(name="Электроинструмент")
    tool = services.register_tool(user=admin_user, name="Перфоратор", category=category)
    site = Site.objects.create(name="Объект на Ленина, 5")
    return tool, site


class FakeRequest:
    def __init__(self, user):
        self.user = user


# ---------------------------------------------------------------------------
# Группы и определение роли
# ---------------------------------------------------------------------------

def test_migration_creates_role_groups(db):
    assert set(Group.objects.values_list("name", flat=True)) >= set(roles.GROUPS.values())


@pytest.mark.parametrize("role", [roles.ADMIN, roles.STOREKEEPER, roles.RESPONSIBLE, roles.VIEWER])
def test_role_by_group(make_user, role):
    assert roles.user_role(make_user("u", role)) == role


def test_superuser_is_admin_and_no_group_is_viewer(make_user, admin_user):
    assert roles.user_role(admin_user) == roles.ADMIN
    assert roles.user_role(make_user("new")) == roles.VIEWER      # без роли — только просмотр


def test_strongest_group_wins_and_assign_role_replaces(make_user):
    user = make_user("u", roles.VIEWER)
    user.groups.add(Group.objects.get(name=roles.GROUPS[roles.STOREKEEPER]))
    assert roles.user_role(user) == roles.STOREKEEPER

    roles.assign_role(user, roles.RESPONSIBLE)                    # старые ролевые группы убраны
    assert roles.user_role(user) == roles.RESPONSIBLE
    assert user.groups.count() == 1


@pytest.mark.parametrize("role, operate, manage", [
    (roles.ADMIN, True, True),
    (roles.STOREKEEPER, True, False),
    (roles.RESPONSIBLE, False, False),
    (roles.VIEWER, False, False),
])
def test_rights_by_role(make_user, role, operate, manage):
    request = FakeRequest(make_user("u", role))
    assert roles.can_operate(request) is operate
    assert roles.can_manage(request) is manage


# ---------------------------------------------------------------------------
# Сайт
# ---------------------------------------------------------------------------

OPERATION_PAGES = [
    "/operations/", "/operations/add/", "/operations/issue/", "/operations/receive/",
    "/operations/missing/", "/operations/write-off/", "/operations/servicing/",
    "/operations/from-servicing/",
]


@pytest.mark.parametrize("role", [roles.VIEWER, roles.RESPONSIBLE])
def test_viewer_redirected_from_operation_pages(client, make_user, role):
    client.force_login(make_user("u", role))
    for url in OPERATION_PAGES:
        response = client.get(url)
        assert response.status_code == 302, url
        assert response["Location"] == "/"


def test_storekeeper_opens_operation_pages(client, make_user):
    client.force_login(make_user("u", roles.STOREKEEPER))
    for url in OPERATION_PAGES[1:]:                                # /operations/ сам редиректит на выдачу
        assert client.get(url).status_code == 200, url


def test_viewer_cannot_issue_via_post(client, make_user, stock):
    tool, site = stock
    client.force_login(make_user("u", roles.VIEWER))
    client.post("/operations/issue/", {"site": site.pk, "tools": [tool.pk]})
    assert not ToolMovement.objects.filter(type="issued").exists()
    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE


def test_viewer_cannot_cancel(client, make_user, stock, admin_user):
    tool, site = stock
    services.issue_to_site(user=admin_user, site=site, tools=[tool])
    movement = ToolMovement.objects.get(type="issued")
    client.force_login(make_user("u", roles.VIEWER))

    client.post(f"/journal/cancel/tool/{movement.pk}/")
    movement.refresh_from_db()
    assert not movement.is_cancelled


def test_buttons_hidden_for_viewer(client, make_user, stock, admin_user):
    tool, site = stock
    services.issue_to_site(user=admin_user, site=site, tools=[tool])
    client.force_login(make_user("u", roles.VIEWER))

    home = client.get("/").content.decode()
    assert 'href="/operations/"' not in home
    assert "Наблюдатель" in home                                   # подпись роли в меню
    journal = client.get("/journal/").content.decode()
    assert "btn-cancel" not in journal
    position = client.get(f"/inventory/tool/{tool.pk}/").content.decode()
    assert "photo-upload" not in position and "btn-cancel" not in position


def test_buttons_shown_for_storekeeper(client, make_user, stock, admin_user):
    tool, site = stock
    services.issue_to_site(user=admin_user, site=site, tools=[tool])
    client.force_login(make_user("u", roles.STOREKEEPER))

    assert 'href="/operations/"' in client.get("/").content.decode()
    assert "btn-cancel" in client.get("/journal/").content.decode()
    assert "photo-upload" in client.get(f"/inventory/tool/{tool.pk}/").content.decode()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_api_operations_forbidden_for_viewer(client, make_user, stock):
    tool, site = stock
    client.force_login(make_user("u", roles.VIEWER))
    response = client.post("/api/issue/", {"site": site.pk, "tools": [tool.pk]},
                           content_type="application/json")
    assert response.status_code == 403
    assert not ToolMovement.objects.filter(type="issued").exists()
    assert client.get("/api/tools/").status_code == 200           # смотреть можно


def test_api_operations_allowed_for_storekeeper(client, make_user, stock):
    tool, site = stock
    client.force_login(make_user("u", roles.STOREKEEPER))
    response = client.post("/api/issue/", {"site": site.pk, "tools": [tool.pk]},
                           content_type="application/json")
    assert response.status_code == 201

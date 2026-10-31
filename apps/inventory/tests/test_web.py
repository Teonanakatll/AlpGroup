"""
Страницы сайта (apps/web): доступ, вход и выход, главная, инвентарь, выборка search_inventory.

admin_client (pytest-django) это клиент, уже вошедший как суперпользователь.
Проверяем, что нужные данные доходят до страницы; вид и анимации проверяются глазами.
"""
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.inventory import selectors, services
from apps.inventory.models import ToolPhoto


def page(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return response.content.decode()


# ---------------------------------------------------------------------------
# Доступ, вход, выход
# ---------------------------------------------------------------------------

def test_pages_require_login(client):
    for url in ("/", "/inventory/"):
        response = client.get(url)
        assert response.status_code == 302
        assert response["Location"].startswith("/login/")


def test_login_page_is_open(client):
    assert "Вход" in page(client, "/login/")


def test_login_leads_to_home(client, django_user_model):
    django_user_model.objects.create_user(username="ivan", password="pass12345")

    response = client.post("/login/", {"username": "ivan", "password": "pass12345"})

    assert response.status_code == 302
    assert response["Location"] == "/"
    assert client.get("/").status_code == 200


def test_wrong_password_shows_error(client, django_user_model):
    django_user_model.objects.create_user(username="ivan", password="pass12345")

    response = client.post("/login/", {"username": "ivan", "password": "wrong"})

    assert response.status_code == 200
    assert "Неверный логин или пароль" in response.content.decode()


def test_logout_is_post_only_and_leads_to_login(admin_client):
    assert admin_client.get("/logout/").status_code == 405   # Django разрешает выход только POST

    response = admin_client.post("/logout/")

    assert response.status_code == 302
    assert response["Location"] == "/login/"
    assert admin_client.get("/").status_code == 302          # снова нужен вход


def test_settings_link_only_for_staff(client, user, admin_client):
    client.force_login(user)                                 # обычный сотрудник
    assert "Настройки" not in page(client, "/")
    assert "Настройки" in page(admin_client, "/")


# ---------------------------------------------------------------------------
# Главная
# ---------------------------------------------------------------------------

def test_home_includes_theme_assets(admin_client):
    html = page(admin_client, "/")

    assert "web/css/app.css" in html and "web/js/app.js" in html
    assert 'id="i-home"' in html                              # набор иконок подключён
    assert "logo-alp-dark.png" in html


def test_home_shows_summary_and_recent_operations(admin_client, user, tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 4)])

    html = page(admin_client, "/")

    assert 'data-count="6"' in html        # на складе: 6 из 10 молотков (перфоратор выдан)
    assert 'data-count="5"' in html        # выдано: перфоратор и 4 молотка
    assert "Перфоратор" in html and "Молоток" in html and site.name in html


def test_home_marks_cancelled_operation(admin_client, user, tool, site):
    batch = services.issue_to_site(user=user, site=site, tools=[tool])
    services.cancel_batch(user=user, batch=batch)

    assert "отменена" in page(admin_client, "/")


def test_home_lists_tools_needing_attention(admin_client, user, tool):
    services.send_to_servicing(user=user, tools=[tool])

    html = page(admin_client, "/")

    assert "Требует внимания" in html
    assert "Перфоратор" in html


def test_home_on_empty_database(admin_client):
    html = page(admin_client, "/")

    assert "Операций пока нет" in html
    assert "Всё в порядке" in html
    assert 'data-count="100"' in html       # считать нечего: парк «в строю» на 100%


# ---------------------------------------------------------------------------
# Инвентарь
# ---------------------------------------------------------------------------

def test_inventory_lists_both_kinds(admin_client, tool, stocked_hand_tool):
    html = page(admin_client, "/inventory/")

    assert "Перфоратор" in html and "Молоток" in html


def test_inventory_search_by_name(admin_client, tool, stocked_hand_tool):
    html = page(admin_client, "/inventory/?q=Молот")

    assert "Молоток" in html and "Перфоратор" not in html


def test_inventory_status_filter_hides_hand_tools(admin_client, user, tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    html = page(admin_client, "/inventory/?status=issued")

    assert "Перфоратор" in html
    assert "Молоток" not in html            # у ручного инструмента статусов нет


# Минимальный корректный GIF 1x1: настоящая картинка для ImageField без внешних файлов.
TINY_GIF = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00"
            b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")


def test_inventory_shows_main_photo_instead_of_icon(admin_client, tool, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path                      # файлы теста не попадают в настоящую media/
    ToolPhoto.objects.create(tool=tool, image=SimpleUploadedFile("a.gif", TINY_GIF), is_main=True)
    ToolPhoto.objects.create(tool=tool, image=SimpleUploadedFile("b.gif", TINY_GIF))   # не главное

    html = page(admin_client, "/inventory/")

    assert html.count('class="item-photo"') == 1        # только главное фото
    assert "/media/tools/" in html


def test_inventory_without_photo_keeps_icon(admin_client, tool):
    html = page(admin_client, "/inventory/")

    assert 'class="item-photo"' not in html
    assert "#i-box" in html


def test_inventory_unknown_status_is_ignored(admin_client, tool):
    assert "Перфоратор" in page(admin_client, "/inventory/?status=hack")


def test_inventory_empty_hints_at_seed_command(admin_client):
    assert "seed_demo" in page(admin_client, "/inventory/")


# ---------------------------------------------------------------------------
# Выборка search_inventory
# ---------------------------------------------------------------------------

def test_search_inventory_by_name(tool, stocked_hand_tool):
    tools, hand_tools = selectors.search_inventory("Перфо")

    assert [t.name for t in tools] == ["Перфоратор"]
    assert list(hand_tools) == []


def test_search_inventory_status_applies_to_tools_only(tool, stocked_hand_tool):
    tools, hand_tools = selectors.search_inventory(status="available")

    assert [t.name for t in tools] == ["Перфоратор"]
    assert list(hand_tools) == []


def test_search_inventory_without_filters_returns_everything(tool, stocked_hand_tool):
    tools, hand_tools = selectors.search_inventory()

    assert len(tools) == 1 and len(hand_tools) == 1

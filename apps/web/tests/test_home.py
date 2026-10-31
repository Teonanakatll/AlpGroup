"""Главная страница. admin_client это клиент, уже вошедший как суперпользователь (pytest-django)."""
from apps.inventory import services


def test_home_requires_login(client):
    response = client.get("/")

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]
    assert "next=/" in response["Location"]


def test_home_shows_summary_logo_and_menu(admin_client, tool, stocked_hand_tool):
    response = admin_client.get("/")
    html = response.content.decode()

    assert response.status_code == 200
    assert "logo-dark.png" in html                 # логотип ALP GROUP в меню
    assert 'data-count="11"' in html               # на складе: 1 перфоратор + 10 молотков
    assert "штучных 1 · ручных 10" in html
    assert "Операций пока нет" not in html         # приход уже записан в журнал
    assert "Всё в порядке" in html                 # ремонта и потерь нет
    assert 'class="toasts"' in html                # место для всплывающих сообщений есть


def test_home_lists_recent_operations_and_attention(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])
    services.mark_missing(user=user, site=site, tools=[tool])

    html = admin_client.get("/").content.decode()

    assert "Не найден: Перфоратор" in html
    assert site.name in html
    assert "Требует внимания" in html
    assert "Не найден</span>" in html              # подпись статуса в блоке «требует внимания»


def test_home_works_on_empty_database(admin_client):
    response = admin_client.get("/")

    assert response.status_code == 200
    assert "Операций пока нет" in response.content.decode()

"""DEMO_USER: автовход под гостем для показа сайта без пароля."""
import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def demo(settings, db):  # после no_demo_autologin из conftest.py
    settings.DEMO_USER = "гость"


def test_without_flag_login_required(client, db):
    assert client.get("/").status_code == 302


def test_guest_logged_in_and_created_without_staff(demo, client):
    assert client.get("/").status_code == 200

    guest = get_user_model().objects.get(username="гость")
    assert not guest.is_staff and not guest.is_superuser
    assert not guest.has_usable_password()


def test_guest_reused_on_next_visit(demo, client):
    client.get("/")
    client.logout()
    client.get("/")
    assert get_user_model().objects.filter(username="гость").count() == 1


def test_login_page_and_admin_not_auto_logged(demo, client):
    """На странице входа и в админке гость не создаётся: там входят под своим логином."""
    client.get("/login/")
    client.get("/admin/")
    assert not get_user_model().objects.filter(username="гость").exists()


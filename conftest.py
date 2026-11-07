"""Общие настройки тестов: быстрый хешер паролей (обычный PBKDF2 нарочно медленный, а тестам он не нужен)."""
import pytest


@pytest.fixture(autouse=True)
def fast_password_hasher(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def no_demo_autologin(settings):
    """DEMO_USER из .env (показ без входа) не должен влиять на тесты: по умолчанию вход нужен."""
    settings.DEMO_USER = ""


@pytest.fixture(autouse=True)
def plain_static_storage(settings):
    """В тестах статика без хешей в именах: collectstatic не запускается, манифеста нет."""
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture(autouse=True)
def no_demo_role_switch(settings):
    """Переключатель ролей (DEMO_ROLE_SWITCH из .env) в тестах выключен: права только по группам."""
    settings.DEMO_ROLE_SWITCH = False

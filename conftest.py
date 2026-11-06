"""Общие настройки тестов: быстрый хешер паролей (обычный PBKDF2 нарочно медленный, а тестам он не нужен)."""
import pytest


@pytest.fixture(autouse=True)
def fast_password_hasher(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def no_demo_autologin(settings):
    """DEMO_USER из .env (показ без входа) не должен влиять на тесты: по умолчанию вход нужен."""
    settings.DEMO_USER = ""

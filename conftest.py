"""Общие настройки тестов: быстрый хешер паролей (обычный PBKDF2 нарочно медленный, а тестам он не нужен)."""
import pytest


@pytest.fixture(autouse=True)
def fast_password_hasher(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

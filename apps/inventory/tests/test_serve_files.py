"""SERVE_FILES: при DEBUG=0 (показ через туннель) Django сам отдаёт статику и фото."""
import importlib

import pytest
from django.urls import clear_url_caches

import config.urls


@pytest.fixture
def reload_urls():
    """Маршруты в config/urls.py зависят от настроек и строятся при импорте: перечитываем их."""
    def reload():
        importlib.reload(config.urls)
        clear_url_caches()

    yield reload
    reload()                     # после теста настройки вернутся, вернём и обычные маршруты


@pytest.fixture
def demo_settings(settings, tmp_path):
    settings.DEBUG = False
    settings.SERVE_FILES = True
    settings.ALLOWED_HOSTS = ["testserver"]
    settings.MEDIA_ROOT = tmp_path
    return settings


def test_static_and_media_served_when_flag_on(demo_settings, reload_urls, client):
    (demo_settings.MEDIA_ROOT / "photo.txt").write_text("ok")
    reload_urls()

    assert client.get("/static/web/img/gem.svg").status_code == 200
    response = client.get("/media/photo.txt")
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"ok"


def test_files_not_served_without_flag(demo_settings, reload_urls, client):
    demo_settings.SERVE_FILES = False
    (demo_settings.MEDIA_ROOT / "photo.txt").write_text("ok")
    reload_urls()

    assert client.get("/static/web/img/gem.svg").status_code == 404
    assert client.get("/media/photo.txt").status_code == 404

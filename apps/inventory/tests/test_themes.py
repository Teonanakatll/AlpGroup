"""
Темы оформления: список в apps/web/themes.py согласован с app.css и выводится на странице.
"""
import json
import re
from pathlib import Path

from apps.web.themes import DEFAULT_THEME, THEMES

CSS = (Path(__file__).resolve().parents[2] / "web" / "static" / "web" / "css" / "app.css").read_text(encoding="utf-8")

# Палитры, которые задают базу своего режима и описаны общим блоком, а не отдельным :root[data-theme="..."]
BASE_PALETTES = {"summit": ':root[data-theme="summit"]', "nexora": ':root[data-mode="light"]'}


def test_theme_list_is_consistent():
    ids = [theme.id for theme in THEMES]
    assert len(ids) == len(set(ids)), "id тем повторяются"
    assert DEFAULT_THEME in ids
    assert {theme.mode for theme in THEMES} <= {"dark", "light"}
    for theme in THEMES:
        assert len(theme.swatch) == 3 and all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in theme.swatch), theme.id


def test_every_theme_has_a_palette_in_css():
    for theme in THEMES:
        selector = BASE_PALETTES.get(theme.id, f':root[data-theme="{theme.id}"]')
        assert selector + " {" in CSS or selector + "," in CSS, f"нет блока цветов для темы {theme.id}"


def test_menu_and_modes_on_page(admin_client):
    html = admin_client.get("/").content.decode()

    for theme in THEMES:
        assert f'data-set-theme="{theme.id}"' in html
    modes = json.loads(re.search(r'<script id="theme-modes" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert modes == {theme.id: theme.mode for theme in THEMES}
    assert 'data-theme="summit" data-mode="dark"' in html     # тема по умолчанию до выбора в браузере

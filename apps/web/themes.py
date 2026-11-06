"""
Темы оформления сайта: один список на всё (меню в шапке, выбор темы до отрисовки страницы, тест).

Тема = палитра (блок переменных :root[data-theme="..."] в app.css) и режим:
dark — оформление как у Summit (стекло, неон), light — как у светлой Nexora (3D-кнопки, тени).
Чтобы добавить тему: блок переменных в app.css и строка здесь.
"""
from dataclasses import dataclass

DEFAULT_THEME = "summit"


@dataclass(frozen=True)
class Theme:
    id: str          # значение data-theme
    name: str        # как подписано в меню
    mode: str        # "dark" или "light"
    swatch: tuple    # три цвета для кружков в меню: фон, блок, акцент


THEMES = [
    Theme("summit", "Summit", "dark", ("#05070a", "#10151a", "#b6ff2e")),
    Theme("dracula", "Dracula", "dark", ("#191a21", "#282a36", "#50fa7b")),
    Theme("synthwave", "Synthwave '84", "dark", ("#1b1729", "#262335", "#ff7edb")),
    Theme("cyber", "Неон киберпанк", "dark", ("#07060d", "#12101f", "#fcee0a")),
    Theme("monokai", "Monokai Pro", "dark", ("#19181a", "#2d2a2e", "#ffd866")),
    Theme("palenight", "Material Palenight", "dark", ("#1b1e2b", "#292d3e", "#c792ea")),
    Theme("gruvdark", "Gruvbox Dark", "dark", ("#1d2021", "#282828", "#fabd2f")),
    Theme("jellyfish", "JellyFish", "dark", ("#000124", "#0b0a3c", "#ff0055")),
    Theme("justblack", "Just Black", "dark", ("#000000", "#0f111a", "#80cbc4")),
    Theme("hacker", "Hacker", "dark", ("#000000", "#030c03", "#00ff00")),
    Theme("nexora", "Nexora", "light", ("#cdd1d8", "#ffffff", "#96ff00")),
    Theme("onelight", "Atom One Light", "light", ("#d9d9db", "#fafafa", "#4078f2")),
    Theme("solarlight", "Solarized Light", "light", ("#eee8d5", "#fdf6e3", "#b58900")),
    Theme("gruvlight", "Gruvbox Light", "light", ("#ebdbb2", "#fbf1c7", "#d65d0e")),
]

# id темы -> режим: нужен скрипту в <head>, чтобы выставить data-mode до отрисовки
THEME_MODES = {theme.id: theme.mode for theme in THEMES}


def themes(request):
    """Контекст-процессор: список тем для меню и словарь режимов для скрипта в base.html."""
    return {
        "site_themes_dark": [t for t in THEMES if t.mode == "dark"],
        "site_themes_light": [t for t in THEMES if t.mode == "light"],
        "site_theme_modes": THEME_MODES,
    }

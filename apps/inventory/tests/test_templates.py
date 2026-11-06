"""
Проверки шаблонов сайта, которым не нужна база.

Комментарий {# ... #} в Django работает только в одну строку: многострочный
шаблонизатор не узнаёт и выводит прямо на страницу. Для длинных — {% comment %}.
"""
import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[2] / "web" / "templates"


def test_no_multiline_hash_comments():
    problems = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\{#(.*?)#\}", text, flags=re.S):
            if "\n" in match.group(1):
                line = text.count("\n", 0, match.start()) + 1
                problems.append(f"{path.relative_to(TEMPLATES)}:{line}")
    assert not problems, "Многострочный {# #} попадёт на страницу, нужен {% comment %}: " + ", ".join(problems)

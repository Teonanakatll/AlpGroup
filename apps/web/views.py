"""
Страницы сайта. Вьюхи тонкие: данные берутся из selectors.py, здесь только подготовка
к показу. Все страницы доступны только вошедшим (login_required).
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.inventory import selectors
from apps.inventory.models import Tool

# Как показывать тип операции: иконка из набора (_icons.html) и цвет (класс tone-*).
# Без класса цвет лаймовый.
OPERATION_STYLE = {
    "added": ("plus", ""),
    "issued": ("arrow-up-right", ""),
    "returned": ("arrow-left", "tone-blue"),
    "servicing": ("wrench", "tone-violet"),
    "missing": ("alert", "tone-orange"),
    "written_off": ("trash", "tone-red"),
}


@login_required
def home(request):
    recent = selectors.recent_movements(limit=6)
    for operation in recent:
        operation["icon"], operation["tone"] = OPERATION_STYLE[operation["type"]]
    return render(request, "web/home.html", {
        "summary": selectors.stock_summary(),
        "recent": recent,
        "attention": selectors.tools_needing_attention(limit=5),
    })


@login_required
def inventory(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if status not in Tool.Status.values:   # чужое значение в адресе просто игнорируем
        status = ""
    tools, hand_tools = selectors.search_inventory(query, status)
    return render(request, "web/inventory.html", {
        "tools": tools,
        "hand_tools": hand_tools,
        "query": query,
        "status": status,
        "statuses": Tool.Status.choices,
    })

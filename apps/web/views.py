"""
Страницы сайта. Вьюхи тонкие: данные берутся из selectors.py, здесь только подготовка
к показу. Все страницы доступны только вошедшим (login_required).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.inventory import selectors, services
from apps.inventory.forms import ReceiveFromSiteForm, SiteOperationForm
from apps.inventory.models import Tool
from apps.sites.models import Site

from .positions import Positions, parse_positions

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


# ---------------------------------------------------------------------------
# Операции: выдача и приём
# ---------------------------------------------------------------------------

def _count_text(tools, hand_tools):
    parts = []
    if tools:
        parts.append(f"штучных {len(tools)}")
    if hand_tools:
        parts.append(f"ручных позиций {len(hand_tools)}")
    return ", ".join(parts)


def _operation_context(request, *, mode, form, positions, site, errors):
    """Всё, что нужно странице выдачи или приёма (общая часть)."""
    if mode == "issue":
        tools = selectors.available_tools()
        hand_rows = [(hand, hand.available) for hand in selectors.available_hand_tools()]
    elif site is not None:
        tools = selectors.tools_on_site(site)
        hand_rows = selectors.hand_tools_on_site(site)
    else:
        tools, hand_rows = [], []
    return {
        "mode": mode,
        "form": form,
        "errors": errors,
        "site": site,
        "tools": tools,
        "hand_rows": [
            {"hand": hand, "max": maximum, "qty": positions.quantities.get(hand.pk, "")}
            for hand, maximum in hand_rows
        ],
        "selected_tools": positions.selected_tools,
    }


def _site_from(value):
    """Объект из адреса или формы; чужое или пустое значение даёт None."""
    try:
        return Site.objects.filter(pk=int(value)).first()
    except (TypeError, ValueError):
        return None


@login_required
def operations(request):
    return redirect("web:issue")


@login_required
def issue(request):
    """Выдача набора на объект: выбрать объект и позиции, нажать «Выдать»."""
    positions, errors = Positions(), []
    if request.method == "POST":
        form = SiteOperationForm(request.POST)
        positions = parse_positions(request.POST)
        errors = list(positions.errors)
        if form.is_valid() and not errors:
            try:
                services.issue_to_site(
                    user=request.user, site=form.cleaned_data["site"],
                    tools=positions.tools, hand_tools=positions.hand_tools,
                    taken_by=form.cleaned_data["taken_by"], note=form.cleaned_data["note"],
                )
            except services.ServiceError as error:
                errors = str(error).splitlines()     # по строке на каждую проблемную позицию
            else:
                messages.success(
                    request,
                    f"Выдано на «{form.cleaned_data['site']}»: {_count_text(positions.tools, positions.hand_tools)}.",
                )
                return redirect("web:issue")
    else:
        form = SiteOperationForm()
    form.fields["site"].empty_label = "Выберите объект…"
    context = _operation_context(request, mode="issue", form=form, positions=positions, site=None, errors=errors)
    return render(request, "web/operation.html", context)


@login_required
def receive(request):
    """
    Приём с объекта. Список позиций зависит от объекта: при выборе объекта HTMX запрашивает
    эту же страницу с ?site=<id> и подменяет только блок позиций (отдаём кусок, не всю страницу).
    """
    positions, errors = Positions(), []
    if request.method == "POST":
        form = ReceiveFromSiteForm(request.POST)
        positions = parse_positions(request.POST)
        errors = list(positions.errors)
        site = _site_from(request.POST.get("site"))
        if form.is_valid() and not errors:
            try:
                services.receive_from_site(
                    user=request.user, site=site,
                    tools=positions.tools, hand_tools=positions.hand_tools,
                    taken_by=form.cleaned_data["taken_by"], note=form.cleaned_data["note"],
                )
            except services.ServiceError as error:
                errors = str(error).splitlines()
            else:
                messages.success(
                    request,
                    f"Принято с «{site}»: {_count_text(positions.tools, positions.hand_tools)}.",
                )
                return redirect("web:receive")
    else:
        site = _site_from(request.GET.get("site"))
        form = ReceiveFromSiteForm(initial={"site": site})
    form.fields["site"].empty_label = "Выберите объект…"
    form.fields["site"].widget.attrs.update({
        "hx-get": reverse("web:receive"), "hx-target": "#positions", "hx-swap": "outerHTML",
        "hx-trigger": "change", "data-site-select": "",
    })
    context = _operation_context(request, mode="receive", form=form, positions=positions, site=site, errors=errors)
    if request.headers.get("HX-Request"):
        return render(request, "web/_positions.html", context)
    return render(request, "web/operation.html", context)

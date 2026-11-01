"""
Страницы сайта. Вьюхи тонкие: данные берутся из selectors.py, здесь только подготовка
к показу. Все страницы доступны только вошедшим (login_required).
"""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.inventory import selectors, services
from apps.inventory.forms import ReceiveFromServicingForm, ReceiveFromSiteForm
from apps.inventory.models import Tool
from apps.sites import services as site_services
from apps.sites.models import Site

from .forms import IssueForm, MissingForm, ServicingForm, WriteOffForm
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


# Заголовок, подсказка и подпись кнопки каждой операции (одна страница-шаблон на все)
OPERATION_TEXT = {
    "issue": ("Выдача на объект", "Отметьте штучный инструмент и укажите количество ручного, затем выберите объект.", "Выдать"),
    "receive": ("Приём с объекта", "Выберите объект: покажем всё, что на нём числится.", "Принять"),
    "missing": ("Не найден на объекте", "Выберите объект и отметьте то, что не нашли. Запись останется в журнале как потеря.", "Отметить"),
    "write_off": ("Списание", "Выберите склад или объект и отметьте списываемое: оно уходит из учёта, запись остаётся в журнале.", "Списать"),
    "servicing": ("Отправка в ремонт", "Только штучный инструмент: со склада или с объекта.", "В ремонт"),
    "from_servicing": ("Приём из ремонта", "Отметьте инструмент, который вернулся из ремонта на склад.", "Принять"),
}


def _lists(mode, site):
    """Что показывать для выбора: (штучные, ручные как пары (позиция, максимум))."""
    warehouse_hands = [(hand, hand.available) for hand in selectors.available_hand_tools()]
    if mode == "issue":
        return selectors.available_tools(), warehouse_hands
    if mode == "from_servicing":
        return selectors.tools_in_servicing(), []
    if mode == "servicing":
        return (selectors.tools_on_site(site) if site else selectors.available_tools()), []
    if mode == "write_off" and site is None:
        return selectors.tools_for_write_off(), warehouse_hands
    if site is None:                      # приём и «не найден» работают только с объектом
        return [], []
    return selectors.tools_on_site(site), selectors.hand_tools_on_site(site)


def _empty_text(mode, site):
    if mode == "issue":
        return "На складе сейчас нечего выдавать."
    if mode == "from_servicing":
        return "Сейчас ничего не в ремонте."
    if site:
        return f"На объекте «{site}» ничего не числится."
    if mode in ("receive", "missing"):
        return "Выберите объект, чтобы увидеть, что на нём числится."
    return "На складе нечего списывать." if mode == "write_off" else "На складе нечего отправлять в ремонт."


def _operation_context(request, *, mode, form, positions, site, errors):
    """Всё, что нужно странице любой операции (общая часть)."""
    tools, hand_rows = _lists(mode, site)
    title, hint, button = OPERATION_TEXT[mode]
    on_site = mode in ("receive", "missing") or (mode in ("write_off", "servicing") and site is not None)
    return {
        "mode": mode,
        "title": title, "hint": hint, "button": button,
        "form": form,
        "errors": errors,
        "site": site,
        "tools": tools,
        "hand_rows": [
            {"hand": hand, "max": maximum, "qty": positions.quantities.get(hand.pk, "")}
            for hand, maximum in hand_rows
        ],
        "selected_tools": positions.selected_tools,
        "hand_where": "на объекте" if on_site else "на складе",
        "show_status": mode == "write_off" and site is None,   # со склада списывают и «в ремонте», и «не найден»
        "empty_text": _empty_text(mode, site),
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
    """
    Выдача набора на объект: выбрать объект (или ввести новый) и позиции, нажать «Выдать».
    Новый объект создаётся в одной транзакции с выдачей: при отказе выдачи он не остаётся.
    """
    positions, errors = Positions(), []
    if request.method == "POST":
        form = IssueForm(request.POST)
        positions = parse_positions(request.POST)
        errors = list(positions.errors)
        if form.is_valid() and not errors:
            data = form.cleaned_data
            try:
                with transaction.atomic():
                    if data["new_site"]:
                        site, created = site_services.get_or_create_site(data["new_site"])
                    else:
                        site, created = data["site"], False
                    services.issue_to_site(
                        user=request.user, site=site,
                        tools=positions.tools, hand_tools=positions.hand_tools,
                        taken_by=data["taken_by"], note=data["note"],
                    )
            except services.ServiceError as error:
                errors = str(error).splitlines()     # по строке на каждую проблемную позицию
            else:
                new_note = " (новый объект)" if created else ""
                messages.success(
                    request,
                    f"Выдано на «{site}»{new_note}: {_count_text(positions.tools, positions.hand_tools)}.",
                )
                return redirect("web:issue")
    else:
        form = IssueForm()
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


# ---------------------------------------------------------------------------
# Не найден, списание, ремонт (общий ход для всех четырёх)
# ---------------------------------------------------------------------------

def _run_missing(user, site, positions, data):
    return services.mark_missing(
        user=user, site=site, tools=positions.tools, hand_tools=positions.hand_tools,
        taken_by=data["taken_by"], note=data["note"],
    )


def _run_write_off(user, site, positions, data):
    return services.write_off(
        user=user, site=site, tools=positions.tools, hand_tools=positions.hand_tools, note=data["note"],
    )


def _run_servicing(user, site, positions, data):
    if positions.hand_tools:
        raise services.ServiceError("Ручной инструмент в ремонт не отправляется.")
    return services.send_to_servicing(
        user=user, tools=positions.tools, site=site, taken_by=data["taken_by"], note=data["note"],
    )


def _run_from_servicing(user, site, positions, data):
    if positions.hand_tools:
        raise services.ServiceError("Из ремонта принимается только штучный инструмент.")
    return services.receive_from_servicing(
        user=user, tools=positions.tools, taken_by=data["taken_by"], note=data["note"],
    )


def _place(site):
    return f"с объекта «{site}»" if site else "со склада"


# mode -> (форма, функция операции, адрес страницы, текст успеха)
SITE_OPERATIONS = {
    "missing": (MissingForm, _run_missing, "web:missing",
                lambda site, text: f"Не найдено на «{site}»: {text}."),
    "write_off": (WriteOffForm, _run_write_off, "web:write_off",
                  lambda site, text: f"Списано {_place(site)}: {text}."),
    "servicing": (ServicingForm, _run_servicing, "web:servicing",
                  lambda site, text: f"Отправлено в ремонт {_place(site)}: {text}."),
    "from_servicing": (ReceiveFromServicingForm, _run_from_servicing, "web:from_servicing",
                       lambda site, text: f"Принято из ремонта: {text}."),
}


def _site_operation(request, mode):
    """
    Общий ход страницы операции над позициями места (объекта или склада).
    Если у формы есть поле «объект», его смена подгружает список через HTMX (как в приёме).
    """
    form_class, run, url_name, success = SITE_OPERATIONS[mode]
    has_site = "site" in form_class.base_fields
    positions, errors = Positions(), []
    if request.method == "POST":
        form = form_class(request.POST)
        positions = parse_positions(request.POST)
        errors = list(positions.errors)
        site = _site_from(request.POST.get("site")) if has_site else None
        if form.is_valid() and not errors:
            try:
                run(request.user, site, positions, form.cleaned_data)
            except services.ServiceError as error:
                errors = str(error).splitlines()
            else:
                messages.success(request, success(site, _count_text(positions.tools, positions.hand_tools)))
                return redirect(url_name)
    else:
        site = _site_from(request.GET.get("site")) if has_site else None
        form = form_class(initial={"site": site}) if has_site else form_class()
    if has_site:
        widget = form.fields["site"].widget
        if form.fields["site"].required:
            form.fields["site"].empty_label = "Выберите объект…"      # у необязательного остаётся «Склад»
        widget.attrs.update({
            "hx-get": reverse(url_name), "hx-target": "#positions", "hx-swap": "outerHTML",
            "hx-trigger": "change", "data-site-select": "", "data-dd-keep": "",
        })
    context = _operation_context(request, mode=mode, form=form, positions=positions, site=site, errors=errors)
    if request.method == "GET" and request.headers.get("HX-Request"):
        return render(request, "web/_positions.html", context)
    return render(request, "web/operation.html", context)


@login_required
def missing(request):
    return _site_operation(request, "missing")


@login_required
def write_off(request):
    return _site_operation(request, "write_off")


@login_required
def servicing(request):
    return _site_operation(request, "servicing")


@login_required
def from_servicing(request):
    return _site_operation(request, "from_servicing")

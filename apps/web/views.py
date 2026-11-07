"""
Страницы сайта. Вьюхи тонкие: данные берутся из selectors.py, здесь только подготовка
к показу. Все страницы доступны только вошедшим (login_required); операции, отмена и фото —
только ролям с правом операций (operator_required, apps/staff/roles.py).
"""
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.inventory import selectors, services
from apps.inventory.forms import ReceiveFromServicingForm, ReceiveFromSiteForm
from apps.inventory.models import HandTool, HandToolMovement, Tool, ToolMovement, ToolPhoto
from apps.sites import services as site_services
from apps.sites.models import Site
from apps.staff import roles
from apps.staff.roles import operator_required

from .forms import AddForm, IssueForm, MissingForm, PhotosForm, ServicingForm, WriteOffForm
from .positions import Positions, parse_positions

# Как показывать тип операции: иконка из набора (_icons.html) и цвет (класс tone-*).
# Без класса цвет лаймовый.
OPERATION_STYLE = {
    "added": ("plus", ""),
    "issued": ("arrow-up-right", ""),
    "returned": ("arrow-left", "tone-blue"),
    "servicing": ("wrench", "tone-violet"),
    "missing": ("alert", "tone-orange"),
    "written_off": ("trash", "tone-writeoff"),
}


# Вкладки операций: (mode, адрес, подпись, тип операции в журнале — от него иконка и цвет)
OPERATION_TABS = [
    ("add", "web:add", "На баланс", "added"),
    ("issue", "web:issue", "Выдача", "issued"),
    ("receive", "web:receive", "Приём", "returned"),
    ("missing", "web:missing", "Не найден", "missing"),
    ("write_off", "web:write_off", "Списание", "written_off"),
    ("servicing", "web:servicing", "В ремонт", "servicing"),
    ("from_servicing", "web:from_servicing", "Из ремонта", "returned"),
]


def _op_nav(mode):
    """Вкладки операций и иконка с цветом текущей: для шапки и панели формы."""
    tabs = []
    for tab_mode, url_name, label, kind in OPERATION_TABS:
        icon, tone = OPERATION_STYLE[kind]
        tabs.append({"mode": tab_mode, "url": reverse(url_name), "label": label, "icon": icon, "tone": tone})
    current = next(tab for tab in tabs if tab["mode"] == mode)
    return {"op_tabs": tabs, "op_icon": current["icon"], "op_tone": current["tone"]}


@login_required
def home(request):
    recent = selectors.recent_entries(limit=6)
    for entry in recent:
        _style_entry(entry)
    return render(request, "web/home.html", {
        "summary": selectors.stock_summary(),
        "recent": recent,
        "attention": selectors.tools_needing_attention(limit=5),
        "attention_total": selectors.tools_needing_attention().count(),
    })


@login_required
def inventory(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if status not in Tool.Status.values:   # чужое значение в адресе просто игнорируем
        status = ""
    tools, hand_tools = selectors.search_inventory(query, status)
    return render(request, "web/inventory.html", {
        "groups": selectors.group_by_category(tools, hand_tools),
        "open_all": bool(query or status),      # при поиске или фильтре категории раскрыты сразу
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
    "missing": ("Не найден", "Выберите склад или объект и отметьте то, что не нашли. Запись останется в журнале как потеря.", "Отметить"),
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
    if mode == "missing" and site is None:   # не нашли на складе: то, что там лежит
        return selectors.available_tools(), warehouse_hands
    if site is None:                      # приём работает только с объектом
        return [], []
    return selectors.tools_on_site(site), selectors.hand_tools_on_site(site)


def _empty_text(mode, site):
    if mode == "issue":
        return "На складе сейчас нечего выдавать."
    if mode == "from_servicing":
        return "Сейчас ничего не в ремонте."
    if site:
        return f"На объекте «{site}» ничего не числится."
    if mode == "receive":
        return "Выберите объект, чтобы увидеть, что на нём числится."
    return {
        "write_off": "На складе нечего списывать.",
        "missing": "На складе сейчас ничего не лежит.",
    }.get(mode, "На складе нечего отправлять в ремонт.")


def _operation_context(request, *, mode, form, positions, site, errors):
    """Всё, что нужно странице любой операции (общая часть)."""
    tools, hand_rows = _lists(mode, site)
    title, hint, button = OPERATION_TEXT[mode]
    on_site = mode == "receive" or (mode in ("missing", "write_off", "servicing") and site is not None)
    return {
        **_op_nav(mode),
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
        "show_status": mode == "write_off" and site is None,   # со склада списывают и «в ремонте», и «не найден»: статус плашкой
        "empty_text": _empty_text(mode, site),
    }


# Какие объекты предлагать в поле «Объект» или «Откуда»: только те, где есть что взять.
SITE_CHOICES = {
    "receive": selectors.sites_with_items,
    "missing": selectors.sites_with_items,
    "write_off": selectors.sites_with_items,
    "servicing": lambda: selectors.sites_with_items(tools_only=True),   # в ремонт только штучные
}


def _limit_sites(form, mode, site):
    """
    Оставить в выпадающем списке только объекты, где что-то числится (и выбранный, чтобы не пропал).

    Вызывается после is_valid: проверка формы идёт по всем объектам, а правила учёта
    (числится ли позиция на этом объекте) проверяет services и даёт понятный текст ошибки.
    """
    choices = SITE_CHOICES[mode]()
    if site is not None:
        choices = Site.objects.filter(pk__in=list(choices.values_list("pk", flat=True)) + [site.pk]).order_by("name")
    form.fields["site"].queryset = choices


def _site_from(value):
    """Объект из адреса или формы; чужое или пустое значение даёт None."""
    try:
        return Site.objects.filter(pk=int(value)).first()
    except (TypeError, ValueError):
        return None


@login_required
@operator_required
def operations(request):
    return redirect("web:issue")


@login_required
@operator_required
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
@operator_required
def add(request):
    """Постановка на баланс: новые штучные позиции, новая или пополнение количественной."""
    errors = []
    if request.method == "POST":
        form = AddForm(request.POST, request.FILES)
        if form.is_valid():
            data = form.cleaned_data
            try:
                if data["kind"] == "tool":
                    created = services.register_tools(user=request.user, name=data["name"], category=data["category"],
                                                      count=data["quantity"], note=data["note"])
                    if data["photo"]:               # одно фото на все штуки: файл сохраняем один раз
                        first = services.add_tool_photos(tool=created[0], images=[data["photo"]])[0]
                        for other in created[1:]:
                            services.add_tool_photos(tool=other, images=[first.image.name])
                    text = f"Поставлено на баланс: «{created[0].name}», {data['quantity']} шт."
                elif data["existing_hand"]:
                    hand = services.add_hand_tool_stock(user=request.user, hand_tool=data["existing_hand"],
                                                        quantity=data["quantity"], note=data["note"])
                    text = f"Пополнено «{hand.name}»: +{data['quantity']}, всего {hand.total}."
                else:
                    hand = services.register_hand_tool(user=request.user, name=data["name"], category=data["category"],
                                                       quantity=data["quantity"], note=data["note"])
                    text = f"Заведено «{hand.name}»: {data['quantity']} шт."
            except services.ServiceError as error:
                errors = str(error).splitlines()
            else:
                messages.success(request, text)
                return redirect("web:add")
    else:
        form = AddForm(initial={"kind": "tool"})
    return render(request, "web/add.html", {
        **_op_nav("add"),
        "mode": "add", "title": "Постановка на баланс",
        "hint": "Новый инструмент или пополнение количественной позиции. Запись попадёт в журнал.",
        "form": form, "errors": errors,
    })


@login_required
@operator_required
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
    _limit_sites(form, "receive", site)
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
                lambda site, text: f"Не найдено {f'на «{site}»' if site else 'на складе'}: {text}."),
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
        _limit_sites(form, mode, site)
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
@operator_required
def missing(request):
    return _site_operation(request, "missing")


@login_required
@operator_required
def write_off(request):
    return _site_operation(request, "write_off")


@login_required
@operator_required
def servicing(request):
    return _site_operation(request, "servicing")


@login_required
@operator_required
def from_servicing(request):
    return _site_operation(request, "from_servicing")


# ---------------------------------------------------------------------------
# Журнал, история позиции, отмена
# ---------------------------------------------------------------------------

def _style_entry(entry):
    """Иконки у строк записи журнала и у самой записи (иконка набора = иконка его операции)."""
    _style_rows(entry["rows"])
    entry["icon"], entry["tone"] = entry["rows"][0]["icon"], entry["rows"][0]["tone"]


def _style_rows(rows):
    """Добавляет к строкам журнала иконку и цвет по типу операции."""
    for row in rows:
        row["icon"], row["tone"] = OPERATION_STYLE[row["type"]]
    return rows


@login_required
def journal(request):
    """Журнал операций: наборы и одиночные строки, у каждого кнопки отмены (если можно)."""
    try:
        limit = min(max(int(request.GET.get("n", 40)), 1), 400)
    except ValueError:
        limit = 40
    only_batch = None
    try:                                           # ?batch=<uuid>: показать один набор (ссылка с главной)
        only_batch = uuid.UUID(request.GET["batch"]) if "batch" in request.GET else None
    except ValueError:
        pass
    entries, has_more = selectors.journal_entries(limit=limit, batch=only_batch)
    for entry in entries:
        _style_entry(entry)
    return render(request, "web/journal.html", {
        "entries": entries, "has_more": has_more and limit < 400, "next_limit": limit + 40,
        "only_batch": only_batch,
    })


@login_required
def tool_detail(request, pk):
    tool = get_object_or_404(Tool.objects.select_related("category", "current_site"), pk=pk)
    return render(request, "web/position.html", {
        "kind": "tool", "item": tool, "rows": _style_rows(selectors.tool_history_rows(tool)),
        "photos": tool.photos.order_by("-is_main", "created_at"), "photo_form": PhotosForm(),
    })


@login_required
@operator_required
@require_POST
def tool_photos(request, pk):
    """Загрузка фото на странице позиции (несколько файлов сразу)."""
    tool = get_object_or_404(Tool, pk=pk)
    form = PhotosForm(request.POST, request.FILES)
    if form.is_valid():
        services.add_tool_photos(tool=tool, images=form.cleaned_data["photos"])
        messages.success(request, f"Фото добавлено: {len(form.cleaned_data['photos'])}.")
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect("web:tool_detail", pk=tool.pk)


@login_required
@operator_required
@require_POST
def photo_main(request, pk):
    photo = get_object_or_404(ToolPhoto, pk=pk)
    services.set_main_photo(photo=photo)
    messages.success(request, "Главное фото обновлено.")
    return redirect("web:tool_detail", pk=photo.tool_id)


@login_required
@operator_required
@require_POST
def photo_delete(request, pk):
    photo = get_object_or_404(ToolPhoto, pk=pk)
    tool_id = photo.tool_id
    services.delete_photo(photo=photo)
    messages.success(request, "Фото удалено.")
    return redirect("web:tool_detail", pk=tool_id)


@login_required
def hand_tool_detail(request, pk):
    hand_tool = get_object_or_404(HandTool.objects.select_related("category"), pk=pk)
    return render(request, "web/position.html", {
        "kind": "hand", "item": hand_tool, "rows": _style_rows(selectors.hand_tool_history_rows(hand_tool)),
    })


def _back(request, default="web:journal"):
    """Куда вернуться после отмены: на страницу, откуда нажали (только свой сайт), иначе в журнал."""
    url = request.POST.get("next", "")
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}):
        return redirect(url)
    return redirect(default)


@login_required
@operator_required
@require_POST
def cancel_batch(request, batch):
    try:
        services.cancel_batch(user=request.user, batch=batch)
    except services.ServiceError as error:
        messages.error(request, " ".join(str(error).splitlines()))   # причины одной строкой в плашке
    else:
        messages.success(request, "Набор отменён: состояние позиций пересчитано по журналу.")
    return _back(request)


@login_required
@operator_required
@require_POST
def cancel_movement(request, kind, pk):
    model = {"tool": ToolMovement, "hand": HandToolMovement}.get(kind)
    if model is None:
        raise Http404
    movement = get_object_or_404(model, pk=pk)
    try:
        services.cancel_movement(user=request.user, movement=movement)
    except services.ServiceError as error:
        messages.error(request, " ".join(str(error).splitlines()))
    else:
        messages.success(request, "Операция отменена: состояние позиции пересчитано по журналу.")
    return _back(request)


# ---------------------------------------------------------------------------
# Тестовый переключатель ролей (только при DEMO_ROLE_SWITCH=1)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def switch_role(request):
    """
    Кнопка в шапке: запомнить роль в сессии и вернуться на ту же страницу.
    Пользователя в базе не меняет. Без флага адреса как будто нет (404).
    """
    if not settings.DEMO_ROLE_SWITCH:
        raise Http404
    role = request.POST.get("role")
    roles.set_switched_role(request, role)
    if role in roles.GROUPS:
        messages.success(request, f"Роль для проверки: «{roles.LABELS[role]}».")
    # Со страницы операции наблюдателя всё равно вернёт на главную (operator_required)
    return _back(request, default="web:home")


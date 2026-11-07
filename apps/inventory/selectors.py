"""
Выборки (только чтение, ничего не меняют). Считаются по журналу, а не по кэшу в моделях.
"""
from django.db.models import Case, Count, F, IntegerField, Max, Prefetch, Sum, Value, When
from django.utils import timezone

from apps.sites.models import Site

from .models import BaseMovement, HandTool, HandToolMovement, Tool, ToolMovement, ToolPhoto

MovementType = BaseMovement.Type


def hand_tool_on_site(hand_tool, site):
    """
    Сколько штук ручного инструмента числится на объекте (DECISIONS, разделы 8 и 14).

    Выдано на объект минус принято с объекта минус не найдено минус списано на объекте.
    Отменённые записи не учитываются. Это общий расчёт по объекту, а не по конкретной
    выдаче: на объект могли выдавать несколько раз, считаем всё вместе.
    """
    rows = HandToolMovement.objects.filter(hand_tool=hand_tool, site=site, is_cancelled=False)

    def qty(movement_type):
        return rows.filter(type=movement_type).aggregate(s=Sum("quantity"))["s"] or 0

    return (
        qty(MovementType.ISSUED)
        - qty(MovementType.RETURNED)
        - qty(MovementType.MISSING)
        - qty(MovementType.WRITTEN_OFF)
    )


# ---------------------------------------------------------------------------
# Доступно к выдаче (для формы выдачи, SPEC раздел 6)
# ---------------------------------------------------------------------------

def available_tools():
    """Штучные позиции, которые можно выдать: статус «на складе»."""
    return Tool.objects.filter(status=Tool.Status.AVAILABLE).select_related("category").order_by("name")


def available_hand_tools():
    """Ручной инструмент, которого есть в наличии (total больше issued)."""
    return HandTool.objects.filter(total__gt=F("issued")).select_related("category").order_by("name")


# ---------------------------------------------------------------------------
# Числится на объекте (для формы приёма и отчётов)
# ---------------------------------------------------------------------------

def tools_on_site(site):
    """
    Штучные позиции, которые числятся на объекте: выданы и не приняты.
    «Не найденные» и списанные сюда не входят (DECISIONS, раздел 14).
    """
    return (
        Tool.objects.filter(status=Tool.Status.ISSUED, current_site=site)
        .select_related("category").order_by("name")
    )


def tools_in_servicing():
    """Штучные позиции, которые сейчас в ремонте (для приёма из ремонта)."""
    return Tool.objects.filter(status=Tool.Status.SERVICING).select_related("category").order_by("name")


def tools_for_write_off():
    """
    Штучные позиции, которые можно списать со склада: «на складе», «в ремонте» и «не найден»
    (потерянное закрывается списанием, DECISIONS, раздел 14).
    """
    statuses = (Tool.Status.AVAILABLE, Tool.Status.SERVICING, Tool.Status.MISSING)
    return Tool.objects.filter(status__in=statuses).select_related("category").order_by("name")


# Как каждая операция меняет количество ручного инструмента на объекте (DECISIONS, разделы 8 и 14).
_ON_SITE_SIGN = {
    MovementType.ISSUED: 1,
    MovementType.RETURNED: -1,
    MovementType.MISSING: -1,
    MovementType.WRITTEN_OFF: -1,
}


def _on_site_delta():
    """Выражение для Sum: +количество за выдачу, −количество за приём, потерю и списание на объекте."""
    return Case(
        *[When(type=kind, then=F("quantity") * factor) for kind, factor in _ON_SITE_SIGN.items()],
        default=Value(0),
        output_field=IntegerField(),
    )


def hand_tools_on_site(site):
    """
    Ручной инструмент, который числится на объекте: список пар (HandTool, количество).

    Считается по журналу так же, как hand_tool_on_site, но сразу по всем позициям
    объекта одним запросом. Позиции с нулём и меньше не попадают в список.
    """
    rows = (
        HandToolMovement.objects.filter(site=site, is_cancelled=False)
        .values("hand_tool")
        .annotate(on_site=Sum(_on_site_delta()))
        .filter(on_site__gt=0)
    )
    quantities = {row["hand_tool"]: row["on_site"] for row in rows}
    hand_tools = HandTool.objects.filter(pk__in=quantities).select_related("category").order_by("name")
    return [(hand_tool, quantities[hand_tool.pk]) for hand_tool in hand_tools]


def sites_with_items(tools_only=False):
    """
    Объекты, на которых сейчас что-то числится: выданная штучная позиция или ручной инструмент.

    Для выпадающих списков приёма, «не найден», списания и ремонта: пустые объекты там не нужны.
    tools_only=True: только объекты с выданными штучными (в ремонт ручной не отправляется).
    """
    ids = set(
        Tool.objects.filter(status=Tool.Status.ISSUED, current_site__isnull=False)
        .values_list("current_site", flat=True)
    )
    if not tools_only:
        # Сумма по объекту больше нуля, только если хоть одна позиция там числится:
        # по отдельной позиции количество на объекте не бывает отрицательным.
        rows = (
            HandToolMovement.objects.filter(is_cancelled=False, site__isnull=False)
            .values("site")
            .annotate(on_site=Sum(_on_site_delta()))
            .filter(on_site__gt=0)
        )
        ids.update(row["site"] for row in rows)
    return Site.objects.filter(pk__in=ids).order_by("name")


# ---------------------------------------------------------------------------
# История и отчёты по журналу
# ---------------------------------------------------------------------------

def tool_history(tool, include_cancelled=True):
    """
    История штучной позиции: все операции, новые сверху.
    Отменённые по умолчанию показываются (у них is_cancelled=True): так видно, что было.
    """
    rows = tool.movements.select_related("site", "created_by").order_by("-created_at", "-pk")
    return rows if include_cancelled else rows.filter(is_cancelled=False)


def hand_tool_history(hand_tool, include_cancelled=True):
    """История ручного инструмента: все операции, новые сверху."""
    rows = hand_tool.movements.select_related("site", "created_by").order_by("-created_at", "-pk")
    return rows if include_cancelled else rows.filter(is_cancelled=False)


def issued_in_period(date_from, date_to, site=None):
    """
    Выдачи за период (обе даты включительно, по местному времени), без отменённых.
    Если указан site, то только на этот объект («выдано на конкретный объект за период»).

    Возвращает пару запросов (строки ToolMovement, строки HandToolMovement): у видов учёта
    разные журналы (DECISIONS, раздел 3), склеивать их для общего отчёта будет вызывающий код.
    """
    def pick(model):
        rows = model.objects.filter(
            type=MovementType.ISSUED, is_cancelled=False,
            created_at__date__gte=date_from, created_at__date__lte=date_to,
        ).select_related("site", "created_by").order_by("-created_at", "-pk")
        return rows if site is None else rows.filter(site=site)

    return pick(ToolMovement), pick(HandToolMovement)


# ---------------------------------------------------------------------------
# Сводка для главной страницы
# ---------------------------------------------------------------------------

def stock_summary():
    """
    Сводка по складу для главной страницы. Считается из кэша статусов и счётчиков в моделях.

    warehouse (+ _tools, _hand) — на складе: штучные «на складе» и ручной инструмент
                                  в наличии (total − issued);
    issued    (+ _tools, _hand) — выдано на объекты;
    servicing — штучные в ремонте;
    missing   — штучные «не найден» (потерянный ручной инструмент уже вычтен из total);
    ready_percent — доля инструмента «в строю» (на складе или на объектах) среди всего,
                    что числится на балансе: не в ремонте и не потеряно, в процентах.
                    Списанное не считается вообще. Если считать нечего, то 100.
    """
    by_status = {
        row["status"]: row["n"]
        for row in Tool.objects.order_by().values("status").annotate(n=Count("pk"))
    }
    hand = HandTool.objects.aggregate(total=Sum("total"), issued=Sum("issued"))
    hand_total = hand["total"] or 0

    warehouse_tools = by_status.get(Tool.Status.AVAILABLE, 0)
    warehouse_hand = hand_total - (hand["issued"] or 0)
    issued_tools = by_status.get(Tool.Status.ISSUED, 0)
    issued_hand = hand["issued"] or 0
    servicing = by_status.get(Tool.Status.SERVICING, 0)
    missing = by_status.get(Tool.Status.MISSING, 0)

    warehouse = warehouse_tools + warehouse_hand
    issued = issued_tools + issued_hand
    on_balance = warehouse + issued + servicing + missing
    return {
        "warehouse": warehouse,
        "warehouse_tools": warehouse_tools,
        "warehouse_hand": warehouse_hand,
        "issued": issued,
        "issued_tools": issued_tools,
        "issued_hand": issued_hand,
        "servicing": servicing,
        "missing": missing,
        "ready_percent": round(100 * (warehouse + issued) / on_balance) if on_balance else 100,
    }


# ---------------------------------------------------------------------------
# Журнал для страницы: строки со знанием «можно ли отменить»
# ---------------------------------------------------------------------------

def _last_active_ids(model, field, ids):
    """Для каждой позиции из ids: pk её последней действующей (не отменённой) записи журнала."""
    rows = model.objects.filter(is_cancelled=False, **{f"{field}__in": ids}).order_by()
    return dict(rows.values_list(field).annotate(last=Max("pk")))


def _movement_dicts(tool_rows, hand_rows):
    """
    Строки обоих журналов -> словари для страницы, новые сверху.

    can_cancel повторяет правила services._cancel: нельзя отменить уже отменённую,
    постановку на баланс и не последнюю действующую операцию по позиции. Если нельзя,
    в hint причина (для подсказки пользователю); сам запрет всё равно проверяет сервис.
    """
    last_tool = _last_active_ids(ToolMovement, "tool_id", {r.tool_id for r in tool_rows})
    last_hand = _last_active_ids(HandToolMovement, "hand_tool_id", {r.hand_tool_id for r in hand_rows})

    def make(row, kind, item, item_id, quantity, last):
        if row.is_cancelled:
            can, hint = False, ""
        elif row.type == MovementType.ADDED:
            can, hint = False, "Постановку на баланс отменять нельзя"
        elif last.get(item_id) != row.pk:
            can, hint = False, "После этой операции были другие: сначала отмените их"
        else:
            can, hint = True, ""
        return {
            "id": row.pk, "kind": kind, "item": item, "item_id": item_id, "quantity": quantity,
            "batch": str(row.batch) if row.batch else "",
            "type": row.type, "type_display": row.get_type_display(),
            "site": row.site.name if row.site else None,
            "taken_by": row.taken_by, "note": row.note,
            "created_at": row.created_at, "created_by": row.created_by.get_username(),
            "is_cancelled": row.is_cancelled,
            "cancelled_by": row.cancelled_by.get_username() if row.cancelled_by else "",
            "can_cancel": can, "hint": hint,
        }

    items = [make(r, "tool", r.tool.name, r.tool_id, None, last_tool) for r in tool_rows]
    items += [make(r, "hand", r.hand_tool.name, r.hand_tool_id, r.quantity, last_hand) for r in hand_rows]
    items.sort(key=lambda d: (d["created_at"], d["id"]), reverse=True)
    return items


def journal_entries(limit=40, batch=None, row_limit=None, site=None, taken_by=None):
    """
    Журнал операций для страницы: (записи, есть_ещё).

    Запись это одна операция пользователя: набор (строки с общим batch из обоих журналов)
    или одиночная строка. У записи can_cancel_batch: набор можно отменить целиком, только если
    каждую его действующую строку можно отменить (правило «всё или ничего»).
    Если набор попал на границу страницы, его строки догружаются целиком.
    batch: показать только один набор (страница по ссылке с главной).
    row_limit: сколько строк брать из каждого журнала (по умолчанию limit); главной нужно
    больше строк, чем записей, потому что набор занимает много строк.
    site, taken_by: фильтр журнала — только операции по этому объекту (id) и/или
    с этим «Кто взял / привёз» (точное совпадение текста). У строк одного набора объект
    и taken_by общие, поэтому набор под фильтр попадает целиком.
    """
    tool_qs = ToolMovement.objects.select_related("tool", "site", "created_by", "cancelled_by")
    hand_qs = HandToolMovement.objects.select_related("hand_tool", "site", "created_by", "cancelled_by")
    if site is not None:
        tool_qs, hand_qs = tool_qs.filter(site_id=site), hand_qs.filter(site_id=site)
    if taken_by:
        tool_qs, hand_qs = tool_qs.filter(taken_by=taken_by), hand_qs.filter(taken_by=taken_by)
    if batch is not None:
        tool_rows = list(tool_qs.filter(batch=batch).order_by("-created_at", "-pk"))
        hand_rows = list(hand_qs.filter(batch=batch).order_by("-created_at", "-pk"))
        has_more = False
    else:
        row_limit = row_limit or limit
        tool_rows = list(tool_qs.order_by("-created_at", "-pk")[:row_limit])
        hand_rows = list(hand_qs.order_by("-created_at", "-pk")[:row_limit])
        has_more = len(tool_rows) == row_limit or len(hand_rows) == row_limit

        batches = {r.batch for r in tool_rows + hand_rows if r.batch}
        if batches:
            have_t, have_h = {r.pk for r in tool_rows}, {r.pk for r in hand_rows}
            tool_rows += [r for r in tool_qs.filter(batch__in=batches) if r.pk not in have_t]
            hand_rows += [r for r in hand_qs.filter(batch__in=batches) if r.pk not in have_h]

    entries, by_batch = [], {}
    for row in _movement_dicts(tool_rows, hand_rows):
        if row["batch"] and row["batch"] in by_batch:
            by_batch[row["batch"]]["rows"].append(row)
            continue
        entry = {"batch": row["batch"], "rows": [row], "created_at": row["created_at"],
                 "site": row["site"], "taken_by": row["taken_by"], "created_by": row["created_by"]}
        entries.append(entry)
        if row["batch"]:
            by_batch[row["batch"]] = entry

    # Постановки на баланс за один день — одной записью «Поставлено на баланс · <дата>»:
    # их много и по одной отменить нельзя, поэтому в журнале они только засоряют ленту.
    # Группируем одиночные added-записи по местной дате; порядок (новые сверху) сохраняется,
    # группа встаёт на место самой свежей постановки этого дня, у неё своё время у каждой строки.
    grouped, by_day = [], {}
    for entry in entries:
        # вся запись — постановка на баланс? (у неё свой batch на каждую позицию, группируем не по нему, а по дню)
        if not all(r["type"] == MovementType.ADDED for r in entry["rows"]):
            grouped.append(entry)
            continue
        day = timezone.localtime(entry["created_at"]).date()
        if day in by_day:
            by_day[day]["rows"].extend(entry["rows"])
            continue
        entry["day_group"] = True
        entry["day"] = day
        by_day[day] = entry
        grouped.append(entry)
    entries = grouped

    for entry in entries:
        active = [r for r in entry["rows"] if not r["is_cancelled"]]
        entry["is_set"] = len(entry["rows"]) > 1
        entry["count"] = len(entry["rows"])
        entry["type_display"] = entry["rows"][0]["type_display"]
        entry["is_cancelled"] = not active
        entry["can_cancel_batch"] = bool(active) and all(r["can_cancel"] for r in active)
        entry["cancel_batch_hint"] = "" if entry["can_cancel_batch"] or not active else next(
            (f"«{r['item']}»: {r['hint'].lower()}" for r in active if not r["can_cancel"]), "")
        if entry.get("day_group"):
            entry["cancel_batch_hint"] = ""   # постановку на баланс не отменяют — кнопку не показываем
    return entries[:limit], has_more


def journal_filters():
    """
    Варианты для фильтра журнала: объекты, по которым были операции, и все «Кто взял / привёз».
    Возвращает {"sites": [Site, ...], "people": ["Имя Фамилия", ...]} (по алфавиту).
    """
    site_ids = set(ToolMovement.objects.filter(site__isnull=False).values_list("site_id", flat=True))
    site_ids |= set(HandToolMovement.objects.filter(site__isnull=False).values_list("site_id", flat=True))
    people = set(ToolMovement.objects.exclude(taken_by="").values_list("taken_by", flat=True).distinct())
    people |= set(HandToolMovement.objects.exclude(taken_by="").values_list("taken_by", flat=True).distinct())
    return {"sites": list(Site.objects.filter(pk__in=site_ids).order_by("name")), "people": sorted(people)}


def recent_entries(limit=6):
    """Последние операции для главной: те же записи, что в журнале (набор = одна запись)."""
    entries, _ = journal_entries(limit=limit, row_limit=limit * 8)
    return entries


def tool_history_rows(tool):
    """История штучной позиции для страницы (со словами «можно ли отменить»)."""
    rows = list(tool_history(tool).select_related("created_by", "cancelled_by"))
    return _movement_dicts(rows, [])


def hand_tool_history_rows(hand_tool):
    rows = list(hand_tool_history(hand_tool).select_related("created_by", "cancelled_by"))
    return _movement_dicts([], rows)


def tools_needing_attention(limit=None):
    """
    Штучные позиции, которые требуют внимания: «не найден» (сначала) и «в ремонте».
    Для блока на главной странице; limit по умолчанию без ограничения.
    """
    rows = (
        Tool.objects.filter(status__in=[Tool.Status.MISSING, Tool.Status.SERVICING])
        .select_related("category", "current_site")
        .order_by(Case(When(status=Tool.Status.MISSING, then=0), default=1, output_field=IntegerField()), "name")
    )
    return rows[:limit] if limit else rows


def search_inventory(query="", status=""):
    """
    Инвентарь для страницы: пара (штучные, ручные), по названию без учёта регистра.

    status относится только к штучным позициям. У ручного инструмента статусов нет
    (DECISIONS, раздел 14), поэтому при выбранном статусе ручной инструмент не показывается.
    """
    # Главное фото берём одним дополнительным запросом на всю страницу (а не по запросу на позицию).
    # В шаблоне: tool.main_photos (список из 0 или 1 фото).
    main_photo = Prefetch("photos", queryset=ToolPhoto.objects.filter(is_main=True), to_attr="main_photos")
    tools = Tool.objects.select_related("category__parent", "current_site").prefetch_related(main_photo).order_by("name")
    hand_tools = HandTool.objects.select_related("category__parent").order_by("name")
    if query:
        tools = tools.filter(name__icontains=query)
        hand_tools = hand_tools.filter(name__icontains=query)
    if status:
        tools = tools.filter(status=status)
        hand_tools = hand_tools.none()
    return tools, hand_tools


def group_by_category(tools, hand_tools):
    """
    Разложить штучные и ручные позиции по категориям для страницы инвентаря.

    Результат: список словарей {name, tools, hand_tools, count}, по алфавиту названий категорий;
    внутри группы позиции в том же порядке, что пришли (по названию). Категория подкатегории
    подписывается путём «Родитель / Подкатегория». Категории без позиций не попадают.
    """
    groups = {}

    def group_for(category):
        if category.pk not in groups:
            name = f"{category.parent.name} / {category.name}" if category.parent else category.name
            groups[category.pk] = {"name": name, "tools": [], "hand_tools": []}
        return groups[category.pk]

    for tool in tools:
        group_for(tool.category)["tools"].append(tool)
    for hand_tool in hand_tools:
        group_for(hand_tool.category)["hand_tools"].append(hand_tool)
    for group in groups.values():
        group["count"] = len(group["tools"]) + len(group["hand_tools"])
    return sorted(groups.values(), key=lambda g: g["name"].lower())

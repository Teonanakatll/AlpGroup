"""
Выборки (только чтение, ничего не меняют). Считаются по журналу, а не по кэшу в моделях.
"""
from django.db.models import Case, Count, F, IntegerField, Sum, Value, When

from .models import BaseMovement, HandTool, HandToolMovement, Tool, ToolMovement

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


def hand_tools_on_site(site):
    """
    Ручной инструмент, который числится на объекте: список пар (HandTool, количество).

    Считается по журналу так же, как hand_tool_on_site, но сразу по всем позициям
    объекта одним запросом. Позиции с нулём и меньше не попадают в список.
    """
    sign = {
        MovementType.ISSUED: 1,
        MovementType.RETURNED: -1,
        MovementType.MISSING: -1,
        MovementType.WRITTEN_OFF: -1,
    }
    delta = Case(
        *[When(type=kind, then=F("quantity") * factor) for kind, factor in sign.items()],
        default=Value(0),
        output_field=IntegerField(),
    )
    rows = (
        HandToolMovement.objects.filter(site=site, is_cancelled=False)
        .values("hand_tool")
        .annotate(on_site=Sum(delta))
        .filter(on_site__gt=0)
    )
    quantities = {row["hand_tool"]: row["on_site"] for row in rows}
    hand_tools = HandTool.objects.filter(pk__in=quantities).select_related("category").order_by("name")
    return [(hand_tool, quantities[hand_tool.pk]) for hand_tool in hand_tools]


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


def recent_movements(limit=6):
    """
    Последние операции по обоим журналам, новые сверху.

    Отменённые тоже возвращаются, с is_cancelled=True: страница показывает их приглушёнными,
    чтобы было видно, что было. Результат — список словарей (у журналов разные поля:
    tool или hand_tool, а странице нужно одно и то же): type, type_display, name,
    quantity (None у штучных), site (название или None), taken_by, created_at, is_cancelled.
    """
    tool_rows = ToolMovement.objects.select_related("tool", "site").order_by("-created_at", "-pk")[:limit]
    hand_rows = HandToolMovement.objects.select_related("hand_tool", "site").order_by("-created_at", "-pk")[:limit]

    def row_dict(row, name, quantity):
        return {
            "type": row.type, "type_display": row.get_type_display(), "name": name,
            "quantity": quantity, "site": row.site.name if row.site else None,
            "taken_by": row.taken_by, "created_at": row.created_at, "is_cancelled": row.is_cancelled,
        }

    items = [row_dict(r, r.tool.name, None) for r in tool_rows]
    items += [row_dict(r, r.hand_tool.name, r.quantity) for r in hand_rows]
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items[:limit]


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
    tools = Tool.objects.select_related("category", "current_site").order_by("name")
    hand_tools = HandTool.objects.select_related("category").order_by("name")
    if query:
        tools = tools.filter(name__icontains=query)
        hand_tools = hand_tools.filter(name__icontains=query)
    if status:
        tools = tools.filter(status=status)
        hand_tools = hand_tools.none()
    return tools, hand_tools

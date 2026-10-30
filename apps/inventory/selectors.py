"""
Выборки (только чтение, ничего не меняют). Считаются по журналу, а не по кэшу в моделях.
"""
from django.db.models import Case, F, IntegerField, Sum, Value, When

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

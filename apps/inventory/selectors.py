"""
Выборки (только чтение, ничего не меняют). Считаются по журналу, а не по кэшу в моделях.
"""
from django.db.models import Sum

from .models import BaseMovement, HandToolMovement

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

"""
Все изменения состояния инструмента делаются только здесь (DECISIONS, раздел 6).

Схема каждой операции одна и та же:
1. открыть транзакцию (transaction.atomic);
2. заблокировать строку позиции (select_for_update), чтобы два человека
   не изменили одну и ту же позицию одновременно;
3. проверить, что операция допустима;
4. дописать строку в журнал;
5. пересчитать состояние позиции из журнала (recalc_*).

Журнал источник истины, статус и счётчики в моделях только кэш.
"""
import uuid

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    BaseMovement, HandTool, HandToolMovement, Tool, ToolMovement,
)

MovementType = BaseMovement.Type


class ServiceError(Exception):
    """Операция запрещена правилами учёта. Текст ошибки можно показать пользователю."""


def new_batch():
    """Новая метка набора. Одно действие пользователя равно одному batch (DECISIONS, раздел 14)."""
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Пересчёт состояния из журнала
# ---------------------------------------------------------------------------

# Какой статус получает штучная позиция после последней действующей операции.
_STATUS_AFTER = {
    MovementType.ADDED: Tool.Status.AVAILABLE,
    MovementType.ISSUED: Tool.Status.ISSUED,
    MovementType.RETURNED: Tool.Status.AVAILABLE,
    MovementType.WRITTEN_OFF: Tool.Status.WRITTEN_OFF,
    MovementType.SERVICING: Tool.Status.SERVICING,
    MovementType.MISSING: Tool.Status.MISSING,
}


def recalc_tool(tool):
    """
    Пересчитать статус и текущий объект штучной позиции по журналу.

    Вызывать только внутри transaction.atomic и после select_for_update.
    Берётся последняя неотменённая запись: она и определяет состояние.
    """
    last = (
        tool.movements.filter(is_cancelled=False)
        .order_by("-created_at", "-id")
        .first()
    )
    if last is None:
        # Журнал пуст или все записи отменены: выводить состояние не из чего.
        return tool

    tool.status = _STATUS_AFTER[last.type]
    # Объект запоминаем только пока позиция выдана. Для «не найден», «списан» и «ремонт»
    # «что числится на объекте» считают selectors.py по журналу.
    tool.current_site = last.site if last.type == MovementType.ISSUED else None
    tool.save(update_fields=["status", "current_site"])
    return tool


def recalc_hand_tool(hand_tool):
    """
    Пересчитать total и issued ручного инструмента по журналу.

    Пока учитываются added, issued и returned. «Не найден» и «списание» для
    ручного инструмента добавим в пункте плана про missing/written_off.
    Вызывать только внутри transaction.atomic и после select_for_update.
    """
    rows = hand_tool.movements.filter(is_cancelled=False)

    def qty(movement_type):
        return rows.filter(type=movement_type).aggregate(s=Sum("quantity"))["s"] or 0

    hand_tool.total = qty(MovementType.ADDED)
    hand_tool.issued = qty(MovementType.ISSUED) - qty(MovementType.RETURNED)
    # Если журнал даст issued > total или отрицательное число, БД отклонит сохранение
    # (CheckConstraint и PositiveIntegerField): ошибка в данных не пройдёт молча.
    hand_tool.save(update_fields=["total", "issued"])
    return hand_tool


# ---------------------------------------------------------------------------
# Постановка на баланс (added)
# ---------------------------------------------------------------------------

@transaction.atomic
def register_tool(*, user, name, category, note="", on_balance_date=None, batch=None):
    """
    Завести штучную позицию и поставить её на баланс: Tool +1.

    Создание позиции и запись `added` в журнал идут в одной транзакции,
    поэтому позиции без события постановки на баланс не бывает.
    """
    tool = Tool.objects.create(
        name=name,
        category=category,
        note=note,
        on_balance_date=on_balance_date or timezone.localdate(),
    )
    ToolMovement.objects.create(
        tool=tool,
        type=MovementType.ADDED,
        created_by=user,
        batch=batch or new_batch(),
        note=note[:300],
    )
    recalc_tool(tool)
    return tool


@transaction.atomic
def add_hand_tool_stock(*, user, hand_tool, quantity, note="", batch=None):
    """
    Поставить на баланс `quantity` единиц ручного инструмента: HandTool +N к total.

    Сама позиция (название, категория) создаётся обычным способом через админку
    с total = 0; количество добавляется только этой функцией.
    """
    if quantity < 1:
        raise ServiceError("Количество должно быть не меньше 1.")

    # Блокируем строку: два одновременных прихода не потеряют друг друга.
    hand_tool = HandTool.objects.select_for_update().get(pk=hand_tool.pk)
    HandToolMovement.objects.create(
        hand_tool=hand_tool,
        type=MovementType.ADDED,
        quantity=quantity,
        created_by=user,
        batch=batch or new_batch(),
        note=note,
    )
    recalc_hand_tool(hand_tool)
    return hand_tool

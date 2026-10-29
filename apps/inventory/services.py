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


# ---------------------------------------------------------------------------
# Выдача набора на объект (issued)
# ---------------------------------------------------------------------------

def _find_duplicates(ids):
    """Id, которые встречаются в списке больше одного раза."""
    return {i for i in ids if ids.count(i) > 1}


@transaction.atomic
def issue_to_site(*, user, site, tools=(), hand_tools=(), taken_by="", note=""):
    """
    Выдать набор позиций на объект одной операцией.

    tools      — штучные позиции: [Tool, Tool, ...]
    hand_tools — ручной инструмент с количеством: [(HandTool, 5), (HandTool, 2), ...]

    Правила (DECISIONS, разделы 13 и 14):
    - выдать можно только штучную позицию со статусом «на складе»;
    - ручного инструмента нельзя выдать больше, чем есть в наличии;
    - «всё или ничего»: если хоть одна позиция не проходит проверку, не выдаётся
      ничего, и пользователь сразу видит все проблемы, а не по одной;
    - у всех строк журнала этой операции один общий новый batch.

    Возвращает batch (UUID): по нему потом можно найти набор или отменить его целиком.
    """
    tools = list(tools)
    hand_tools = list(hand_tools)

    if site is None:
        raise ServiceError("Не указан объект.")
    if not tools and not hand_tools:
        raise ServiceError("Не выбрано ни одной позиции.")

    tool_ids = [t.pk for t in tools]
    hand_ids = [ht.pk for ht, _ in hand_tools]
    quantities = {ht.pk: qty for ht, qty in hand_tools}

    errors = []
    if _find_duplicates(tool_ids) or _find_duplicates(hand_ids):
        errors.append("Одна и та же позиция указана в наборе больше одного раза.")

    # Блокируем строки позиций. Всегда в порядке id и всегда сначала штучные, потом ручные:
    # если две выдачи пересекаются, они берут блокировки в одном порядке и не повиснут
    # друг на друге (взаимная блокировка, deadlock).
    # Состояние читаем из заблокированных строк, а не из переданных объектов: пока
    # форма была открыта, статус мог измениться.
    locked_tools = {
        t.pk: t for t in Tool.objects.select_for_update().filter(pk__in=tool_ids).order_by("pk")
    }
    locked_hand = {
        h.pk: h for h in HandTool.objects.select_for_update().filter(pk__in=hand_ids).order_by("pk")
    }

    for tool_id in tool_ids:
        tool = locked_tools.get(tool_id)
        if tool is None:
            errors.append(f"Инструмент с id {tool_id} не найден.")
        elif tool.status != Tool.Status.AVAILABLE:
            errors.append(f"«{tool.name}»: нельзя выдать, статус «{tool.get_status_display()}».")

    for hand_id in hand_ids:
        hand_tool = locked_hand.get(hand_id)
        quantity = quantities[hand_id]
        if hand_tool is None:
            errors.append(f"Ручной инструмент с id {hand_id} не найден.")
        elif quantity < 1:
            errors.append(f"«{hand_tool.name}»: количество должно быть не меньше 1.")
        elif quantity > hand_tool.available:
            errors.append(
                f"«{hand_tool.name}»: запрошено {quantity}, в наличии {hand_tool.available}."
            )

    if errors:
        raise ServiceError("\n".join(errors))

    # Все проверки пройдены: пишем журнал и пересчитываем состояние.
    batch = new_batch()
    for tool in locked_tools.values():
        ToolMovement.objects.create(
            tool=tool, type=MovementType.ISSUED, site=site, taken_by=taken_by,
            created_by=user, batch=batch, note=note,
        )
        recalc_tool(tool)
    for hand_tool in locked_hand.values():
        HandToolMovement.objects.create(
            hand_tool=hand_tool, type=MovementType.ISSUED, site=site, taken_by=taken_by,
            quantity=quantities[hand_tool.pk], created_by=user, batch=batch, note=note,
        )
        recalc_hand_tool(hand_tool)
    return batch

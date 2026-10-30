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
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from . import selectors
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
    Пересчитать total и issued ручного инструмента по журналу (DECISIONS, раздел 14).

    total  = приход − не найдено − списано: это то, чем реально можно снабдить людей;
    issued = выдано − принято − не найдено − списано на объекте.
    «Не найден» и «списан» уменьшают и total, и issued, если позиция числилась на объекте
    (запись с объектом). Списание со склада (запись без объекта) уменьшает только total.
    Сами записи остаются в журнале, отчёты по потерям и списаниям строятся по нему.

    Вызывать только внутри transaction.atomic и после select_for_update.
    """
    rows = hand_tool.movements.filter(is_cancelled=False)

    def qty(movement_type, only_with_site=False):
        selected = rows.filter(type=movement_type)
        if only_with_site:
            selected = selected.filter(site__isnull=False)
        return selected.aggregate(s=Sum("quantity"))["s"] or 0

    missing = qty(MovementType.MISSING)
    written_off = qty(MovementType.WRITTEN_OFF)

    hand_tool.total = qty(MovementType.ADDED) - missing - written_off
    hand_tool.issued = (
        qty(MovementType.ISSUED)
        - qty(MovementType.RETURNED)
        - missing                                   # потеряно всегда на объекте
        - qty(MovementType.WRITTEN_OFF, only_with_site=True)
    )
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
# Общие помощники для операций над набором позиций (выдача, приём)
# ---------------------------------------------------------------------------

@dataclass
class _LockedSet:
    """Набор позиций операции: заблокированные строки из базы и найденные ошибки."""
    tool_ids: list
    hand_ids: list
    tools: dict          # pk -> Tool (заблокированная строка)
    hand_tools: dict     # pk -> HandTool (заблокированная строка)
    quantities: dict     # pk ручного инструмента -> запрошенное количество
    errors: list         # тексты ошибок для пользователя


def _find_duplicates(ids):
    """Id, которые встречаются в списке больше одного раза."""
    return {i for i in ids if ids.count(i) > 1}


def _lock_positions(tools, hand_tools):
    """
    Заблокировать строки позиций операции и вернуть их свежее состояние.

    Блокируем всегда в порядке id и всегда сначала штучные, потом ручные:
    если две операции пересекаются, они берут блокировки в одном порядке и не повиснут
    друг на друге (взаимная блокировка, deadlock).
    Состояние читаем из заблокированных строк, а не из переданных объектов: пока
    форма была открыта, статус мог измениться.
    Вызывать только внутри transaction.atomic.
    """
    tool_ids = [t.pk for t in tools]
    hand_ids = [ht.pk for ht, _ in hand_tools]
    errors = []
    if _find_duplicates(tool_ids) or _find_duplicates(hand_ids):
        errors.append("Одна и та же позиция указана в наборе больше одного раза.")

    return _LockedSet(
        tool_ids=tool_ids,
        hand_ids=hand_ids,
        tools={
            t.pk: t
            for t in Tool.objects.select_for_update().filter(pk__in=tool_ids).order_by("pk")
        },
        hand_tools={
            h.pk: h
            for h in HandTool.objects.select_for_update().filter(pk__in=hand_ids).order_by("pk")
        },
        quantities={ht.pk: qty for ht, qty in hand_tools},
        errors=errors,
    )


def _write_set(locked, *, movement_type, site, user, taken_by, note):
    """
    Записать в журнал одну операцию над набором и пересчитать состояние позиций.

    Все строки получают один новый batch. Проверки к этому моменту уже пройдены.
    Возвращает batch.
    """
    batch = new_batch()
    for tool in locked.tools.values():
        ToolMovement.objects.create(
            tool=tool, type=movement_type, site=site, taken_by=taken_by,
            created_by=user, batch=batch, note=note,
        )
        recalc_tool(tool)
    for hand_tool in locked.hand_tools.values():
        HandToolMovement.objects.create(
            hand_tool=hand_tool, type=movement_type, site=site, taken_by=taken_by,
            quantity=locked.quantities[hand_tool.pk], created_by=user, batch=batch, note=note,
        )
        recalc_hand_tool(hand_tool)
    return batch


def _check_not_empty(tools, hand_tools):
    if not tools and not hand_tools:
        raise ServiceError("Не выбрано ни одной позиции.")


def _check_tools_at(locked, site, action, warehouse_statuses=()):
    """
    Проверить штучные позиции набора перед операцией; ошибки дописываются в locked.errors.

    site указан  — позиция должна быть выдана и числиться именно на этом объекте;
    site не указан — позиция должна быть на складе, статус из warehouse_statuses.
    action — глагол для текста ошибки: «принять», «списать» и т.п.
    """
    for tool_id in locked.tool_ids:
        tool = locked.tools.get(tool_id)
        if tool is None:
            locked.errors.append(f"Инструмент с id {tool_id} не найден.")
        elif site is None:
            if tool.status not in warehouse_statuses:
                locked.errors.append(
                    f"«{tool.name}»: нельзя {action}, статус «{tool.get_status_display()}»."
                )
        elif tool.status != Tool.Status.ISSUED:
            locked.errors.append(
                f"«{tool.name}»: нельзя {action}, статус «{tool.get_status_display()}»."
            )
        elif tool.current_site_id != site.pk:
            locked.errors.append(f"«{tool.name}»: числится не на этом объекте.")


def _check_hand_quantities(locked, site):
    """
    Проверить количество ручного инструмента; ошибки дописываются в locked.errors.

    site указан  — нельзя взять больше, чем числится на этом объекте (selectors);
    site не указан — нельзя взять больше, чем лежит на складе (available).
    """
    for hand_id in locked.hand_ids:
        hand_tool = locked.hand_tools.get(hand_id)
        quantity = locked.quantities[hand_id]
        if hand_tool is None:
            locked.errors.append(f"Ручной инструмент с id {hand_id} не найден.")
        elif quantity < 1:
            locked.errors.append(f"«{hand_tool.name}»: количество должно быть не меньше 1.")
        else:
            limit = hand_tool.available if site is None else selectors.hand_tool_on_site(hand_tool, site)
            place = "на складе" if site is None else "на объекте"
            if quantity > limit:
                locked.errors.append(
                    f"«{hand_tool.name}»: запрошено {quantity}, {place} числится {limit}."
                )


# ---------------------------------------------------------------------------
# Выдача набора на объект (issued)
# ---------------------------------------------------------------------------

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
    _check_not_empty(tools, hand_tools)

    locked = _lock_positions(tools, hand_tools)
    errors = locked.errors

    for tool_id in locked.tool_ids:
        tool = locked.tools.get(tool_id)
        if tool is None:
            errors.append(f"Инструмент с id {tool_id} не найден.")
        elif tool.status != Tool.Status.AVAILABLE:
            errors.append(f"«{tool.name}»: нельзя выдать, статус «{tool.get_status_display()}».")

    for hand_id in locked.hand_ids:
        hand_tool = locked.hand_tools.get(hand_id)
        quantity = locked.quantities[hand_id]
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

    return _write_set(
        locked, movement_type=MovementType.ISSUED, site=site,
        user=user, taken_by=taken_by, note=note,
    )


# ---------------------------------------------------------------------------
# Приём (returned)
# ---------------------------------------------------------------------------

@transaction.atomic
def receive_from_site(*, user, site, tools=(), hand_tools=(), taken_by="", note=""):
    """
    Принять набор позиций с объекта на склад одной операцией.

    tools      — штучные позиции: [Tool, ...]
    hand_tools — ручной инструмент с количеством: [(HandTool, 3), ...]
    taken_by   — кто привёз (текст, по желанию).

    Правила (DECISIONS, разделы 13 и 14):
    - штучную позицию можно принять, только если она выдана (статус «выдан») и
      числится именно на этом объекте; «не найденную» принять нельзя;
    - ручной инструмент принимается общим количеством по объекту: нельзя принять
      больше, чем на этом объекте числится (считает selectors.hand_tool_on_site);
    - «всё или ничего» и один новый batch на операцию, как при выдаче.

    Если что-то не найдено при приёмке, это отдельная операция «не найден»
    (в плане следующим шагом), а не частичный приём этой функцией.
    Возвращает batch (UUID).
    """
    tools = list(tools)
    hand_tools = list(hand_tools)

    if site is None:
        raise ServiceError("Не указан объект.")
    _check_not_empty(tools, hand_tools)

    locked = _lock_positions(tools, hand_tools)
    _check_tools_at(locked, site, "принять")
    _check_hand_quantities(locked, site)

    if locked.errors:
        raise ServiceError("\n".join(locked.errors))

    return _write_set(
        locked, movement_type=MovementType.RETURNED, site=site,
        user=user, taken_by=taken_by, note=note,
    )


@transaction.atomic
def receive_from_servicing(*, user, tools, taken_by="", note=""):
    """
    Принять штучные позиции из ремонта на склад (приём без объекта).

    Ручной инструмент в ремонт не отправляется (DECISIONS, раздел 14), поэтому
    принимаются только штучные позиции со статусом «в ремонте».
    Возвращает batch (UUID).
    """
    tools = list(tools)
    _check_not_empty(tools, [])

    locked = _lock_positions(tools, [])
    errors = locked.errors

    for tool_id in locked.tool_ids:
        tool = locked.tools.get(tool_id)
        if tool is None:
            errors.append(f"Инструмент с id {tool_id} не найден.")
        elif tool.status != Tool.Status.SERVICING:
            errors.append(
                f"«{tool.name}»: нельзя принять из ремонта, статус «{tool.get_status_display()}»."
            )

    if errors:
        raise ServiceError("\n".join(errors))

    return _write_set(
        locked, movement_type=MovementType.RETURNED, site=None,
        user=user, taken_by=taken_by, note=note,
    )


# ---------------------------------------------------------------------------
# Не найден, списание, ремонт (DECISIONS, раздел 14)
# ---------------------------------------------------------------------------

@transaction.atomic
def mark_missing(*, user, site, tools=(), hand_tools=(), taken_by="", note=""):
    """
    Отметить позиции не найденными на объекте.

    Это возможно только для того, что числится на этом объекте (выдано и не принято):
    штучная позиция должна быть выдана на этот объект, ручного инструмента нельзя
    потерять больше, чем там числится. Запись остаётся в журнале, из total ручного
    инструмента потерянное вычитается (см. recalc_hand_tool).
    Возвращает batch (UUID).
    """
    tools = list(tools)
    hand_tools = list(hand_tools)

    if site is None:
        raise ServiceError("Не указан объект.")
    _check_not_empty(tools, hand_tools)

    locked = _lock_positions(tools, hand_tools)
    _check_tools_at(locked, site, "отметить не найденным")
    _check_hand_quantities(locked, site)

    if locked.errors:
        raise ServiceError("\n".join(locked.errors))

    return _write_set(
        locked, movement_type=MovementType.MISSING, site=site,
        user=user, taken_by=taken_by, note=note,
    )


@transaction.atomic
def write_off(*, user, site=None, tools=(), hand_tools=(), note=""):
    """
    Списать позиции.

    site не указан — списание со склада: штучная позиция «на складе», «в ремонте» или
                     «не найден» (потерянное можно списать), ручного инструмента не больше,
                     чем в наличии на складе;
    site указан    — списание с объекта: штучная позиция выдана на этом объекте,
                     ручного инструмента не больше, чем там числится.
    Потерянный ручной инструмент списывать не нужно и нельзя: он уже вычтен из total
    при отметке «не найден», в наличии и на объекте его нет (DECISIONS, раздел 14).
    Возвращает batch (UUID).
    """
    tools = list(tools)
    hand_tools = list(hand_tools)
    _check_not_empty(tools, hand_tools)

    locked = _lock_positions(tools, hand_tools)
    _check_tools_at(
        locked, site, "списать",
        warehouse_statuses=(Tool.Status.AVAILABLE, Tool.Status.SERVICING, Tool.Status.MISSING),
    )
    _check_hand_quantities(locked, site)

    if locked.errors:
        raise ServiceError("\n".join(locked.errors))

    return _write_set(
        locked, movement_type=MovementType.WRITTEN_OFF, site=site,
        user=user, taken_by="", note=note,
    )


@transaction.atomic
def send_to_servicing(*, user, tools, site=None, taken_by="", note=""):
    """
    Отправить штучные позиции в ремонт.

    site не указан — со склада (статус «на складе»);
    site указан    — с объекта (позиция выдана на этом объекте).
    Ручной инструмент в ремонт не отправляется (DECISIONS, раздел 14).
    Возврат из ремонта это receive_from_servicing.
    Возвращает batch (UUID).
    """
    tools = list(tools)
    _check_not_empty(tools, [])

    locked = _lock_positions(tools, [])
    _check_tools_at(locked, site, "отправить в ремонт", warehouse_statuses=(Tool.Status.AVAILABLE,))

    if locked.errors:
        raise ServiceError("\n".join(locked.errors))

    return _write_set(
        locked, movement_type=MovementType.SERVICING, site=site,
        user=user, taken_by=taken_by, note=note,
    )


# ---------------------------------------------------------------------------
# Отмена (DECISIONS, разделы 6 и 13)
# ---------------------------------------------------------------------------

def _cancel(tool_row_ids, hand_row_ids):
    """
    Отменить строки журнала: пометить is_cancelled и пересчитать состояние позиций.

    Строки журнала не удаляются и не правятся (журнал только дописывается), меняется
    только флаг. Состояние позиции после этого не откатывается обратной арифметикой,
    а пересчитывается по оставшимся действующим записям.

    Правила (DECISIONS, раздел 13):
    - отменить можно только последнюю действующую операцию по позиции;
    - постановку на баланс (added) отменять нельзя: ошибки прихода исправляются
      отдельно (инвентаризация, позже);
    - всё или ничего: если хоть одну строку отменить нельзя, не отменяется ни одна.
    Вызывать только внутри transaction.atomic.
    """
    # Сначала блокируем позиции этих строк (порядок как везде: по id, штучные, потом ручные),
    # потом заново читаем строки: пока мы ждали блокировку, кто-то мог их отменить.
    tool_ids = sorted(set(
        ToolMovement.objects.filter(pk__in=tool_row_ids).values_list("tool_id", flat=True)
    ))
    hand_ids = sorted(set(
        HandToolMovement.objects.filter(pk__in=hand_row_ids).values_list("hand_tool_id", flat=True)
    ))
    tools = {
        t.pk: t for t in Tool.objects.select_for_update().filter(pk__in=tool_ids).order_by("pk")
    }
    hand_tools = {
        h.pk: h for h in HandTool.objects.select_for_update().filter(pk__in=hand_ids).order_by("pk")
    }

    tool_rows = list(ToolMovement.objects.filter(pk__in=tool_row_ids, is_cancelled=False))
    hand_rows = list(HandToolMovement.objects.filter(pk__in=hand_row_ids, is_cancelled=False))
    if not tool_rows and not hand_rows:
        raise ServiceError("Нечего отменять: записи уже отменены.")

    errors = []
    for row in tool_rows:
        name = tools[row.tool_id].name
        if row.type == MovementType.ADDED:
            errors.append(f"«{name}»: постановку на баланс отменять нельзя.")
        elif ToolMovement.objects.filter(
            tool_id=row.tool_id, is_cancelled=False, pk__gt=row.pk,
        ).exists():
            errors.append(
                f"«{name}»: после этой операции были другие, отменить можно только последнюю."
            )
    for row in hand_rows:
        name = hand_tools[row.hand_tool_id].name
        if row.type == MovementType.ADDED:
            errors.append(f"«{name}»: постановку на баланс отменять нельзя.")
        elif HandToolMovement.objects.filter(
            hand_tool_id=row.hand_tool_id, is_cancelled=False, pk__gt=row.pk,
        ).exists():
            errors.append(
                f"«{name}»: после этой операции были другие, отменить можно только последнюю."
            )
    if errors:
        raise ServiceError("\n".join(errors))

    ToolMovement.objects.filter(pk__in=[r.pk for r in tool_rows]).update(is_cancelled=True)
    HandToolMovement.objects.filter(pk__in=[r.pk for r in hand_rows]).update(is_cancelled=True)

    for tool in tools.values():
        recalc_tool(tool)
    for hand_tool in hand_tools.values():
        recalc_hand_tool(hand_tool)


@transaction.atomic
def cancel_batch(*, user, batch):
    """
    Отменить набор целиком: все строки обоих журналов с этим batch.

    Если хоть по одной позиции набора уже были другие операции, не отменяется ничего.
    """
    tool_row_ids = list(ToolMovement.objects.filter(batch=batch).values_list("pk", flat=True))
    hand_row_ids = list(HandToolMovement.objects.filter(batch=batch).values_list("pk", flat=True))
    if not tool_row_ids and not hand_row_ids:
        raise ServiceError("Набор не найден.")
    _cancel(tool_row_ids, hand_row_ids)


@transaction.atomic
def cancel_movement(*, user, movement):
    """
    Отменить одну запись журнала (ToolMovement или HandToolMovement), например
    одну позицию, ошибочно попавшую в набор. Остальные строки набора не трогаются.
    """
    if isinstance(movement, ToolMovement):
        _cancel([movement.pk], [])
    elif isinstance(movement, HandToolMovement):
        _cancel([], [movement.pk])
    else:
        raise ServiceError("Неизвестный тип записи журнала.")

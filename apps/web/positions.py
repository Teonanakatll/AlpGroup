"""
Разбор позиций из формы выдачи и приёма (сайт).

Форма присылает: tools=<id> (флажки штучного) и qty_<id>=<число> (ручной инструмент).
Пустое количество или 0 значит «не выбрано». Здесь только разбор формата;
правила учёта (статус, остатки) проверяет services.py.
"""
from dataclasses import dataclass, field

from apps.inventory.models import HandTool, Tool


@dataclass
class Positions:
    tools: list = field(default_factory=list)        # [Tool, ...]
    hand_tools: list = field(default_factory=list)   # [(HandTool, количество), ...]
    selected_tools: set = field(default_factory=set)  # id штучных: чтобы после ошибки флажки остались
    quantities: dict = field(default_factory=dict)    # {id ручного: количество} по той же причине
    errors: list = field(default_factory=list)


def parse_positions(data):
    """Достаёт из POST выбранные позиции. Неверный формат даёт строки в errors."""
    result = Positions()

    tool_ids = set()
    for raw in data.getlist("tools"):
        try:
            tool_ids.add(int(raw))
        except ValueError:
            result.errors.append("Неверный номер штучной позиции.")
    found = {tool.pk: tool for tool in Tool.objects.filter(pk__in=tool_ids)}
    for tool_id in sorted(tool_ids):
        if tool_id in found:
            result.tools.append(found[tool_id])
        else:
            result.errors.append(f"Штучная позиция {tool_id} не найдена.")
    result.selected_tools = set(found)

    wanted = {}
    for key, raw in data.items():
        if not key.startswith("qty_") or not raw.strip():
            continue
        try:
            hand_id, quantity = int(key[4:]), int(raw)
        except ValueError:
            result.errors.append(f"Количество «{raw}» не число, нужно целое.")
            continue
        if quantity < 0:
            result.errors.append("Количество не может быть отрицательным.")
        elif quantity > 0:
            wanted[hand_id] = quantity
    hands = {hand.pk: hand for hand in HandTool.objects.filter(pk__in=wanted)}
    for hand_id, quantity in sorted(wanted.items()):
        if hand_id in hands:
            result.hand_tools.append((hands[hand_id], quantity))
            result.quantities[hand_id] = quantity
        else:
            result.errors.append(f"Ручной инструмент {hand_id} не найден.")
    return result

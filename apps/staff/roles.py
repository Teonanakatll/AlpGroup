"""
Роли и права (SPEC, разд. 7.1). Единственное место, где решается, что можно пользователю.

Роль = группа Django (группы создаёт миграция staff/0001). Вьюхи, шаблоны и API не проверяют
группы сами, а спрашивают здесь: effective_role(request), can_operate(request), can_manage(request).
Поэтому тестовый переключатель ролей (роль в сессии) и будущий кабинет админа меняют только этот файл.

Что роль меняет: делает ли человек складские операции и управляет ли справочниками.
Правила журнала (отмена только последней операции и т.п.) роль не меняет, они в services.py.
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.models import Group
from django.shortcuts import redirect

ADMIN = "admin"
STOREKEEPER = "storekeeper"
RESPONSIBLE = "responsible"
VIEWER = "viewer"

# Роль → название группы Django. Порядок важен: если у пользователя несколько групп,
# действует первая (самая сильная) из этого списка.
GROUPS = {
    ADMIN: "Администратор",
    STOREKEEPER: "Кладовщик",
    RESPONSIBLE: "Ответственное лицо",
    VIEWER: "Наблюдатель",
}

# Подписи для интерфейса (в шапке, в сообщениях). Пока совпадают с группами.
LABELS = dict(GROUPS)

OPERATORS = {ADMIN, STOREKEEPER}     # делают складские операции и отмену
MANAGERS = {ADMIN}                   # управляют справочниками и пользователями


def user_role(user):
    """
    Роль пользователя по его группам. Суперпользователь всегда администратор.
    Без группы (в том числе гость DEMO_USER) — наблюдатель: по умолчанию только просмотр,
    чтобы новый пользователь ничего не мог испортить, пока ему не выдали роль.
    """
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return ADMIN
    names = set(user.groups.values_list("name", flat=True))
    for role, group in GROUPS.items():
        if group in names:
            return role
    return VIEWER


def effective_role(request):
    """Роль, по которой проверяются права в этом запросе. Запоминается на время запроса."""
    if not hasattr(request, "_effective_role"):
        request._effective_role = user_role(request.user)
    return request._effective_role


def can_operate(request):
    """Складские операции: баланс, выдача, приём, не найден, списание, ремонт, отмена, фото позиции."""
    return effective_role(request) in OPERATORS


def can_manage(request):
    """Справочники и пользователи (пока это Django-админка, позже кабинет админа)."""
    return effective_role(request) in MANAGERS


def assign_role(user, role):
    """Выдать пользователю роль: убрать из других ролевых групп, добавить в нужную."""
    user.groups.remove(*Group.objects.filter(name__in=GROUPS.values()))
    group, _ = Group.objects.get_or_create(name=GROUPS[role])
    user.groups.add(group)


def operator_required(view):
    """
    Декоратор вьюхи сайта: пускает только тех, кто делает операции (ставить после login_required).
    Остальным — сообщение в плашке и возврат на главную, а не голая страница 403.
    """
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not can_operate(request):
            messages.error(
                request,
                f"Операции недоступны: ваша роль «{LABELS[effective_role(request)]}» только для просмотра.",
            )
            return redirect("web:home")
        return view(request, *args, **kwargs)
    return wrapper


def roles(request):
    """Контекст-процессор: роль и права для шаблонов (role, role_label, can_operate, can_manage)."""
    role = effective_role(request) if hasattr(request, "user") else None
    return {
        "role": role,
        "role_label": LABELS.get(role, ""),
        "can_operate": role in OPERATORS,
        "can_manage": role in MANAGERS,
    }

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
from django.conf import settings
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


# Тестовый переключатель ролей (DEMO_ROLE_SWITCH=1, только стенд): выбранная роль лежит в сессии
# под этим ключом и подменяет роль из групп. Пользователь в базе не меняется.
SESSION_KEY = "demo_role"


def switched_role(request):
    """Роль, выбранная переключателем, или None (флаг выключен, не выбрано, не вошёл)."""
    if not settings.DEMO_ROLE_SWITCH or not request.user.is_authenticated:
        return None
    role = request.session.get(SESSION_KEY)
    return role if role in GROUPS else None


def set_switched_role(request, role):
    """Запомнить роль переключателя в сессии (role=None — вернуться к роли из групп)."""
    if role in GROUPS:
        request.session[SESSION_KEY] = role
    else:
        request.session.pop(SESSION_KEY, None)
    request.__dict__.pop("_effective_role", None)


def effective_role(request):
    """
    Роль, по которой проверяются права в этом запросе: выбранная переключателем (если он включён),
    иначе по группам. Запоминается на время запроса.
    """
    if "_effective_role" not in request.__dict__:
        request._effective_role = switched_role(request) or user_role(request.user)
    return request._effective_role


def can_operate(request):
    """Складские операции: баланс, выдача, приём, не найден, списание, ремонт, отмена, фото позиции."""
    return effective_role(request) in OPERATORS


def can_manage(request):
    """Справочники и пользователи (пока это Django-админка, позже кабинет админа)."""
    return effective_role(request) in MANAGERS


def own_site_ids(request):
    """
    Какие объекты видит пользователь в журнале: None — все; иначе id его объектов.
    Ограничение только у ответственного лица (объекты, где он указан ответственным, SPEC 7.1).
    """
    if effective_role(request) != RESPONSIBLE:
        return None
    from apps.sites.models import Site          # здесь, а не сверху: roles грузится в settings-процессоре рано
    return set(Site.objects.filter(responsible=request.user).values_list("pk", flat=True))


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


# Кнопки переключателя: (роль, полная подпись, короткая для телефона)
SWITCH_BUTTONS = [
    (ADMIN, "Админ", "А"),
    (STOREKEEPER, "Кладовщик", "К"),
    (RESPONSIBLE, "Отв. лицо", "О"),
    (VIEWER, "Наблюдатель", "Н"),
]


def roles(request):
    """
    Контекст-процессор: роль и права для шаблонов (role, role_label, can_operate, can_manage);
    при DEMO_ROLE_SWITCH ещё кнопки переключателя (role_switch).
    """
    role = effective_role(request) if hasattr(request, "user") else None
    show_switch = settings.DEMO_ROLE_SWITCH and role is not None
    return {
        "role": role,
        "role_label": LABELS.get(role, ""),
        "can_operate": role in OPERATORS,
        "can_manage": role in MANAGERS,
        "role_switch": SWITCH_BUTTONS if show_switch else None,
    }

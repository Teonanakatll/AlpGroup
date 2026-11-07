"""Права для DRF: те же правила, что на сайте, через apps/staff/roles.py."""
from rest_framework.permissions import BasePermission

from . import roles


class CanOperate(BasePermission):
    """Складские операции и отмена через API: только роли с правом операций (иначе 403)."""
    message = "Операции недоступны для вашей роли: только просмотр."

    def has_permission(self, request, view):
        return roles.can_operate(request)

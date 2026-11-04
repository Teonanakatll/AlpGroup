"""Автовход под гостем для показа сайта (DEMO_USER в .env, см. docs/DEPLOY.md «Быстрый показ»)."""
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.urls import reverse


class DemoAutoLoginMiddleware:
    """Если задан DEMO_USER, не вошедший посетитель сразу входит под этим пользователем.

    Совсем без пользователя нельзя: у каждой записи журнала обязательное поле «Кто внёс».
    Гость создаётся сам, без пароля и без is_staff, поэтому админка ему закрыта.
    Страница входа и /admin/ пропускаются: так владелец может войти под своим логином.
    Без DEMO_USER (обычная работа, сервер) middleware ничего не делает.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        username = settings.DEMO_USER
        if username and not request.user.is_authenticated and not self._skip(request.path):
            user, created = get_user_model().objects.get_or_create(username=username)
            if created:
                user.set_unusable_password()     # войти под гостем можно только автовходом
                user.save(update_fields=["password"])
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return self.get_response(request)

    @staticmethod
    def _skip(path):
        return path.startswith(reverse("admin:index")) or path == reverse("web:login")

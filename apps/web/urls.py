"""Адреса сайта (подключены в config/urls.py с корня)."""
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.home, name="home"),
    path("inventory/", views.inventory, name="inventory"),
    path("operations/", views.operations, name="operations"),
    path("operations/issue/", views.issue, name="issue"),
    path("operations/receive/", views.receive, name="receive"),
    path("operations/missing/", views.missing, name="missing"),
    path("operations/write-off/", views.write_off, name="write_off"),
    path("operations/servicing/", views.servicing, name="servicing"),
    path("operations/from-servicing/", views.from_servicing, name="from_servicing"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="web/login.html", redirect_authenticated_user=True),
        name="login",
    ),
    # Выход только методом POST (так требует Django): в меню это форма с кнопкой
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]

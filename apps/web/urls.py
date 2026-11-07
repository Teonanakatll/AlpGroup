"""Адреса сайта (подключены в config/urls.py с корня)."""
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.home, name="home"),
    path("inventory/", views.inventory, name="inventory"),
    path("journal/", views.journal, name="journal"),
    path("journal/cancel-batch/<uuid:batch>/", views.cancel_batch, name="cancel_batch"),
    path("journal/cancel/<str:kind>/<int:pk>/", views.cancel_movement, name="cancel_movement"),
    path("inventory/tool/<int:pk>/", views.tool_detail, name="tool_detail"),
    path("inventory/tool/<int:pk>/photos/", views.tool_photos, name="tool_photos"),
    path("inventory/photo/<int:pk>/main/", views.photo_main, name="photo_main"),
    path("inventory/photo/<int:pk>/delete/", views.photo_delete, name="photo_delete"),
    path("inventory/hand/<int:pk>/", views.hand_tool_detail, name="hand_tool_detail"),
    path("operations/", views.operations, name="operations"),
    path("operations/add/", views.add, name="add"),
    path("operations/issue/", views.issue, name="issue"),
    path("operations/receive/", views.receive, name="receive"),
    path("operations/missing/", views.missing, name="missing"),
    path("operations/write-off/", views.write_off, name="write_off"),
    path("operations/servicing/", views.servicing, name="servicing"),
    path("operations/from-servicing/", views.from_servicing, name="from_servicing"),
    path("role/", views.switch_role, name="switch_role"),      # переключатель ролей стенда (DEMO_ROLE_SWITCH)
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="web/login.html", redirect_authenticated_user=True),
        name="login",
    ),
    # Выход только методом POST (так требует Django): в меню это форма с кнопкой
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]

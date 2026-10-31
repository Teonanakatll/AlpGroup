"""
Адреса API (подключены в config/urls.py под /api/).

Router сам делает адреса для списка и одной записи:
  /api/tools/            список штучного инструмента
  /api/tools/<id>/       одна позиция
  /api/tools/<id>/history/   её история
Так же для hand-tools, sites и categories; плюс /api/sites/<id>/on-site/ и /api/available/.
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("tools", views.ToolViewSet, basename="tool")
router.register("hand-tools", views.HandToolViewSet, basename="handtool")
router.register("sites", views.SiteViewSet, basename="site")
router.register("categories", views.CategoryViewSet, basename="category")

urlpatterns = [
    path("available/", views.AvailableView.as_view(), name="available"),
    *router.urls,
]

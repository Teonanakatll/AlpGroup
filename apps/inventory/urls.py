"""
Адреса API (подключены в config/urls.py под /api/).

Router сам делает адреса для списка и одной записи:
  /api/tools/            список штучного инструмента
  /api/tools/<id>/       одна позиция
  /api/tools/<id>/history/   её история
Так же для hand-tools, sites и categories; плюс /api/sites/<id>/on-site/ и /api/available/.

Операции (POST): /api/issue/, /api/receive/, /api/receive-from-servicing/, /api/missing/,
/api/write-off/, /api/servicing/, /api/cancel-batch/, /api/cancel-movement/.
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
    path("issue/", views.IssueView.as_view(), name="issue"),
    path("receive/", views.ReceiveView.as_view(), name="receive"),
    path("receive-from-servicing/", views.ReceiveFromServicingView.as_view(), name="receive-from-servicing"),
    path("missing/", views.MissingView.as_view(), name="missing"),
    path("write-off/", views.WriteOffView.as_view(), name="write-off"),
    path("servicing/", views.ServicingView.as_view(), name="servicing"),
    path("cancel-batch/", views.CancelBatchView.as_view(), name="cancel-batch"),
    path("cancel-movement/", views.CancelMovementView.as_view(), name="cancel-movement"),
    *router.urls,
]

from django.contrib import admin

from .models import Site, WorkType


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    """Объекты: здесь назначается ответственное лицо (пока нет кабинета админа на сайте)."""
    list_display = ("name", "work_type", "responsible")
    list_filter = ("responsible", "work_type")
    search_fields = ("name",)


@admin.register(WorkType)
class WorkTypeAdmin(admin.ModelAdmin):
    list_display = ("name",)

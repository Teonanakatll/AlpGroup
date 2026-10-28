from django.contrib import admin
from .models import Category, Tool, HandTool, ToolPhoto, ToolMovement, HandToolMovement


class ToolPhotoInline(admin.TabularInline):
    model = ToolPhoto
    extra = 1


@admin.register(Tool)
class ToolAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "status")
    inlines = [ToolPhotoInline]

@admin.register(HandTool)
class HandTootAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "total", "issued")

@admin.register(ToolMovement)
class ToolMovementAdmin(admin.ModelAdmin):
    list_display = ("site", "type", "tool")

@admin.register(HandToolMovement)
class HandToolMovementAdmin(admin.ModelAdmin):
    list_display = ("site", "type", "hand_tool")

admin.site.register(Category)


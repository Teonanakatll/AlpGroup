"""
Админка склада.

Админка не меняет состояние сама: всё, что влияет на статусы и счётчики, идёт
через services.py (DECISIONS, раздел 6). Поэтому:
- статусы, объект и счётчики показаны только для чтения;
- новая позиция создаётся через services.register_tool, а не простым save();
- журналы доступны только для просмотра;
- выдача, приём и приход сделаны как admin actions, которые вызывают services.
"""
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db import transaction
from django.template.response import TemplateResponse
from django.urls import reverse

from . import forms, services
from .models import Category, Tool, HandTool, ToolPhoto, ToolMovement, HandToolMovement


# ---------------------------------------------------------------------------
# Общий ход действия с промежуточной страницей
# ---------------------------------------------------------------------------

def run_operation(modeladmin, request, objects, *, title, form, perform, done):
    """
    Админ-действие с промежуточной страницей, где вводятся объект, количества и т.п.

    Как это работает в Django: действие вызывается дважды.
    1. Первый раз без ключа "apply": показываем пустую форму.
    2. Второй раз форма присылает данные вместе с "apply": проверяем их и вызываем
       services. Если service отказал (ServiceError), показываем форму снова с ошибками
       и ничего не меняем. Если всё хорошо, возвращаем None, и Django сам вернёт
       пользователя на список.

    objects — выбранные позиции (список), показываются на странице;
    form    — готовый экземпляр формы (на втором шаге уже с данными из POST);
    perform — функция form -> batch, внутри вызывает нужный service;
    done    — функция (form, batch) -> текст сообщения об успехе.
    """
    if "apply" in request.POST and form.is_valid():
        try:
            batch = perform(form)
        except services.ServiceError as error:
            # В тексте ошибки по строке на каждую проблемную позицию.
            for line in str(error).splitlines():
                form.add_error(None, line)
        else:
            messages.success(request, done(form, batch))
            return None

    context = {
        **modeladmin.admin_site.each_context(request),
        "title": title,
        "opts": modeladmin.model._meta,
        "form": form,
        "objects": objects,
        "action_name": request.POST.get("action"),
        "action_checkbox_name": ACTION_CHECKBOX_NAME,
        "changelist_url": reverse(
            f"admin:{modeladmin.model._meta.app_label}_{modeladmin.model._meta.model_name}_changelist"
        ),
    }
    return TemplateResponse(request, "admin/inventory/operation_form.html", context)


def _bound(request, form_class, **kwargs):
    """Форма: пустая при первом показе, с данными из POST после нажатия «Выполнить»."""
    if "apply" in request.POST:
        return form_class(request.POST, **kwargs)
    return form_class(**kwargs)


def _site_args(form):
    """Объект, «кто взял» и примечание из формы, в виде аргументов для services."""
    data = form.cleaned_data
    return {"site": data["site"], "taken_by": data["taken_by"], "note": data["note"]}


# ---------------------------------------------------------------------------
# Штучный инструмент
# ---------------------------------------------------------------------------

class ToolPhotoInline(admin.TabularInline):
    model = ToolPhoto
    extra = 1


@admin.register(Tool)
class ToolAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "status", "current_site")
    list_filter = ("status", "category")
    search_fields = ("name",)
    # removed_date тоже только для чтения: его должен выставлять service при списании
    # (пока не выставляет), а ручная правка разошлась бы с журналом.
    readonly_fields = ("status", "current_site", "removed_date")
    inlines = [ToolPhotoInline]
    actions = ["issue_action", "receive_from_site_action", "receive_from_servicing_action"]

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return
        # Новую позицию заводит service: вместе с ней в журнал пишется «поставлен на баланс».
        # Позиция без этой записи нарушила бы правило «журнал источник истины».
        created = services.register_tool(
            user=request.user, name=obj.name, category=obj.category,
            note=obj.note, on_balance_date=obj.on_balance_date,
        )
        # Дальше админка работает с obj (сохраняет фото, пишет сообщение), поэтому
        # переносим в него то, что создал service.
        obj.pk = created.pk
        obj.status = created.status
        obj.current_site = created.current_site
        obj._state.adding = False
        obj._state.db = created._state.db

    @admin.action(description="Выдать на объект", permissions=["change"])
    def issue_action(self, request, queryset):
        tools = list(queryset.order_by("name"))
        form = _bound(request, forms.SiteOperationForm)
        return run_operation(
            self, request, tools, title="Выдать на объект", form=form,
            perform=lambda f: services.issue_to_site(user=request.user, tools=tools, **_site_args(f)),
            done=lambda f, batch: f"Выдано на объект «{f.cleaned_data['site']}»: {len(tools)} шт.",
        )

    @admin.action(description="Принять с объекта", permissions=["change"])
    def receive_from_site_action(self, request, queryset):
        tools = list(queryset.order_by("name"))
        # Если все выбранные позиции на одном объекте, подставляем его сами.
        sites = {tool.current_site_id for tool in tools}
        initial = {"site": sites.pop()} if len(sites) == 1 and None not in sites else {}
        form = _bound(request, forms.ReceiveFromSiteForm, initial=initial)
        return run_operation(
            self, request, tools, title="Принять с объекта", form=form,
            perform=lambda f: services.receive_from_site(user=request.user, tools=tools, **_site_args(f)),
            done=lambda f, batch: f"Принято с объекта «{f.cleaned_data['site']}»: {len(tools)} шт.",
        )

    @admin.action(description="Принять из ремонта", permissions=["change"])
    def receive_from_servicing_action(self, request, queryset):
        tools = list(queryset.order_by("name"))
        form = _bound(request, forms.ReceiveFromServicingForm)
        return run_operation(
            self, request, tools, title="Принять из ремонта", form=form,
            perform=lambda f: services.receive_from_servicing(
                user=request.user, tools=tools,
                taken_by=f.cleaned_data["taken_by"], note=f.cleaned_data["note"],
            ),
            done=lambda f, batch: f"Принято из ремонта: {len(tools)} шт.",
        )


# ---------------------------------------------------------------------------
# Ручной инструмент (количеством)
# ---------------------------------------------------------------------------

@admin.register(HandTool)
class HandToolAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "total", "issued", "available")
    list_filter = ("category",)
    search_fields = ("name",)
    # Создаётся с нулём, количество добавляется только действием «Поставить на баланс».
    readonly_fields = ("total", "issued")
    actions = ["add_stock_action", "issue_action", "receive_from_site_action"]

    @admin.display(description="На складе")
    def available(self, obj):
        return obj.available

    @admin.action(description="Поставить на баланс (приход)", permissions=["change"])
    def add_stock_action(self, request, queryset):
        hand_tools = list(queryset.order_by("name"))
        form = _bound(request, forms.HandStockForm, hand_tools=hand_tools)

        def perform(f):
            # Один приход на несколько позиций: общий batch, всё или ничего.
            with transaction.atomic():
                batch = services.new_batch()
                for hand_tool, quantity in f.quantities():
                    services.add_hand_tool_stock(
                        user=request.user, hand_tool=hand_tool, quantity=quantity,
                        note=f.cleaned_data["note"], batch=batch,
                    )
            return batch

        return run_operation(
            self, request, hand_tools, title="Поставить на баланс", form=form,
            perform=perform,
            done=lambda f, batch: f"Поставлено на баланс позиций: {len(hand_tools)}.",
        )

    @admin.action(description="Выдать на объект", permissions=["change"])
    def issue_action(self, request, queryset):
        hand_tools = list(queryset.order_by("name"))
        form = _bound(request, forms.HandIssueForm, hand_tools=hand_tools)
        return run_operation(
            self, request, hand_tools, title="Выдать на объект", form=form,
            perform=lambda f: services.issue_to_site(
                user=request.user, hand_tools=f.quantities(), **_site_args(f),
            ),
            done=lambda f, batch: f"Выдано на объект «{f.cleaned_data['site']}»: позиций {len(hand_tools)}.",
        )

    @admin.action(description="Принять с объекта", permissions=["change"])
    def receive_from_site_action(self, request, queryset):
        hand_tools = list(queryset.order_by("name"))
        form = _bound(request, forms.HandReceiveForm, hand_tools=hand_tools)
        return run_operation(
            self, request, hand_tools, title="Принять с объекта", form=form,
            perform=lambda f: services.receive_from_site(
                user=request.user, hand_tools=f.quantities(), **_site_args(f),
            ),
            done=lambda f, batch: f"Принято с объекта «{f.cleaned_data['site']}»: позиций {len(hand_tools)}.",
        )


# ---------------------------------------------------------------------------
# Журналы: только просмотр
# ---------------------------------------------------------------------------

class ReadOnlyJournalAdmin(admin.ModelAdmin):
    """Журнал только дописывается через services.py; в админке его можно лишь смотреть."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ToolMovement)
class ToolMovementAdmin(ReadOnlyJournalAdmin):
    list_display = ("created_at", "type", "tool", "site", "taken_by", "created_by", "is_cancelled")
    list_filter = ("type", "is_cancelled", "site")
    search_fields = ("tool__name", "taken_by")
    list_select_related = ("tool", "site", "created_by")


@admin.register(HandToolMovement)
class HandToolMovementAdmin(ReadOnlyJournalAdmin):
    list_display = (
        "created_at", "type", "hand_tool", "quantity", "site", "taken_by", "created_by", "is_cancelled",
    )
    list_filter = ("type", "is_cancelled", "site")
    search_fields = ("hand_tool__name", "taken_by")
    list_select_related = ("hand_tool", "site", "created_by")


admin.site.register(Category)

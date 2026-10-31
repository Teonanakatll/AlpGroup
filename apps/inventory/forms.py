"""
Формы промежуточных страниц админ-действий (выдача, приём, приход).

Формы только собирают данные: объект, «кто взял», примечание, количества.
Проверки правил учёта делает services.py, здесь их нет.
"""
from django import forms

from apps.sites.models import Site


class SiteOperationForm(forms.Form):
    """Операция над позициями на объекте: объект, кто взял, примечание."""
    site = forms.ModelChoiceField(queryset=Site.objects.all(), label="Объект")
    taken_by = forms.CharField(label="Кто взял", max_length=200, required=False)
    note = forms.CharField(label="Примечание", max_length=300, required=False)


class ReceiveFromSiteForm(SiteOperationForm):
    """Приём с объекта: то же самое, но человек «привёз», а не «взял»."""
    taken_by = forms.CharField(label="Кто привёз", max_length=200, required=False)


class ReceiveFromServicingForm(forms.Form):
    """Приём из ремонта: объекта нет."""
    taken_by = forms.CharField(label="Кто привёз", max_length=200, required=False)
    note = forms.CharField(label="Примечание", max_length=300, required=False)


class HandQuantitiesMixin:
    """
    Добавляет поле «количество» на каждую выбранную позицию ручного инструмента.

    Поля создаются в __init__, потому что их число зависит от выбранных позиций.
    После is_valid() список пар [(HandTool, количество), ...] отдаёт quantities().
    """
    show_available = False  # подсказывать, сколько лежит на складе (нужно при выдаче)

    def __init__(self, *args, hand_tools=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.hand_tools = list(hand_tools)
        for hand_tool in self.hand_tools:
            self.fields[self._field_name(hand_tool)] = forms.IntegerField(
                label=f"{hand_tool.name}: количество",
                min_value=1,
                help_text=f"На складе: {hand_tool.available}" if self.show_available else "",
            )
        # Количества показываем сразу после объекта (или первыми, если объекта нет).
        quantity_fields = [self._field_name(h) for h in self.hand_tools]
        first = ["site"] if "site" in self.fields else []
        self.order_fields(first + quantity_fields)

    @staticmethod
    def _field_name(hand_tool):
        return f"qty_{hand_tool.pk}"

    def quantities(self):
        return [(h, self.cleaned_data[self._field_name(h)]) for h in self.hand_tools]


class HandIssueForm(HandQuantitiesMixin, SiteOperationForm):
    show_available = True


class HandReceiveForm(HandQuantitiesMixin, ReceiveFromSiteForm):
    pass


class HandStockForm(HandQuantitiesMixin, forms.Form):
    """Приход ручного инструмента: сколько штук поставить на баланс."""
    note = forms.CharField(label="Примечание", max_length=300, required=False)

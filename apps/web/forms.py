"""Формы сайта. Только сбор и разбор данных; правила учёта проверяет services.py."""
from django import forms

from apps.inventory.forms import SiteOperationForm
from apps.sites.models import Site


class IssueForm(SiteOperationForm):
    """
    Форма выдачи: объект выбирается из списка или вводится новый тут же.
    Если заполнено «новый объект», берём его (его создаст вьюха вместе с выдачей).
    """
    site = forms.ModelChoiceField(queryset=Site.objects.all(), label="Объект", required=False)
    new_site = forms.CharField(
        label="Или новый объект", max_length=300, required=False,
        widget=forms.TextInput(attrs={"placeholder": "Название нового объекта"}),
    )
    field_order = ["site", "new_site", "taken_by", "note"]

    def clean(self):
        cleaned = super().clean()
        cleaned["new_site"] = " ".join(cleaned.get("new_site", "").split())
        if not cleaned.get("site") and not cleaned["new_site"]:
            self.add_error("site", "Выберите объект или введите новый.")
        return cleaned

"""Формы сайта. Только сбор и разбор данных; правила учёта проверяет services.py."""
from django import forms

from apps.inventory.forms import SiteOperationForm
from apps.inventory.models import Category, HandTool
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


class MissingForm(SiteOperationForm):
    """«Не найден»: объект обязателен, указываем, кто сообщил о пропаже."""
    taken_by = forms.CharField(label="Кто сообщил", max_length=200, required=False)


class _SourceForm(forms.Form):
    """Операции со склада или с объекта: пустой «Откуда» означает склад."""
    site = forms.ModelChoiceField(queryset=Site.objects.all(), label="Откуда", required=False, empty_label="Склад")


class WriteOffForm(_SourceForm):
    note = forms.CharField(label="Причина, примечание", max_length=300, required=False)


class ServicingForm(_SourceForm):
    taken_by = forms.CharField(label="Кто отвёз", max_length=200, required=False)
    note = forms.CharField(label="Примечание", max_length=300, required=False)


class AddForm(forms.Form):
    """
    Постановка на баланс. Штучное: название, категория и сколько одинаковых штук завести.
    Количественное: либо пополнить существующую позицию, либо завести новую; quantity это сколько единиц.
    """
    KIND = [("tool", "Штучный инструмент"), ("hand", "Количественный (ручной)")]

    kind = forms.ChoiceField(label="Вид учёта", choices=KIND)
    name = forms.CharField(label="Название", max_length=200, required=False)
    category = forms.ModelChoiceField(queryset=Category.objects.all(), label="Категория", required=False,
                                      empty_label="Выберите категорию…")
    quantity = forms.IntegerField(label="Количество (штук)", min_value=1, max_value=100000, initial=1)
    existing_hand = forms.ModelChoiceField(
        queryset=HandTool.objects.order_by("name"), label="Или пополнить существующую", required=False,
        empty_label="Новая позиция", help_text="Только для количественного учёта",
    )
    note = forms.CharField(label="Примечание", max_length=300, required=False)
    photo = forms.ImageField(label="Фото (для штучных)", required=False)

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        existing = cleaned.get("existing_hand") if kind == "hand" else None
        cleaned["existing_hand"] = existing
        if kind == "tool" and cleaned.get("quantity") and cleaned["quantity"] > 50:
            self.add_error("quantity", "Штучных можно завести не больше 50 за раз.")
        if kind and not existing:
            if not " ".join(cleaned.get("name", "").split()):
                self.add_error("name", "Укажите название.")
            if not cleaned.get("category"):
                self.add_error("category", "Выберите категорию.")
        return cleaned


class MultiFileInput(forms.FileInput):
    allow_multiple_selected = True       # Django по умолчанию запрещает multiple, разрешаем явно


class PhotosForm(forms.Form):
    """Загрузка фото к штучной позиции: можно выбрать несколько файлов сразу."""
    photos = forms.Field(label="Фото", widget=MultiFileInput(attrs={"accept": "image/*"}), error_messages={"required": "Выберите файл."})

    def clean_photos(self):
        checker = forms.ImageField()        # каждую картинку проверяет как обычное поле-картинку (Pillow)
        return [checker.clean(f) for f in self.files.getlist("photos")]

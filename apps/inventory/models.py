from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Category(models.Model):
    name = models.CharField("Название", max_length=100)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="children", verbose_name="Родительская категория",
    )

    class Meta:
        verbose_name = "Категория"
        verbose_name_plural = "Категории"

    def __str__(self):
        return self.name


class Tool(models.Model):

    class Status(models.TextChoices):
        AVAILABLE = "available", "На складе"
        ISSUED = "issued", "Выдан"
        WRITTEN_OFF = "written_off", "Списан"
        SERVICING = "servicing", "В ремонте"
        MISSING = "missing", "Не найден"

    name = models.CharField("Название", max_length=200)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, verbose_name="Категория")
    status = models.CharField("Статус", max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    note = models.TextField("Примечание", blank=True)
    on_balance_date = models.DateField("Поставлен на баланс", default=timezone.localdate)
    removed_date = models.DateField("Снят с баланса", null=True, blank=True)

    class Meta:
        verbose_name = "Инструмент"
        verbose_name_plural = "Инструменты"

    def __str__(self):
        return self.name


class ToolPhoto(models.Model):
    tool = models.ForeignKey(Tool, on_delete=models.CASCADE, related_name="photos", verbose_name="Инструмент")
    image = models.ImageField("Фото", upload_to="tools/%Y/%m/")
    is_main = models.BooleanField("Главное", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Фото"
        verbose_name_plural = "Фото"
        constraints = [
            models.UniqueConstraint(
                fields=["tool"], condition=models.Q(is_main=True),
                name="one_main_photo_per_tool",
            )
        ]


class HandTool(models.Model):
    name = models.CharField("Название", max_length=200)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, verbose_name="Категория")
    total = models.PositiveIntegerField("Всего на балансе", default=0)
    issued = models.PositiveIntegerField("Выдано", default=0)
    note = models.TextField("Примечание", blank=True)

    class Meta:
        verbose_name = "Ручной инструмент (количеством)"
        verbose_name_plural = "Ручной инструмент (количеством)"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(issued__lte=models.F("total")),
                name="handtool_issued_lte_total",
            )
        ]

    @property
    def available(self):
        return self.total - self.issued

    def __str__(self):
        return self.name

class BaseMovement(models.Model):
    class Type(models.TextChoices):
        # название типа операции
        ISSUED = "issued", "Выдан"
        RETURNED = "returned", "Принят"
        WRITTEN_OFF = "written_off", "Списан"
        SERVICING = "servicing", "В ремонте"
        MISSING = "missing", "Не найден"

    type = models.CharField("Операция", max_length=20, choices=Type.choices)
    site = models.ForeignKey(
        "sites.Site", null=True, blank=True, on_delete=models.PROTECT,
        verbose_name="Объект",
    )
    taken_by = models.CharField("Кто взял", max_length=200, blank=True)
    created_at = models.DateTimeField("Время операции", auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="Кто внёс",
    )
    is_cancelled = models.BooleanField("Отменена", default=False)
    note = models.CharField("Примечание", max_length=300, blank=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class ToolMovement(BaseMovement):
    tool = models.ForeignKey(
        Tool, on_delete=models.PROTECT, related_name="movements",
        verbose_name="Инструмент",
    )

    class Meta(BaseMovement.Meta):
        verbose_name = "Движение инструмента"
        verbose_name_plural = "Движения инструмента"


class HandToolMovement(BaseMovement):
    hand_tool = models.ForeignKey(
        "HandTool", on_delete=models.PROTECT, related_name="movements",
        verbose_name="Ручной инструмент",
    )
    quantity = models.PositiveIntegerField(
        "Количество", validators=[MinValueValidator(1)],
    )

    class Meta(BaseMovement.Meta):
        verbose_name = "Движение ручного инструмента"
        verbose_name_plural = "Движения ручного инструмента"
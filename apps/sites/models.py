from django.db import models


class WorkType(models.Model):
    name = models.CharField("Вид работ", max_length=100)  # мойка, гидра, монтаж

    class Meta:
        verbose_name = "Вид работ"
        verbose_name_plural = "Виды работ"

    def __str__(self):
        return self.name


class Site(models.Model):
    name = models.CharField("Название или адрес", max_length=300)
    work_type = models.ForeignKey(WorkType, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Вид работ")

    class Meta:
        verbose_name = "Объект"
        verbose_name_plural = "Объекты"

    def __str__(self):
        return self.name

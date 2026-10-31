"""Изменения справочника объектов (по правилам проекта все записи идут через services.py)."""
from .models import Site


def get_or_create_site(name):
    """
    Найти объект по названию или создать новый. Возвращает пару (Site, создан ли).

    Лишние пробелы убираем, регистр не важен («лемон гарден» найдёт «Лемон Гарден»):
    так опечатка в регистре не плодит дубли объектов.
    """
    name = " ".join(name.split())
    if not name:
        raise ValueError("Пустое название объекта.")
    site = Site.objects.filter(name__iexact=name).first()
    if site:
        return site, False
    return Site.objects.create(name=name), True

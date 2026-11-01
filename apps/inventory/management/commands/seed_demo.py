"""
Загрузка тестовых данных: 25 электроинструментов и 20 единиц высотного снаряжения (штучно), 25 ручных и 10 видов снаряжения (количеством) и 5 объектов.

Запуск:
    python manage.py seed_demo               # от имени первого суперпользователя
    python manage.py seed_demo --user ivan   # от имени пользователя ivan
    python manage.py seed_demo --seed 1      # те же случайные количества при каждом запуске

Данные заводятся через services.py, как и в рабочем режиме, поэтому в журнале
у каждой позиции есть запись «поставлен на баланс» и счётчики сходятся с журналом.
Повторный запуск ничего не дублирует: позиции и объекты, которые уже есть в базе (по названию), пропускаются.
"""
import random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.inventory import services
from apps.inventory.models import Category, HandTool, Tool
from apps.sites import services as site_services

ELECTRO_CATEGORY = "Электроинструмент"
HAND_CATEGORY = "Ручной инструмент"
GEAR_CATEGORY = "Высотное снаряжение"

ELECTRO_TOOLS = [
    "Дрель-шуруповёрт аккумуляторная",
    "Дрель сетевая",
    "Перфоратор SDS-plus",
    "Перфоратор SDS-max",
    "Отбойный молоток",
    "Болгарка 125 мм",
    "Болгарка 230 мм",
    "Циркулярная пила",
    "Сабельная пила",
    "Электролобзик",
    "Торцовочная пила",
    "Ленточная шлифмашина",
    "Эксцентриковая шлифмашина",
    "Рубанок электрический",
    "Фрезер",
    "Штроборез",
    "Гайковёрт ударный",
    "Строительный фен",
    "Мойка высокого давления",
    "Лазерный нивелир",
    "Строительный пылесос",
    "Дрель-миксер",
    "Краскопульт электрический",
    "Плиткорез электрический",
    "Лазерный дальномер",
]

HAND_TOOLS = [
    "Молоток слесарный",
    "Кувалда 5 кг",
    "Отвёртка плоская",
    "Отвёртка крестовая",
    "Набор бит",
    "Ключ разводной",
    "Набор рожковых ключей",
    "Набор торцевых головок",
    "Пассатижи",
    "Плоскогубцы",
    "Кусачки боковые",
    "Нож строительный",
    "Ножовка по металлу",
    "Ножовка по дереву",
    "Рулетка 5 м",
    "Уровень строительный 1 м",
    "Шпатель",
    "Монтировка",
    "Зубило",
    "Струбцина",
    "Лом",
    "Лопата штыковая",
    "Топор",
    "Угольник",
    "Киянка резиновая",
]

# Высотное снаряжение: дорогое и с учётом по номеру (штучно) и расходное количеством.
GEAR_TOOLS = (
    [f"Обвязка страховочная №{n}" for n in range(1, 6)]
    + [f"Спусковое устройство «Рига» №{n}" for n in range(1, 4)]
    + [f"Подъёмное устройство (жумар) №{n}" for n in range(1, 4)]
    + [f"Верёвка рабочая 50 м №{n}" for n in range(1, 4)]
    + [f"Верёвка страховочная 50 м №{n}" for n in range(1, 3)]
    + [f"Блок-ролик №{n}" for n in range(1, 3)]
    + ["Рабочая платформа (люлька) №1", "Анкерная линия временная №1"]
)

GEAR_HAND_TOOLS = [
    "Карабин стальной муфтованный",
    "Карабин алюминиевый",
    "Строп страховочный с амортизатором",
    "Усы удерживающие",
    "Каска с подбородочным ремнём",
    "Перчатки для высотных работ",
    "Петля прусика 6 мм",
    "Лента текстильная (петля) 120 см",
    "Соединительное звено (маллон)",
    "Мешок для снаряжения",
]

SITES = ["Лемон Гарден", "Центрополис", "Такаишвили", "Зелёный дом", "Шартава 7"]

MIN_QUANTITY, MAX_QUANTITY = 5, 15


class Command(BaseCommand):
    help = "Загрузить тестовые данные: 45 штучных (25 электро и 20 снаряжения), 35 ручных (5-15 шт.) и 5 объектов."

    def add_arguments(self, parser):
        parser.add_argument("--user", help="логин того, кто «вносит» данные (по умолчанию первый суперпользователь)")
        parser.add_argument("--seed", type=int, help="число для воспроизводимых случайных количеств")

    def handle(self, *args, user=None, seed=None, **options):
        author = self._author(user)
        rng = random.Random(seed)  # свой генератор: не трогает глобальный random

        with transaction.atomic():
            categories = {
                name: Category.objects.get_or_create(name=name)[0]
                for name in (ELECTRO_CATEGORY, HAND_CATEGORY, GEAR_CATEGORY)
            }
            tools = [(n, ELECTRO_CATEGORY) for n in ELECTRO_TOOLS] + [(n, GEAR_CATEGORY) for n in GEAR_TOOLS]
            hand_tools = [(n, HAND_CATEGORY) for n in HAND_TOOLS] + [(n, GEAR_CATEGORY) for n in GEAR_HAND_TOOLS]

            new_tools = 0
            for name, category_name in tools:
                if Tool.objects.filter(name=name).exists():      # уже есть (по названию): пропускаем
                    continue
                services.register_tool(user=author, name=name, category=categories[category_name])
                new_tools += 1

            new_hand = 0
            for name, category_name in hand_tools:
                # Позиция создаётся с нулём, количество добавляет только service (приход).
                hand_tool, created = HandTool.objects.get_or_create(
                    name=name, defaults={"category": categories[category_name]},
                )
                if not created:
                    continue
                quantity = rng.randint(MIN_QUANTITY, MAX_QUANTITY)
                services.add_hand_tool_stock(user=author, hand_tool=hand_tool, quantity=quantity)
                new_hand += 1

            new_sites = sum(site_services.get_or_create_site(name)[1] for name in SITES)

        self.stdout.write(self.style.SUCCESS(
            f"Готово: штучных добавлено {new_tools} из {len(tools)}, "
            f"ручных добавлено {new_hand} из {len(hand_tools)}, "
            f"объектов добавлено {new_sites} из {len(SITES)} (остальные уже были)."
        ))

    def _author(self, username):
        users = get_user_model().objects
        if username:
            try:
                return users.get(username=username)
            except users.model.DoesNotExist:
                raise CommandError(f"Пользователь «{username}» не найден.")
        author = users.filter(is_superuser=True).order_by("pk").first()
        if author is None:
            raise CommandError("Нет ни одного суперпользователя: сначала python manage.py createsuperuser.")
        return author

"""
Загрузка тестовых данных: 25 электроинструментов (штучно) и 25 ручных (количеством).

Запуск:
    python manage.py seed_demo               # от имени первого суперпользователя
    python manage.py seed_demo --user ivan   # от имени пользователя ivan
    python manage.py seed_demo --seed 1      # те же случайные количества при каждом запуске

Данные заводятся через services.py, как и в рабочем режиме, поэтому в журнале
у каждой позиции есть запись «поставлен на баланс» и счётчики сходятся с журналом.
Повторный запуск ничего не дублирует: уже существующие позиции пропускаются.
"""
import random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.inventory import services
from apps.inventory.models import Category, HandTool, Tool

ELECTRO_CATEGORY = "Электроинструмент"
HAND_CATEGORY = "Ручной инструмент"

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

MIN_QUANTITY, MAX_QUANTITY = 5, 15


class Command(BaseCommand):
    help = "Загрузить тестовые данные: 25 электроинструментов и 25 ручных (5-15 шт.)."

    def add_arguments(self, parser):
        parser.add_argument("--user", help="логин того, кто «вносит» данные (по умолчанию первый суперпользователь)")
        parser.add_argument("--seed", type=int, help="число для воспроизводимых случайных количеств")

    def handle(self, *args, user=None, seed=None, **options):
        author = self._author(user)
        rng = random.Random(seed)  # свой генератор: не трогает глобальный random

        with transaction.atomic():
            electro_category, _ = Category.objects.get_or_create(name=ELECTRO_CATEGORY)
            hand_category, _ = Category.objects.get_or_create(name=HAND_CATEGORY)

            new_tools = 0
            for name in ELECTRO_TOOLS:
                if Tool.objects.filter(name=name).exists():
                    continue
                services.register_tool(user=author, name=name, category=electro_category)
                new_tools += 1

            new_hand = 0
            for name in HAND_TOOLS:
                # Позиция создаётся с нулём, количество добавляет только service (приход).
                hand_tool, created = HandTool.objects.get_or_create(
                    name=name, defaults={"category": hand_category},
                )
                if not created:
                    continue
                quantity = rng.randint(MIN_QUANTITY, MAX_QUANTITY)
                services.add_hand_tool_stock(user=author, hand_tool=hand_tool, quantity=quantity)
                new_hand += 1

        self.stdout.write(self.style.SUCCESS(
            f"Готово: штучных добавлено {new_tools} из {len(ELECTRO_TOOLS)}, "
            f"ручных добавлено {new_hand} из {len(HAND_TOOLS)} (остальные уже были)."
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

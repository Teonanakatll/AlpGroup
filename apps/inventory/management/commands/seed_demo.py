"""
Загрузка тестовых данных: 25 электроинструментов и 20 единиц высотного снаряжения (штучно), 25 ручных и 10 видов снаряжения (количеством) и 5 объектов.

Запуск:
    python manage.py seed_demo               # от имени первого суперпользователя
    python manage.py seed_demo --user ivan   # от имени пользователя ivan
    python manage.py seed_demo --seed 1      # те же случайные количества при каждом запуске
    python manage.py seed_demo --journal     # плюс «живой журнал»: 15 операций вперемешку (см. ниже)

Данные заводятся через services.py, как и в рабочем режиме, поэтому в журнале
у каждой позиции есть запись «поставлен на баланс» и счётчики сходятся с журналом.
Повторный запуск ничего не дублирует: позиции и объекты, которые уже есть в базе (по названию), пропускаются.

--journal: после справочников ещё 15 операций в случайном порядке — 5 выдач на разные объекты
(по 8-12 позиций, инструмент и снаряжение), 3 приёма, 3 списания и 4 отправки в ремонт.
Позиции берутся из текущего состояния базы и проводятся через те же services.py, что и сайт,
поэтому правила учёта соблюдаются и на базе, где уже есть свои выдачи и ремонты. Операция,
для которой сейчас нечего взять (например, приём, пока ничего не выдано), ждёт своей очереди
до конца; если взять так и нечего — пропускается с сообщением. Каждый запуск с --journal
дописывает новый круг операций (журнал «продолжается»), справочники при этом не дублируются.
"""
import random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.inventory import selectors, services
from apps.inventory.models import Category, HandTool, Tool
from apps.sites import services as site_services
from apps.sites.models import Site

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

# «Живой журнал» (--journal): сколько операций каждого вида и размер выдачи
JOURNAL_PLAN = {"issue": 5, "receive": 3, "write_off": 3, "servicing": 4}
ISSUE_MIN, ISSUE_MAX = 8, 12

# Кто взял / кто привёз (текст taken_by, как в форме)
PEOPLE = ["Гиорги Беридзе", "Леван Цулая", "Нино Абашидзе", "Давит Кацитадзе", "Сергей Орлов", "Иван Петренко"]
WRITE_OFF_NOTES = ["Износ, ремонт нецелесообразен", "Разбит при падении", "Трещина корпуса", "Истёк срок службы"]
SERVICING_NOTES = ["Не держит обороты", "Искрит щётками", "Заедает механизм", "Плановое обслуживание", "Перетёрт кабель"]


class Command(BaseCommand):
    help = "Загрузить тестовые данные: 45 штучных (25 электро и 20 снаряжения), 35 ручных (5-15 шт.) и 5 объектов."

    def add_arguments(self, parser):
        parser.add_argument("--user", help="логин того, кто «вносит» данные (по умолчанию первый суперпользователь)")
        parser.add_argument("--seed", type=int, help="число для воспроизводимых случайных количеств")
        parser.add_argument("--journal", action="store_true",
                            help="добавить 15 операций вперемешку: 5 выдач, 3 приёма, 3 списания, 4 ремонта")

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

            journal = JournalSimulator(author, rng, self.stdout).run() if options["journal"] else None

        self.stdout.write(self.style.SUCCESS(
            f"Готово: штучных добавлено {new_tools} из {len(tools)}, "
            f"ручных добавлено {new_hand} из {len(hand_tools)}, "
            f"объектов добавлено {new_sites} из {len(SITES)} (остальные уже были)."
        ))
        if journal is not None:
            done = ", ".join(f"{JOURNAL_LABELS[kind]} {count}" for kind, count in journal.items())
            self.stdout.write(self.style.SUCCESS(f"Журнал: {done}."))

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


# ---------------------------------------------------------------------------
# «Живой журнал» (--journal)
# ---------------------------------------------------------------------------

JOURNAL_LABELS = {"issue": "выдач", "receive": "приёмов", "write_off": "списаний", "servicing": "ремонтов"}


class JournalSimulator:
    """
    Проводит операции из JOURNAL_PLAN в случайном порядке через services.py.

    Перед каждой операцией смотрит текущее состояние (selectors), выбирает подходящие позиции
    и вызывает тот же service, что и форма на сайте. Если сейчас нечего взять (например, приём
    до первой выдачи), операция откладывается и пробуется позже; в конце — пропускается.
    """

    def __init__(self, author, rng, stdout):
        self.author, self.rng, self.stdout = author, rng, stdout
        self.sites = list(Site.objects.order_by("name"))
        self.free_sites = []          # объекты для выдач: по очереди, чтобы 5 выдач ушли на разные

    def run(self):
        queue = [kind for kind, count in JOURNAL_PLAN.items() for _ in range(count)]
        self.rng.shuffle(queue)
        done = {kind: 0 for kind in JOURNAL_PLAN}
        while queue:
            for kind in queue:                     # первая операция из очереди, которую можно провести
                if self._run(kind):
                    queue.remove(kind)
                    done[kind] += 1
                    break
            else:                                   # ни одну из оставшихся провести нельзя
                for kind in queue:
                    self.stdout.write(f"Пропущено ({JOURNAL_LABELS[kind]}): нечего взять в текущей базе.")
                break
        return done

    def _run(self, kind):
        """Провести одну операцию. False — сейчас нечего взять (состояние базы не изменилось)."""
        try:
            with transaction.atomic():              # при отказе service ничего не остаётся
                return getattr(self, f"_{kind}")()
        except services.ServiceError as error:      # не должно случаться: позиции выбраны по правилам
            self.stdout.write(f"Отклонено ({JOURNAL_LABELS[kind]}): {' '.join(str(error).splitlines())}")
            return False

    # --- операции -------------------------------------------------------------

    def _issue(self):
        if not self.sites:
            return False
        if not self.free_sites:
            self.free_sites = self.rng.sample(self.sites, len(self.sites))
        site = self.free_sites.pop()

        tools = list(selectors.available_tools())
        hands = list(selectors.available_hand_tools())
        size = self.rng.randint(ISSUE_MIN, ISSUE_MAX)
        n_tools = min(len(tools), self.rng.randint(size // 3, size * 2 // 3))   # примерно поровну
        n_hands = min(len(hands), size - n_tools)
        if n_tools + n_hands == 0:
            return False
        picked_tools = self.rng.sample(tools, n_tools)
        picked_hands = [(h, self.rng.randint(1, min(h.available, 4))) for h in self.rng.sample(hands, n_hands)]
        services.issue_to_site(
            user=self.author, site=site, tools=picked_tools, hand_tools=picked_hands,
            taken_by=self.rng.choice(PEOPLE),
        )
        return True

    def _receive(self):
        sites = list(selectors.sites_with_items())
        if not sites:
            return False
        site = self.rng.choice(sites)
        tools = list(selectors.tools_on_site(site))
        hands = selectors.hand_tools_on_site(site)
        # Возвращают часть: от трети до всего, что там числится
        tools = self.rng.sample(tools, self.rng.randint(min(1, len(tools)), len(tools))) if tools else []
        hands = [(h, self.rng.randint(1, qty)) for h, qty in hands if self.rng.random() < 0.6]
        if not tools and not hands:
            return False
        services.receive_from_site(
            user=self.author, site=site, tools=tools, hand_tools=hands, taken_by=self.rng.choice(PEOPLE),
        )
        return True

    def _write_off(self):
        """Со склада (сломанное, старое) или с объекта; если в выбранном месте пусто — из другого."""
        note = self.rng.choice(WRITE_OFF_NOTES)
        options = []
        on_site = list(Tool.objects.filter(status=Tool.Status.ISSUED, current_site__isnull=False))
        if on_site:
            tool = self.rng.choice(on_site)
            options.append(lambda: services.write_off(user=self.author, site=tool.current_site, tools=[tool], note=note))
        warehouse = list(selectors.tools_for_write_off())
        if warehouse:
            tool_w = self.rng.choice(warehouse)
            options.append(lambda: services.write_off(user=self.author, tools=[tool_w], note=note))
        hands = list(selectors.available_hand_tools())
        if hands:
            hand = self.rng.choice(hands)
            options.append(lambda: services.write_off(user=self.author, hand_tools=[(hand, 1)], note=note))
        return self._one_of(options)

    def _servicing(self):
        """1-2 штучных со склада или одна с объекта; если в выбранном месте пусто — из другого."""
        note = self.rng.choice(SERVICING_NOTES)
        options = []
        on_site = list(Tool.objects.filter(status=Tool.Status.ISSUED, current_site__isnull=False))
        if on_site:
            tool = self.rng.choice(on_site)
            options.append(lambda: services.send_to_servicing(
                user=self.author, site=tool.current_site, tools=[tool], taken_by=self.rng.choice(PEOPLE), note=note,
            ))
        warehouse = list(selectors.available_tools())
        if warehouse:
            picked = self.rng.sample(warehouse, min(len(warehouse), self.rng.randint(1, 2)))
            options.append(lambda: services.send_to_servicing(user=self.author, tools=picked, note=note))
        return self._one_of(options)

    def _one_of(self, options):
        """Провести один из возможных вариантов (выбор случайный). False — вариантов нет."""
        if not options:
            return False
        self.rng.choice(options)()
        return True

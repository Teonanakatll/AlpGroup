# AlpGroup: контекст проекта для Claude

Складской учёт инструмента и снаряжения, выдача на объекты.
Требования: docs/SPEC.md. Принятые решения и причины: docs/DECISIONS.md.
Владелец проекта давно не писал код (хочет вспомнить Django и DRF): объясняй решения коротко, код давай читаемый, сложные места поясняй.

## Стек
Python 3.12, Django, Django REST Framework. PostgreSQL (настройки в .env). Позже: адаптивный сайт, Telegram-бот только для оповещений.

## Структура
- config/ — настройки и urls
- apps/inventory/ — Category, Tool, ToolPhoto, HandTool, BaseMovement (abstract), ToolMovement, HandToolMovement
- apps/sites/ — Site, WorkType (минимальный справочник)
- в каждом приложении services.py (изменения), selectors.py (выборки), tests/

## Ключевые правила (подробности в DECISIONS.md)
- Журналы только дописываются. Источник истины журнал; статус и счётчики в моделях кэш.
- Состояние меняется только в services.py, в одной транзакции с записью в журнал (atomic + select_for_update). Поля статусов и счётчиков в админке только для чтения.
- Отмена: is_cancelled, затем пересчёт состояния из журнала.
- Два вида учёта: Tool (штучно, дорогое), HandTool (количеством, дешёвое).
- Выдача набора: общий UUID batch у строк журнала.
- Вьюхи DRF тонкие, логика только в services.py и selectors.py.
- Статусы и типы операций через TextChoices.
- Секреты через .env, в репозитории .env.example. Не коммитить .venv, .env, db.sqlite3, media/, .idea/, __pycache__/.
- Тесты на services и selectors (pytest-django). Коммиты: одна мысль, префикс feat/fix/refactor/docs/test/chore.

## Как запускать
1. Создать venv и активировать его, затем `pip install -r requirements.txt`.
2. Создать `.env` по образцу `.env.example` (параметры PostgreSQL).
3. `python manage.py migrate`, `python manage.py createsuperuser`.
4. `python manage.py runserver`.
5. Тесты: `pytest`.

## Текущее состояние
Сделано:
- [x] каркас Django, rest_framework подключён
- [x] модели: Category, Tool, ToolPhoto, HandTool, журналы (batch, current_site)
- [x] приложение sites (Site, WorkType)
- [x] админка: статусы и счётчики только для чтения
- [x] requirements.txt, .env, язык ru, часовой пояс Europe/Moscow
- [x] PostgreSQL

План (по порядку):
- [x] settings: MEDIA_URL и MEDIA_ROOT
- [x] services.py, общий каркас: пересчёт состояния из журнала (atomic, select_for_update), тесты
- [x] постановка на баланс (added): Tool +1, HandTool +N к total
- [x] выдача набора на объект: один новый batch на операцию, проверки
- [x] приём (returned): с объекта и из ремонта (без объекта)
- [x] не найден (missing), списание (written_off), ремонт (servicing) по DECISIONS, раздел 14
- [x] отмена записи или набора (только последняя операция по позиции, набор всё или ничего)
- [ ] selectors.py с тестами (доступно к выдаче, числится на объекте, история, выдано за период)
- [ ] админка: закрыть total и журналы, admin action для выдачи и приёма
- [ ] DRF-эндпоинты, затем формы выдачи и приёма, фронтенд
- [ ] права, отчёты и бэкапы, оповещения

## Открытые вопросы
См. раздел 9 в docs/SPEC.md.
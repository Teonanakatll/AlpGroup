# AlpGroup: контекст проекта для Claude

Складской учёт инструмента и снаряжения, выдача на объекты.
Требования: docs/SPEC.md. Принятые решения и причины: docs/DECISIONS.md.
Владелец проекта давно не писал код (хочет вспомнить Django и DRF): объясняй решения коротко, код давай читаемый, сложные места поясняй.

## Стек
Python 3.12, Django, Django REST Framework. Сейчас SQLite, переход на PostgreSQL запланирован до services.py. Позже: адаптивный сайт, Telegram-бот только для оповещений.

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
(заполнить: venv, pip install -r requirements.txt, migrate, runserver, pytest)

## Текущее состояние
- [x] каркас Django, приложение apps.inventory, rest_framework подключён
- [ ] requirements.txt
- [ ] settings: язык ru, часовой пояс Europe/Moscow, MEDIA, .env
- [ ] модели: Category, Tool, ToolPhoto, HandTool, журналы
- [ ] приложение sites (Site, WorkType)
- [ ] админка (статусы и счётчики только для чтения)
- [ ] PostgreSQL
- [ ] services.py и selectors.py с тестами
- [ ] DRF-эндпоинты: доступно к выдаче, числится на объекте, выдать, принять
- [ ] формы выдачи и приёма, фронтенд
- [ ] txt-загрузка, права, отчёты и бэкапы, оповещения

## Открытые вопросы
См. раздел 9 в docs/SPEC.md.
# Деплой на сервер (DigitalOcean + Docker)

Три контейнера: **db** (PostgreSQL), **web** (Django + gunicorn), **caddy** (HTTPS, статика, фото).
Сертификат Caddy получает и продлевает сам.

## 0. Что понадобится
- Аккаунт DigitalOcean. Если карта российская и не проходит, подойдёт любой хостер с обычным Ubuntu-сервером (Hetzner, Timeweb, Selectel, Beget), дальше всё то же самое.
- Домен **или** бесплатный адрес по IP: `203-0-113-10.sslip.io` (IP через дефисы + `.sslip.io`), для него Caddy тоже выпускает настоящий сертификат.

## 1. Сервер
1. Create → Droplets → Ubuntu 24.04 LTS, Basic, **2 ГБ RAM** (1 ГБ тесно для базы и Django). Регион ближе к пользователям (Frankfurt/Amsterdam). Авторизация: SSH-ключ.
2. Если есть домен: A-запись `alp.example.com` → IP сервера.
3. Подключитесь `ssh root@IP` и выполните:
   ```bash
   curl -fsSL https://get.docker.com | sh        # Docker и compose
   ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
   ```

## 2. Приложение
```bash
git clone https://github.com/Teonanakatll/AlpGroup.git alpgroup && cd alpgroup
git checkout claude/deploy        # пока ветка не влита в main
cp .env.example .env && nano .env
```
В `.env` для сервера заполните: `DB_NAME`, `DB_USER`, `DB_PASSWORD` (свой, длинный), `SECRET_KEY`
(`python3 -c "import secrets; print(secrets.token_urlsafe(50))"`), `DOMAIN`. `DB_HOST` и `DEBUG` compose выставляет сам.

```bash
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py seed_demo      # тестовые данные, только для тестового стенда
```
Откройте `https://ВАШ_ДОМЕН`. Первый запуск занимает 1–2 минуты: Caddy выпускает сертификат.

Полезное: `docker compose logs -f web` (логи), `docker compose ps` (состояние).

## 3. Обновление
```bash
cd alpgroup && git pull && docker compose up -d --build
```
Миграции и сбор статики выполняются при каждом старте автоматически.

## 4. Бэкапы
Дамп базы в `backups/`, копии старше 14 дней удаляются:
```bash
sh scripts/backup.sh
```
По расписанию (каждую ночь в 3:00): `crontab -e`, строка
`0 3 * * * cd /root/alpgroup && sh scripts/backup.sh >> backups/backup.log 2>&1`
Хранить копии только на этом же сервере мало: периодически скачивайте их к себе
(`scp root@IP:alpgroup/backups/*.gz .`) или включите «Backups» у дроплета в панели DigitalOcean.
Восстановление описано в начале `scripts/backup.sh`. Фото инструмента лежат в томе `media`, копируйте и их.

## 5. Тестовый и боевой стенды
Журналы только дописываются, ошибки тестирования остаются в истории навсегда. Поэтому:
- сначала **тестовый** сервер (с `seed_demo` и тестовыми пользователями, можно ломать);
- **боевой** поднимайте отдельно, с чистой базой и без `seed_demo`.

## 6. Если что-то не работает
- Сертификат не выпускается: домен должен указывать на IP сервера, порты 80 и 443 открыты (`ufw status`).
- Ошибка CSRF при входе: проверьте `DOMAIN` и `HTTPS` в `.env`, после правки `docker compose up -d`.
- Нет стилей или фото: `docker compose logs caddy web`; статика собирается при старте `web`.
- Работа по IP без домена и без sslip.io: `DOMAIN=:80`, `HTTPS=0` (только http, пароли идут открыто, только для проверки).

## Быстрый показ без сервера (Cloudflare Tunnel)
Сайт работает на вашем компьютере (`runserver`), `cloudflared` даёт ему временный адрес
`https://что-то.trycloudflare.com`. Аккаунт Cloudflare не нужен. Работает, пока включён компьютер
и открыты оба окна; адрес меняется при каждом запуске.

### Почему не просто `runserver` с обычным `.env`
- При `DEBUG=1` любой посетитель на ошибке видит страницу с трейсбеком и настройками, а ключ
  сессий запасной, из репозитория. Наружу показываем только с `DEBUG=0` и своим `SECRET_KEY`.
- При `DEBUG=0` Django сам не отдаёт стили и фото (на сервере это делает Caddy).
  Флаг `SERVE_FILES=1` включает раздачу через Django: для показа хватает, на сервере не нужен.
- Прав пока нет: любой вошедший может выдавать и списывать, а журнал только дописывается.
  Поэтому показ на **отдельной базе** (`alpgroup_demo`), рабочая остаётся чистой.

### Один раз
1. Установить cloudflared (PowerShell): `winget install --id Cloudflare.cloudflared`, затем открыть новое окно терминала.
2. Создать базу для показа (psql или pgAdmin, от суперпользователя PostgreSQL):
   `CREATE DATABASE alpgroup_demo OWNER alpgroup;`
3. Сгенерировать ключ: `python -c "import secrets; print(secrets.token_urlsafe(50))"`.
4. Переключить `.env` на показ (старые строки можно закомментировать `#`, вернуть позже):
   ```
   DB_NAME=alpgroup_demo
   DEBUG=0
   SECRET_KEY=сгенерированный_ключ
   SERVE_FILES=1
   ALLOWED_HOSTS=localhost,127.0.0.1,.trycloudflare.com
   CSRF_TRUSTED_ORIGINS=https://*.trycloudflare.com
   ```
   `HTTPS` оставьте `1`: cloudflared отдаёт сайт по https и сообщает Django об этом в заголовке.
5. Подготовить базу:
   ```
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py seed_demo
   ```
6. Завести логины для гостей: `/admin/` → Пользователи → Добавить (по одному на человека,
   чтобы в журнале было видно, кто что делал).

### Каждый показ
Два окна терминала в папке проекта (venv активирован):
```
python manage.py runserver 8000
```
```
cloudflared tunnel --url http://localhost:8000
```
Во втором окне появится адрес `https://….trycloudflare.com`: его и отправляйте.
Остановить: Ctrl+C в обоих окнах.

### После показа
Верните в `.env` рабочие `DB_NAME` и уберите строку `DEBUG=0` (или `DEBUG=1`), иначе при обычной
разработке не будет страниц с ошибками. Демо-базу можно удалить: `DROP DATABASE alpgroup_demo;`.

### Если что-то не так
- 400 Bad Request: адреса нет в `ALLOWED_HOSTS` (проверьте `.trycloudflare.com` с точкой в начале).
- 403 CSRF при входе: нет или опечатка в `CSRF_TRUSTED_ORIGINS`.
- Страницы без стилей и фото: не включён `SERVE_FILES=1`.
- Ошибка 500 без подробностей: так и задумано при `DEBUG=0`, трейсбек смотрите в окне `runserver`.

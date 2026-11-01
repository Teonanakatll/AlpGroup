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

## Быстрый показ без сервера
Cloudflare Tunnel: `cloudflared tunnel --url http://localhost:8000` (запущен `runserver`).
В `.env` добавьте `ALLOWED_HOSTS=.trycloudflare.com` и `CSRF_TRUSTED_ORIGINS=https://*.trycloudflare.com`.
Работает, пока включён ваш компьютер; адрес меняется при каждом запуске.

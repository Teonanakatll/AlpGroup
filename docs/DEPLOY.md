# Деплой на сервер (Docker Compose)

Три контейнера: **db** (PostgreSQL), **web** (Django + gunicorn), **caddy** (HTTPS, статика, фото).
Сертификат Caddy получает и продлевает сам.

**Пошагово с нуля (Hetzner, команды с Windows): [SERVER.md](SERVER.md).** Ниже коротко, для любого
хостера с Ubuntu-сервером.

## 1. Сервер
- Ubuntu 24.04, от **2 ГБ RAM** (1 ГБ тесно для базы и Django), вход по SSH-ключу.
- Адрес: свой домен (A-запись на IP сервера) **или** бесплатный `203-0-113-10.sslip.io`
  (IP через дефисы + `.sslip.io`), для него Caddy тоже выпускает настоящий сертификат.
- Docker, firewall и swap:
  ```bash
  curl -fsSL https://get.docker.com | sh
  ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  ```

## 2. Приложение
```bash
git clone https://github.com/Teonanakatll/AlpGroup.git alpgroup && cd alpgroup
```
`.env` для сервера: `DB_NAME`, `DB_USER`, `DB_PASSWORD` (длинный), `SECRET_KEY`, `DOMAIN`, `HTTPS=1`.
`DB_HOST` и `DEBUG` compose выставляет сам. Команда, которая создаёт `.env` с готовыми паролем и ключом,
есть в [SERVER.md](SERVER.md), шаг 5.

```bash
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py seed_demo      # тестовые данные, только для тестового стенда
```
Откройте `https://ВАШ_ДОМЕН`. Первый запуск занимает 1–2 минуты: Caddy выпускает сертификат.

Полезное: `docker compose logs -f web` (логи), `docker compose ps` (состояние).

## 3. Обновление
```bash
cd ~/alpgroup && git pull && docker compose up -d --build
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
(`scp root@IP:alpgroup/backups/*.gz .`) или включите бэкапы сервера в панели хостера.
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

### Один раз
Скачать cloudflared: это один файл, установка не нужна. В командной строке (cmd):
```
curl -L -o %USERPROFILE%\Downloads\cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
```
Если `curl` не найден, откройте эту ссылку в браузере и переименуйте скачанный файл в `cloudflared.exe`
(в папке «Загрузки»). Класть его в папку проекта не стоит: попадёт в `git status`.
Если на компьютере есть winget, можно и так: `winget install --id Cloudflare.cloudflared`, тогда
дальше вместо полного пути просто `cloudflared`.

### Каждый показ
1. Добавить в `.env`:
   ```
   TUNNEL=1
   DEMO_USER=гость
   ```
   `TUNNEL=1` выключает DEBUG (посетители не видят трейсбеков), сам генерирует ключ, раздаёт стили
   и фото без Caddy и разрешает адреса `trycloudflare.com`. `DEMO_USER` пускает без пароля, все
   работают под пользователем «гость» (создаётся сам, без доступа в админку). Если нужно видеть,
   кто что делал, уберите `DEMO_USER` и заведите логины в `/admin/` → Пользователи.
2. Два окна терминала в папке проекта (venv активирован):
   ```
   python manage.py runserver 8000
   ```
   ```
   %USERPROFILE%\Downloads\cloudflared.exe tunnel --url http://localhost:8000
   ```
   Это одна команда, из любой папки (в cmd; в PowerShell вместо `%USERPROFILE%` пишется `$env:USERPROFILE`). Во втором окне через несколько секунд появится рамка с адресом `https://….trycloudflare.com`: его и отправляйте, только своим
   (с `DEMO_USER` сайт открыт всем, у кого есть ссылка). Сами входите под своим логином через `/login/`.
3. После показа: Ctrl+C в обоих окнах и удалить (или закомментировать `#`) две строки из `.env`.

Показ идёт на той же базе, что и разработка: всё, что нащёлкают гости, останется в журнале
(журнал только дописывается). Для тестовой базы это нормально.

### Если что-то не так
- 400 Bad Request или 403 CSRF: в `.env` нет `TUNNEL=1` (или опечатка).
- Ошибка 500 без подробностей: так и задумано, трейсбек виден в окне `runserver`.
- После перезапуска `runserver` всех выкинуло на вход: ключ генерируется при каждом запуске, это нормально.

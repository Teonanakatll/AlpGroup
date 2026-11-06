# Тестовый сервер с нуля: Hetzner, пошагово с Windows

Так поднят тестовый стенд https://alpgroup.ezolab.dev: Hetzner Cloud CX23 (Helsinki), Ubuntu 24.04.
Сначала он работал по бесплатному адресу sslip.io, потом подключён домен (шаг 6, «Свой домен»).
Общая схема (три контейнера, бэкапы, обновление) описана в [DEPLOY.md](DEPLOY.md).

Команды с пометкой **(cmd)** выполняются на своём компьютере в командной строке Windows,
с пометкой **(сервер)** уже на сервере, после подключения по SSH.

## 1. Хостинг
- **Hetzner Cloud**, тариф **CX23**: 2 vCPU, 4 ГБ RAM, 40 ГБ. €5,49 + €0,50 за IPv4 = €5,99 в месяц без НДС
  (для клиентов вне ЕС НДС нет). Ссылки: тарифы https://www.hetzner.com/cloud,
  панель https://console.hetzner.com, аккаунт и счета https://accounts.hetzner.com.
- Оплата почасовая с месячным потолком. Счёт за прошлый месяц выставляется в начале следующего
  и списывается с карты сам. **Выключенный сервер тоже оплачивается**, списания прекращает только удаление.
- Регистрация: реальные данные латиницей, адрес проживания, карта на своё имя, **без VPN**.
  При проверке личности выбирается страна, выдавшая документ, и загранпаспорт (Passport).
  Пока аккаунт на проверке, создать сервер нельзя («попробуйте позже»); вопросы по проверке:
  cda-review@hetzner.com.
- Запасные варианты, если Hetzner не одобрит: DigitalOcean (Droplet Basic, 2 ГБ, $12), netcup.

## 2. SSH-ключ (cmd, один раз)
Ключ нужен, чтобы входить на сервер без пароля. Сначала проверьте, нет ли его уже:
```
type %USERPROFILE%\.ssh\id_ed25519.pub
```
Если файла нет, создайте (на все вопросы Enter):
```
ssh-keygen -t ed25519 -C "alpgroup"
```
Если спросит `Overwrite (y/n)?`, отвечайте **n**: ключ уже есть, перезапись сломает доступ туда, где он добавлен.

Скопировать публичный ключ в буфер обмена:
```
type %USERPROFILE%\.ssh\id_ed25519.pub | clip
```
Вставляется одна строка `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5... alpgroup`. Файл `id_ed25519` без `.pub`
секретный, его никуда не вставлять.

## 3. Создание сервера (панель Hetzner)
Servers → Add Server:
- Type: Shared Resources → Cost-Optimized → **CX23** (x86). Если нет в наличии: другая локация или CAX11 (ARM).
- Location: Helsinki, Falkenstein или Nuremberg.
- Image: **Ubuntu 24.04**.
- Networking: IPv4 и IPv6 (без IPv4 часть посетителей сайт не откроет).
- SSH keys: Add SSH key, вставить строку из шага 2. Имя ключа любое, например `home-pc`.
- Volumes, Firewalls, Backups: не нужны (порты закрывает ufw, базу бэкапит scripts/backup.sh).
- Имя сервера, например `alp-test` → **Create & Buy now**. IP будет в списке серверов.

## 4. Подготовка сервера
Подключиться **(cmd)**, при первом входе ответить `yes`:
```
ssh root@IP_СЕРВЕРА
```
Вставка в окне терминала: **правая кнопка мыши** (Ctrl+V может вставить мусор).

**(сервер)** обновления, Docker, firewall и swap на 2 ГБ (без swap сборка образа может упереться в память):
```bash
apt update && apt -y upgrade
curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```
Если `upgrade` покажет окно с вопросом о конфигурации, Enter.

## 5. Приложение
**(сервер)**
```bash
git clone https://github.com/Teonanakatll/AlpGroup.git alpgroup && cd alpgroup
```
`.env` одной командой, пароль базы и ключ генерируются сами (nano не нужен).
В `DOMAIN` IP через дефисы + `.sslip.io`, например `135-181-195-12.sslip.io`:
```bash
cat > .env <<EOF
DB_NAME=alpgroup
DB_USER=alpgroup
DB_PASSWORD=$(openssl rand -hex 24)
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')
DOMAIN=IP-ЧЕРЕЗ-ДЕФИСЫ.sslip.io
HTTPS=1
EOF
```
- Содержимое `.env` никому не показывать: это пароли.
- Перегенерировать пароль базы можно только **до** первого запуска: потом PostgreSQL помнит старый.

Запуск (первая сборка 3–5 минут), админ и тестовые данные:
```bash
docker compose up -d --build
docker compose ps                     # у db, web, caddy STATUS = Up
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py seed_demo
```
Сайт: `https://IP-ЧЕРЕЗ-ДЕФИСЫ.sslip.io`. Сертификат Let's Encrypt Caddy получает сам за 1–2 минуты
после первого запуска и сам продлевает; http перенаправляется на https. По голому IP сайт не открывается.

## 6. Дальше
- **Обновление** после мержа в main **(сервер)**:
  `cd ~/alpgroup && git pull && docker compose up -d --build`
- **Бэкапы**: [DEPLOY.md](DEPLOY.md), раздел 4. Скачать к себе **(cmd)**:
  `scp root@IP_СЕРВЕРА:alpgroup/backups/*.gz .`
  Бэкап содержит только базу; ключи в `.env` при этом не меняются. Фото лежат отдельно, в томе `media`.
- **Свой домен** вместо sslip.io: A-запись на IP сервера (в Cloudflare режим **DNS only**, серое облачко),
  затем поменять `DOMAIN` в `.env` и `docker compose up -d`.
- **Сколько сайтов выдержит**: один сайт в таком виде занимает ~0,4–0,6 ГБ. На CX23 (4 ГБ) несколько
  тестовых сайтов помещаются; больше, если сделать общие PostgreSQL и Caddy и `WEB_WORKERS=2`.
- **Боевой стенд** отдельным сервером, с чистой базой и без `seed_demo` (DEPLOY.md, раздел 5).

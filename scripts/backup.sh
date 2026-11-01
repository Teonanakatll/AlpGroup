#!/bin/sh
# Копия базы PostgreSQL: сжатый дамп в backups/, старше 14 дней удаляются.
# Запуск вручную: sh scripts/backup.sh   По расписанию: см. docs/DEPLOY.md (cron).
# Восстановление (в пустую базу):
#   gunzip -c backups/<файл>.sql.gz | docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"'
set -e
cd "$(dirname "$0")/.."

mkdir -p backups
file="backups/alpgroup-$(date +%Y-%m-%d-%H%M).sql.gz"
# логин и имя базы берём из окружения самого контейнера db, .env читать не нужно
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$file"
find backups -name 'alpgroup-*.sql.gz' -mtime +14 -delete
echo "Готово: $file"

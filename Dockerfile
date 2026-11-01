# Образ приложения: Django + gunicorn. Статику и media раздаёт Caddy (см. docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Зависимости ставим отдельным слоем: пока requirements.txt не менялся, пересборка быстрая.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x deploy/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["deploy/entrypoint.sh"]

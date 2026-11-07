git checkout main
git fetch origin
git merge origin/claude/,,,
pytest
git push origin main      # только если тесты зелёные

.venv\Scripts\activate

python manage.py seed_demo

https://alpgroup.ezolab.dev/ - тестовый сайт (админка: /admin/)

ssh root@135.181.195.12 - зайти на сервер

cd ~/alpgroup && git pull && docker compose up -d --build - залить обновление

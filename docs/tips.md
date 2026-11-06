git checkout main
git fetch origin
git merge origin/claude/,,,
pytest
git push origin main      # только если тесты зелёные


python manage.py seed_demo

ssh root@135.181.195.12 - зайти на сервер

cd ~/alpgroup && git pull && docker compose up -d --build - залить обновление

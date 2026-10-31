git checkout main
git fetch origin
git merge origin/claude/,,,
pytest
git push origin main      # только если тесты зелёные


python manage.py seed_demo
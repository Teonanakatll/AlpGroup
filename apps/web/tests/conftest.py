# Общие фикстуры (user, site, category, tool, stocked_hand_tool...) лежат в тестах inventory;
# здесь их подключаем, чтобы тесты страниц могли собирать данные тем же способом.
from apps.inventory.tests.conftest import (  # noqa: F401
    category, hand_tool, site, stocked_hand_tool, tool, user,
)

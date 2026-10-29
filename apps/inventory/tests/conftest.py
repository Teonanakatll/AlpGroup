import pytest
from django.contrib.auth import get_user_model

from apps.inventory import services
from apps.inventory.models import Category, HandTool
from apps.sites.models import Site


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="storekeeper", password="x")


@pytest.fixture
def category(db):
    return Category.objects.create(name="Электроинструмент")


@pytest.fixture
def site(db):
    return Site.objects.create(name="Объект на Ленина, 5")


@pytest.fixture
def hand_tool(category):
    return HandTool.objects.create(name="Молоток", category=category)


@pytest.fixture
def tool(user, category):
    """Штучная позиция, уже поставленная на баланс (статус «на складе»)."""
    return services.register_tool(user=user, name="Перфоратор", category=category)


@pytest.fixture
def stocked_hand_tool(user, hand_tool):
    """Ручной инструмент с 10 штуками на балансе."""
    return services.add_hand_tool_stock(user=user, hand_tool=hand_tool, quantity=10)

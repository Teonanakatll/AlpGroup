import pytest
from django.contrib.auth import get_user_model

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

"""Команда seed_demo: 20 + 10 позиций и 5 объектов, количества 5-15, повторный запуск без дублей."""
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.inventory import services
from apps.inventory.models import HandTool, HandToolMovement, Tool, ToolMovement
from apps.sites.models import Site


def test_seed_creates_20_and_10(admin_user):
    call_command("seed_demo", seed=1)

    assert Tool.objects.count() == 20
    assert HandTool.objects.count() == 20
    assert all(5 <= h.total <= 15 for h in HandTool.objects.all())
    assert all(h.issued == 0 for h in HandTool.objects.all())
    assert Tool.objects.exclude(status=Tool.Status.AVAILABLE).count() == 0


def test_seed_writes_journal_through_services(admin_user):
    call_command("seed_demo", seed=1)

    # По одной записи «поставлен на баланс» на каждую позицию.
    assert ToolMovement.objects.filter(type="added").count() == 20
    assert HandToolMovement.objects.filter(type="added").count() == 10
    assert HandToolMovement.objects.filter(created_by=admin_user).count() == 10


def test_seed_twice_does_not_duplicate(admin_user):
    call_command("seed_demo", seed=1)
    call_command("seed_demo", seed=2)

    assert Tool.objects.count() == 20
    assert HandTool.objects.count() == 20
    assert HandToolMovement.objects.count() == 10


def test_seed_is_reproducible_with_seed(admin_user):
    call_command("seed_demo", seed=7)
    first = dict(HandTool.objects.values_list("name", "total"))
    HandToolMovement.objects.all().delete()
    HandTool.objects.all().delete()

    call_command("seed_demo", seed=7)

    assert dict(HandTool.objects.values_list("name", "total")) == first


def test_seed_creates_five_sites_without_duplicates(admin_user):
    Site.objects.create(name="Центрополис")       # такой объект уже был

    call_command("seed_demo", seed=1)
    call_command("seed_demo", seed=1)

    assert sorted(Site.objects.values_list("name", flat=True)) == sorted(
        ["Лемон Гарден", "Центрополис", "Такаишвили", "Зелёный дом", "Шартава 7"]
    )


def test_seed_needs_a_user(db):
    with pytest.raises(CommandError):
        call_command("seed_demo")


def test_seed_skips_what_is_already_in_database(admin_user, category):
    # Позиция с таким названием уже есть (например, добавили руками): не дублируется и не меняется.
    existing = services.register_tool(user=admin_user, name="Дрель сетевая", category=category)

    call_command("seed_demo", seed=1)

    assert Tool.objects.filter(name="Дрель сетевая").count() == 1
    assert Tool.objects.count() == 20
    existing.refresh_from_db()
    assert existing.category == category
    assert ToolMovement.objects.filter(tool=existing, type="added").count() == 1

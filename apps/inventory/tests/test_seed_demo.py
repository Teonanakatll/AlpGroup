"""Команда seed_demo: 25 + 25 позиций, количества 5-15, повторный запуск без дублей."""
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.inventory.models import HandTool, HandToolMovement, Tool, ToolMovement


def test_seed_creates_25_and_25(admin_user):
    call_command("seed_demo", seed=1)

    assert Tool.objects.count() == 25
    assert HandTool.objects.count() == 25
    assert all(5 <= h.total <= 15 for h in HandTool.objects.all())
    assert all(h.issued == 0 for h in HandTool.objects.all())
    assert Tool.objects.exclude(status=Tool.Status.AVAILABLE).count() == 0


def test_seed_writes_journal_through_services(admin_user):
    call_command("seed_demo", seed=1)

    # По одной записи «поставлен на баланс» на каждую позицию.
    assert ToolMovement.objects.filter(type="added").count() == 25
    assert HandToolMovement.objects.filter(type="added").count() == 25
    assert HandToolMovement.objects.filter(created_by=admin_user).count() == 25


def test_seed_twice_does_not_duplicate(admin_user):
    call_command("seed_demo", seed=1)
    call_command("seed_demo", seed=2)

    assert Tool.objects.count() == 25
    assert HandTool.objects.count() == 25
    assert HandToolMovement.objects.count() == 25


def test_seed_is_reproducible_with_seed(admin_user):
    call_command("seed_demo", seed=7)
    first = dict(HandTool.objects.values_list("name", "total"))
    HandToolMovement.objects.all().delete()
    HandTool.objects.all().delete()

    call_command("seed_demo", seed=7)

    assert dict(HandTool.objects.values_list("name", "total")) == first


def test_seed_needs_a_user(db):
    with pytest.raises(CommandError):
        call_command("seed_demo")

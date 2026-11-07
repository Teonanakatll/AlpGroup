"""Команда seed_demo: 45 штучных и 35 ручных позиций и 5 объектов, количества 5-15, повторный запуск без дублей."""
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.inventory import services
from apps.inventory.models import Category, HandTool, HandToolMovement, Tool, ToolMovement
from apps.sites.models import Site


def test_seed_creates_45_and_35(admin_user):
    call_command("seed_demo", seed=1)

    assert Tool.objects.count() == 45
    assert HandTool.objects.count() == 35
    assert all(5 <= h.total <= 15 for h in HandTool.objects.all())
    assert all(h.issued == 0 for h in HandTool.objects.all())
    assert Tool.objects.exclude(status=Tool.Status.AVAILABLE).count() == 0


def test_seed_writes_journal_through_services(admin_user):
    call_command("seed_demo", seed=1)

    # По одной записи «поставлен на баланс» на каждую позицию.
    assert ToolMovement.objects.filter(type="added").count() == 45
    assert HandToolMovement.objects.filter(type="added").count() == 35
    assert HandToolMovement.objects.filter(created_by=admin_user).count() == 35


def test_seed_twice_does_not_duplicate(admin_user):
    call_command("seed_demo", seed=1)
    call_command("seed_demo", seed=2)

    assert Tool.objects.count() == 45
    assert HandTool.objects.count() == 35
    assert HandToolMovement.objects.count() == 35


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
    assert Tool.objects.count() == 45
    existing.refresh_from_db()
    assert existing.category == category
    assert ToolMovement.objects.filter(tool=existing, type="added").count() == 1


def test_seed_adds_gear_to_its_own_category(admin_user):
    call_command("seed_demo", seed=1)

    gear = Category.objects.get(name="Высотное снаряжение")
    assert Tool.objects.filter(category=gear).count() == 20       # штучно: обвязки, верёвки, устройства
    assert HandTool.objects.filter(category=gear).count() == 10   # количеством: карабины, стропы, каски


def test_seed_does_not_duplicate_gear_on_rerun(admin_user):
    call_command("seed_demo", seed=1)
    call_command("seed_demo", seed=1)

    assert Category.objects.filter(name="Высотное снаряжение").count() == 1
    assert Tool.objects.filter(name="Обвязка страховочная №1").count() == 1


# ---------------------------------------------------------------------------
# --journal: «живой журнал» из 15 операций
# ---------------------------------------------------------------------------

def _batches(model, movement_type):
    return set(model.objects.filter(type=movement_type).values_list("batch", flat=True))


def _all_batches(movement_type):
    return _batches(ToolMovement, movement_type) | _batches(HandToolMovement, movement_type)


def test_journal_creates_operations_of_each_kind(admin_user):
    call_command("seed_demo", seed=3, journal=True)

    assert len(_all_batches("issued")) == 5
    assert len(_all_batches("returned")) == 3
    assert len(_all_batches("written_off")) == 3
    assert len(_batches(ToolMovement, "servicing")) == 4
    assert not HandToolMovement.objects.filter(type="servicing").exists()   # ручной в ремонт не идёт


def test_journal_issues_8_to_12_positions_to_different_sites(admin_user):
    call_command("seed_demo", seed=3, journal=True)

    sites = set()
    for batch in _all_batches("issued"):
        rows = (ToolMovement.objects.filter(batch=batch).count()
                + HandToolMovement.objects.filter(batch=batch).count())
        assert 8 <= rows <= 12
        row = ToolMovement.objects.filter(batch=batch).first() or HandToolMovement.objects.filter(batch=batch).first()
        sites.add(row.site_id)
    assert len(sites) == 5


def test_journal_state_matches_journal(admin_user):
    """Кэш в моделях совпадает с пересчётом из журнала: операции шли через services."""
    call_command("seed_demo", seed=3, journal=True)

    for tool in Tool.objects.all():
        before = (tool.status, tool.current_site_id)
        services.recalc_tool(tool)
        tool.refresh_from_db()
        assert (tool.status, tool.current_site_id) == before
    for hand in HandTool.objects.all():
        before = (hand.total, hand.issued)
        services.recalc_hand_tool(hand)
        hand.refresh_from_db()
        assert (hand.total, hand.issued) == before
        assert 0 <= hand.issued <= hand.total


def test_journal_without_flag_adds_no_operations(admin_user):
    call_command("seed_demo", seed=3)
    assert not ToolMovement.objects.exclude(type="added").exists()
    assert not HandToolMovement.objects.exclude(type="added").exists()


def test_journal_on_top_of_existing_operations(admin_user):
    """База, где уже есть свои выдачи и ремонты (как на стенде): новый круг проходит без ошибок."""
    call_command("seed_demo", seed=1, journal=True)
    call_command("seed_demo", seed=2, journal=True)

    assert Tool.objects.count() == 45                                     # справочники не задвоились
    assert len(_all_batches("issued")) == 10
    assert len(_batches(ToolMovement, "servicing")) == 8

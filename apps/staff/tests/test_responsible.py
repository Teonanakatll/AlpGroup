"""Ответственное лицо объекта: видит в журнале и на главной только свои объекты."""
import pytest
from django.core.management import call_command

from apps.inventory import services
from apps.inventory.models import Category
from apps.sites.models import Site
from apps.staff import roles


@pytest.fixture
def setup(db, admin_user, django_user_model):
    polina = django_user_model.objects.create_user("polina", password="x", first_name="Полина", last_name="Иванова")
    roles.assign_role(polina, roles.RESPONSIBLE)
    category = Category.objects.create(name="Электро")
    mine = Site.objects.create(name="Мой объект", responsible=polina)
    other = Site.objects.create(name="Чужой объект")
    for site, name in ((mine, "Дрель"), (other, "Болгарка")):
        tool = services.register_tool(user=admin_user, name=name, category=category)
        services.issue_to_site(user=admin_user, site=site, tools=[tool], taken_by="Кто-то")
    return polina


def test_responsible_sees_only_own_sites(client, setup):
    client.force_login(setup)
    journal = client.get("/journal/").content.decode()
    assert "Мой объект" in journal and "Дрель" in journal
    assert "Чужой объект" not in journal and "Болгарка" not in journal
    assert "Операции по вашим объектам" in journal

    home = client.get("/").content.decode()
    assert "Болгарка" not in home and "Чужой объект" not in home


def test_responsible_cannot_filter_into_foreign_site(client, setup):
    client.force_login(setup)
    other = Site.objects.get(name="Чужой объект")
    html = client.get("/journal/", {"site": other.pk}).content.decode()
    assert "Болгарка" not in html


def test_responsible_without_sites_sees_hint(client, django_user_model, setup):
    nobody = django_user_model.objects.create_user("nobody", password="x")
    roles.assign_role(nobody, roles.RESPONSIBLE)
    client.force_login(nobody)
    html = client.get("/journal/").content.decode()
    assert "не закреплено ни одного объекта" in html
    assert "Дрель" not in html


def test_storekeeper_sees_all(client, django_user_model, setup):
    keeper = django_user_model.objects.create_user("keeper", password="x")
    roles.assign_role(keeper, roles.STOREKEEPER)
    client.force_login(keeper)
    html = client.get("/journal/").content.decode()
    assert "Дрель" in html and "Болгарка" in html


def test_seed_assigns_responsible_and_issues_to_them(admin_user):
    call_command("seed_demo", seed=3, journal=True)

    site = Site.objects.select_related("responsible").get(name="Лемон Гарден")
    assert site.responsible.get_full_name() == "Гиорги Беридзе"
    assert roles.user_role(site.responsible) == roles.RESPONSIBLE
    assert not site.responsible.has_usable_password()
    assert Site.objects.filter(responsible__isnull=True).count() == 0


def test_seed_gives_guest_two_sites_when_demo_user(admin_user, settings):
    settings.DEMO_USER = "гость"
    call_command("seed_demo", seed=3)
    names = sorted(Site.objects.filter(responsible__username="гость").values_list("name", flat=True))
    assert names == ["Зелёный дом", "Шартава 7"]


def test_seed_does_not_override_assigned_responsible(admin_user, django_user_model):
    Site.objects.create(name="Лемон Гарден", responsible=admin_user)
    call_command("seed_demo", seed=3)
    assert Site.objects.get(name="Лемон Гарден").responsible == admin_user

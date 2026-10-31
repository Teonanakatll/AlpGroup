from apps.sites.models import Site
from apps.sites.services import get_or_create_site
import pytest


def test_creates_new_site(db):
    site, created = get_or_create_site("Зелёный дом")

    assert created and site.name == "Зелёный дом"


def test_finds_existing_site_ignoring_case_and_spaces(db):
    existing = Site.objects.create(name="Lemon Garden")      # латиница: регистр кириллицы зависит от локали БД

    site, created = get_or_create_site("  lemon   garden ")

    assert not created and site == existing
    assert Site.objects.count() == 1


def test_empty_name_is_rejected(db):
    with pytest.raises(ValueError):
        get_or_create_site("   ")

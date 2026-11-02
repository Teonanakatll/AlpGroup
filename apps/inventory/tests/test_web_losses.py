"""
Страницы «Не найден», «Списание», «В ремонт», «Из ремонта» (apps/web) и выборки для них.
Правила учёта проверяются в тестах services; здесь форма доводит данные до сервисов и показывает отказ.
"""
from apps.inventory import selectors, services
from apps.inventory.models import HandToolMovement, Tool, ToolMovement

URLS = ("/operations/missing/", "/operations/write-off/", "/operations/servicing/", "/operations/from-servicing/")


def post(client, url, **fields):
    return client.post(url, fields)


def page(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return response.content.decode()


# ---------------------------------------------------------------------------
# Доступ, вкладки, выборки
# ---------------------------------------------------------------------------

def test_pages_require_login(client):
    for url in URLS:
        response = client.get(url)
        assert response.status_code == 302 and response["Location"].startswith("/login/")


def test_all_operation_tabs_are_on_every_page(admin_client):
    for url in ("/operations/issue/", "/operations/receive/") + URLS:
        html = page(admin_client, url)
        for target in ("/operations/add/", "/operations/issue/", "/operations/receive/") + URLS:
            assert f'href="{target}"' in html


def test_selectors_for_servicing_and_write_off(user, category, site, tool):
    sent = services.register_tool(user=user, name="Фрезер", category=category)
    lost = services.register_tool(user=user, name="Нивелир", category=category)
    issued = services.register_tool(user=user, name="Болгарка", category=category)
    services.send_to_servicing(user=user, tools=[sent])
    services.issue_to_site(user=user, site=site, tools=[lost, issued])
    services.mark_missing(user=user, site=site, tools=[lost])

    assert [t.name for t in selectors.tools_in_servicing()] == ["Фрезер"]
    # со склада списывается: на складе, в ремонте, не найден; выданное нельзя
    assert sorted(t.name for t in selectors.tools_for_write_off()) == ["Нивелир", "Перфоратор", "Фрезер"]


# ---------------------------------------------------------------------------
# Не найден
# ---------------------------------------------------------------------------

def test_missing_page_asks_for_site_then_lists_site_items(admin_client, user, tool, stocked_hand_tool, site):
    assert "Выберите объект" in page(admin_client, "/operations/missing/")
    services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 4)])

    html = page(admin_client, f"/operations/missing/?site={site.pk}")

    assert "Перфоратор" in html and "Молоток" in html and 'max="4"' in html


def test_missing_marks_items_and_reduces_hand_total(admin_client, user, tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 4)])

    response = post(admin_client, "/operations/missing/", site=site.pk, tools=[tool.pk],
                    taken_by="Прораб", **{f"qty_{stocked_hand_tool.pk}": 1})

    assert response.status_code == 302 and response["Location"] == "/operations/missing/"
    tool.refresh_from_db()
    stocked_hand_tool.refresh_from_db()
    assert tool.status == "missing"
    assert (stocked_hand_tool.total, stocked_hand_tool.issued) == (9, 3)
    assert "Не найдено на «Объект на Ленина, 5»" in page(admin_client, "/operations/missing/")


def test_missing_needs_site(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    response = admin_client.post("/operations/missing/", {"tools": [tool.pk]})

    assert response.status_code == 200
    tool.refresh_from_db()
    assert tool.status == "issued"


def test_missing_on_warehouse_item_is_rejected(admin_client, tool, site):
    response = post(admin_client, "/operations/missing/", site=site.pk, tools=[tool.pk])

    assert response.status_code == 200 and "Операция не выполнена" in response.content.decode()
    tool.refresh_from_db()
    assert tool.status == "available"


# ---------------------------------------------------------------------------
# Списание
# ---------------------------------------------------------------------------

def test_write_off_page_defaults_to_warehouse_with_statuses(admin_client, user, tool, stocked_hand_tool, category, site):
    broken = services.register_tool(user=user, name="Фрезер", category=category)
    services.send_to_servicing(user=user, tools=[broken])
    busy = services.register_tool(user=user, name="Болгарка", category=category)
    services.issue_to_site(user=user, site=site, tools=[busy])

    html = page(admin_client, "/operations/write-off/")

    assert "Перфоратор" in html and "Фрезер" in html and "В ремонте" in html
    assert "Болгарка" not in html                      # выданное со склада не списать
    assert 'max="10"' in html and "на складе 10" in html
    assert 'data-dd-keep' in html                      # «Склад» это настоящий выбор, а не подсказка


def test_write_off_from_warehouse(admin_client, tool, stocked_hand_tool):
    response = post(admin_client, "/operations/write-off/", site="", tools=[tool.pk],
                    note="сломан", **{f"qty_{stocked_hand_tool.pk}": 3})

    assert response.status_code == 302
    tool.refresh_from_db()
    stocked_hand_tool.refresh_from_db()
    assert tool.status == "written_off"
    assert stocked_hand_tool.total == 7
    assert ToolMovement.objects.get(tool=tool, type="written_off").note == "сломан"
    assert "Списано со склада" in page(admin_client, "/operations/write-off/")


def test_write_off_from_site(admin_client, user, tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 4)])

    html = page(admin_client, f"/operations/write-off/?site={site.pk}")
    assert "Перфоратор" in html and 'max="4"' in html and "на объекте 4" in html

    response = post(admin_client, "/operations/write-off/", site=site.pk, tools=[tool.pk],
                    **{f"qty_{stocked_hand_tool.pk}": 2})

    assert response.status_code == 302
    tool.refresh_from_db()
    stocked_hand_tool.refresh_from_db()
    assert tool.status == "written_off"
    assert (stocked_hand_tool.total, stocked_hand_tool.issued) == (8, 2)


def test_write_off_too_many_is_rejected(admin_client, stocked_hand_tool):
    response = post(admin_client, "/operations/write-off/", site="", **{f"qty_{stocked_hand_tool.pk}": 11})

    assert response.status_code == 200 and "Операция не выполнена" in response.content.decode()
    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.total == 10
    assert not HandToolMovement.objects.filter(type="written_off").exists()


def test_write_off_htmx_returns_block_for_chosen_place(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    on_site = admin_client.get(f"/operations/write-off/?site={site.pk}", headers={"HX-Request": "true"})
    warehouse = admin_client.get("/operations/write-off/?site=", headers={"HX-Request": "true"})

    assert 'id="positions"' in on_site.content.decode() and "<html" not in on_site.content.decode()
    assert "Перфоратор" in on_site.content.decode()
    assert "нечего списывать" in warehouse.content.decode()      # на складе выданное не списать


# ---------------------------------------------------------------------------
# Ремонт
# ---------------------------------------------------------------------------

def test_servicing_has_no_hand_tools(admin_client, tool, stocked_hand_tool):
    html = page(admin_client, "/operations/servicing/")

    assert "Перфоратор" in html
    assert "Молоток" not in html and "qty_" not in html


def test_send_to_servicing_from_warehouse_and_back(admin_client, tool):
    response = post(admin_client, "/operations/servicing/", site="", tools=[tool.pk], taken_by="Сергей")
    assert response.status_code == 302
    tool.refresh_from_db()
    assert tool.status == "servicing"

    assert "Перфоратор" in page(admin_client, "/operations/from-servicing/")
    response = post(admin_client, "/operations/from-servicing/", tools=[tool.pk], taken_by="Сергей")

    assert response.status_code == 302
    tool.refresh_from_db()
    assert tool.status == "available"
    assert "Принято из ремонта" in page(admin_client, "/operations/from-servicing/")


def test_send_to_servicing_from_site(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    response = post(admin_client, "/operations/servicing/", site=site.pk, tools=[tool.pk])

    assert response.status_code == 302
    tool.refresh_from_db()
    assert tool.status == "servicing" and tool.current_site is None


def test_servicing_rejects_hand_tools(admin_client, tool, stocked_hand_tool):
    response = post(admin_client, "/operations/servicing/", site="", tools=[tool.pk],
                    **{f"qty_{stocked_hand_tool.pk}": 1})

    assert response.status_code == 200 and "Ручной инструмент в ремонт не отправляется" in response.content.decode()
    tool.refresh_from_db()
    assert tool.status == "available"


def test_from_servicing_lists_only_items_in_servicing(admin_client, user, category, tool):
    broken = services.register_tool(user=user, name="Фрезер", category=category)
    services.send_to_servicing(user=user, tools=[broken])

    html = page(admin_client, "/operations/from-servicing/")

    assert "Фрезер" in html and "Перфоратор" not in html


def test_from_servicing_rejects_item_not_in_servicing(admin_client, tool):
    response = post(admin_client, "/operations/from-servicing/", tools=[tool.pk])

    assert response.status_code == 200 and "Операция не выполнена" in response.content.decode()
    tool.refresh_from_db()
    assert tool.status == "available"


def test_from_servicing_empty(admin_client):
    assert "ничего не в ремонте" in page(admin_client, "/operations/from-servicing/")

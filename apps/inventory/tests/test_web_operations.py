"""
Формы выдачи и приёма на сайте (apps/web): страницы, разбор формы, отказы, подмена блока через HTMX.

Правила учёта проверяются в тестах services; здесь убеждаемся, что форма доводит данные
до сервисов, показывает отказ и ничего не записывает при ошибке.
"""
from apps.inventory import services
from apps.inventory.models import ToolMovement
from apps.sites.models import Site


def issue_post(client, site, **fields):
    return client.post("/operations/issue/", {"site": site.pk, **fields})


def receive_post(client, site, **fields):
    return client.post("/operations/receive/", {"site": site.pk, **fields})


# ---------------------------------------------------------------------------
# Доступ и страницы
# ---------------------------------------------------------------------------

def test_operations_require_login(client):
    for url in ("/operations/", "/operations/issue/", "/operations/receive/"):
        response = client.get(url)
        assert response.status_code == 302
        assert response["Location"].startswith("/login/")


def test_operations_menu_item_leads_to_issue(admin_client):
    response = admin_client.get("/operations/")
    assert response.status_code == 302 and response["Location"] == "/operations/issue/"
    assert 'href="/operations/"' in admin_client.get("/").content.decode()


def test_issue_page_lists_only_what_can_be_issued(admin_client, user, category, site, tool, stocked_hand_tool):
    taken = services.register_tool(user=user, name="Болгарка", category=category)
    services.issue_to_site(user=user, site=site, tools=[taken])

    html = admin_client.get("/operations/issue/").content.decode()

    assert "Перфоратор" in html and "Молоток" in html
    assert "Болгарка" not in html            # уже выдана
    assert f'name="qty_{stocked_hand_tool.pk}"' in html
    assert 'max="10"' in html


def test_issue_page_on_empty_warehouse(admin_client):
    assert "нечего выдавать" in admin_client.get("/operations/issue/").content.decode()


# ---------------------------------------------------------------------------
# Выдача
# ---------------------------------------------------------------------------

def test_issue_writes_to_journal_and_shows_message(admin_client, tool, stocked_hand_tool, site):
    response = issue_post(
        admin_client, site, tools=[tool.pk], taken_by="Иванов", note="на неделю",
        **{f"qty_{stocked_hand_tool.pk}": 4},
    )

    assert response.status_code == 302 and response["Location"] == "/operations/issue/"
    tool.refresh_from_db()
    stocked_hand_tool.refresh_from_db()
    assert tool.status == "issued" and tool.current_site == site
    assert stocked_hand_tool.issued == 4
    movement = ToolMovement.objects.get(tool=tool, type="issued")
    assert movement.taken_by == "Иванов" and movement.note == "на неделю"
    html = admin_client.get("/operations/issue/").content.decode()   # сообщение показывается на следующей странице
    assert "Выдано на «Объект на Ленина, 5»" in html


def test_issue_ignores_blank_and_zero_quantities(admin_client, tool, stocked_hand_tool, site):
    response = issue_post(admin_client, site, tools=[tool.pk], **{f"qty_{stocked_hand_tool.pk}": ""})
    assert response.status_code == 302
    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 0


def test_issue_without_selection_is_rejected(admin_client, tool, site):
    response = issue_post(admin_client, site)

    assert response.status_code == 200
    assert "Не выбрано ни одной позиции" in response.content.decode()


def test_issue_without_site_shows_field_error(admin_client, tool):
    response = admin_client.post("/operations/issue/", {"tools": [tool.pk]})

    assert response.status_code == 200
    tool.refresh_from_db()
    assert tool.status == "available"


def test_issue_rejects_too_many_and_writes_nothing(admin_client, tool, stocked_hand_tool, site):
    response = issue_post(admin_client, site, tools=[tool.pk], **{f"qty_{stocked_hand_tool.pk}": 11})

    html = response.content.decode()
    assert response.status_code == 200
    assert "Операция не выполнена" in html and "в наличии 10" in html
    tool.refresh_from_db()
    assert tool.status == "available"        # всё или ничего: и штучная позиция не выдана
    assert not ToolMovement.objects.filter(type="issued").exists()
    assert f'value="{tool.pk}" checked' in html   # выбор не потерян после ошибки


def test_issue_rejects_already_issued_tool(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    response = issue_post(admin_client, site, tools=[tool.pk])

    assert response.status_code == 200
    assert "нельзя выдать" in response.content.decode()


def test_issue_bad_quantity_is_reported(admin_client, stocked_hand_tool, site):
    response = issue_post(admin_client, site, **{f"qty_{stocked_hand_tool.pk}": "abc"})

    assert response.status_code == 200
    assert "не число" in response.content.decode()
    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 0


# ---------------------------------------------------------------------------
# Приём
# ---------------------------------------------------------------------------

def test_receive_page_without_site_asks_to_choose(admin_client, site):
    html = admin_client.get("/operations/receive/").content.decode()

    assert "Выберите объект" in html
    assert 'hx-get="/operations/receive/"' in html      # HTMX подменит блок позиций


def test_receive_lists_what_is_on_the_site(admin_client, user, tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 4)])

    html = admin_client.get(f"/operations/receive/?site={site.pk}").content.decode()

    assert "Перфоратор" in html and "Молоток" in html
    assert 'max="4"' in html                             # принять можно не больше, чем на объекте


def test_receive_htmx_returns_only_the_positions_block(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    response = admin_client.get(f"/operations/receive/?site={site.pk}", headers={"HX-Request": "true"})

    html = response.content.decode()
    assert response.status_code == 200
    assert 'id="positions"' in html and "Перфоратор" in html
    assert "<html" not in html                           # кусок страницы, а не вся страница


def test_receive_other_site_shows_nothing(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])
    other = Site.objects.create(name="Другой объект")

    html = admin_client.get(f"/operations/receive/?site={other.pk}").content.decode()

    assert "ничего не числится" in html and "Перфоратор" not in html


def test_receive_garbage_site_is_ignored(admin_client):
    assert admin_client.get("/operations/receive/?site=abc").status_code == 200


def test_receive_returns_items_to_warehouse(admin_client, user, tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 4)])

    response = receive_post(
        admin_client, site, tools=[tool.pk], taken_by="Петров", **{f"qty_{stocked_hand_tool.pk}": 3},
    )

    assert response.status_code == 302 and response["Location"] == "/operations/receive/"
    tool.refresh_from_db()
    stocked_hand_tool.refresh_from_db()
    assert tool.status == "available" and tool.current_site is None
    assert stocked_hand_tool.issued == 1                 # 4 выдали, 3 приняли
    assert "Принято с «Объект на Ленина, 5»" in admin_client.get("/operations/receive/").content.decode()


def test_receive_from_wrong_site_is_rejected(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])
    other = Site.objects.create(name="Другой объект")

    response = receive_post(admin_client, other, tools=[tool.pk])

    assert response.status_code == 200
    assert "Операция не выполнена" in response.content.decode()
    tool.refresh_from_db()
    assert tool.status == "issued" and tool.current_site == site


def test_receive_more_than_on_site_is_rejected(admin_client, user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 4)])

    response = receive_post(admin_client, site, **{f"qty_{stocked_hand_tool.pk}": 5})

    assert response.status_code == 200
    assert "Операция не выполнена" in response.content.decode()
    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 4


# ---------------------------------------------------------------------------
# Новый объект прямо в форме выдачи
# ---------------------------------------------------------------------------

def test_issue_form_offers_new_site_field(admin_client, tool):
    html = admin_client.get("/operations/issue/").content.decode()

    assert 'name="new_site"' in html and "Название нового объекта" in html


def test_issue_creates_new_site_with_issue(admin_client, tool):
    response = admin_client.post("/operations/issue/", {"new_site": "  Лемон   Гарден ", "tools": [tool.pk]})

    assert response.status_code == 302
    created = Site.objects.get(name="Лемон Гарден")            # лишние пробелы убраны
    tool.refresh_from_db()
    assert tool.status == "issued" and tool.current_site == created
    assert "(новый объект)" in admin_client.get("/operations/issue/").content.decode()


def test_issue_reuses_existing_site_by_name(admin_client, tool, site):
    admin_client.post("/operations/issue/", {"new_site": f"  {site.name}  ", "tools": [tool.pk]})

    assert Site.objects.count() == 1                           # дубль не создан
    tool.refresh_from_db()
    assert tool.current_site == site


def test_new_site_wins_over_selected_one(admin_client, tool, site):
    admin_client.post("/operations/issue/", {"site": site.pk, "new_site": "Шартава 7", "tools": [tool.pk]})

    tool.refresh_from_db()
    assert tool.current_site.name == "Шартава 7"


def test_failed_issue_does_not_leave_new_site(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])      # позиция уже выдана: выдача откажет

    response = admin_client.post("/operations/issue/", {"new_site": "Центрополис", "tools": [tool.pk]})

    assert response.status_code == 200
    assert not Site.objects.filter(name="Центрополис").exists()    # объект откатился вместе с выдачей
    assert "Центрополис" in response.content.decode()              # а введённое название в форме осталось


def test_issue_needs_site_or_new_site(admin_client, tool):
    response = admin_client.post("/operations/issue/", {"tools": [tool.pk]})

    assert response.status_code == 200
    assert "Выберите объект или введите новый" in response.content.decode()


# ---------------------------------------------------------------------------
# Количество ручного инструмента: стрелки
# ---------------------------------------------------------------------------

def test_hand_tool_row_has_stepper_arrows(admin_client, stocked_hand_tool):
    html = admin_client.get("/operations/issue/").content.decode()

    assert html.count('data-qty-step="-1"') == 1 and html.count('data-qty-step="1"') == 1

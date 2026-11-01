"""
Журнал, история позиции и отмена на сайте (apps/web) и выборки для них.
Сами правила отмены проверяются в тестах services; здесь страницы показывают
«можно ли отменить» и доводят нажатие до сервисов.
"""
from apps.inventory import selectors, services
from apps.inventory.models import HandToolMovement, Tool, ToolMovement


def page(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return response.content.decode()


# ---------------------------------------------------------------------------
# Выборки
# ---------------------------------------------------------------------------

def test_only_last_operation_can_be_cancelled(user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])
    services.receive_from_site(user=user, site=site, tools=[tool])

    entries, _ = selectors.journal_entries()
    rows = {r["type"]: r for e in entries for r in e["rows"]}

    assert rows["returned"]["can_cancel"] is True
    assert rows["issued"]["can_cancel"] is False and "сначала отмените" in rows["issued"]["hint"]
    assert rows["added"]["can_cancel"] is False and "на баланс" in rows["added"]["hint"]


def test_set_is_grouped_and_can_be_cancelled_whole(user, tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 3)])

    entries, _ = selectors.journal_entries()
    issued = [e for e in entries if e["is_set"]]

    assert len(issued) == 1 and len(issued[0]["rows"]) == 2        # перфоратор и молотки в одном наборе
    assert issued[0]["can_cancel_batch"] is True


def test_set_cannot_be_cancelled_if_one_item_moved_on(user, tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 3)])
    services.receive_from_site(user=user, site=site, tools=[tool])   # перфоратор уже вернули

    entry = next(e for e in selectors.journal_entries()[0] if e["is_set"])

    assert entry["can_cancel_batch"] is False
    assert "Перфоратор" in entry["cancel_batch_hint"]


def test_cancelled_row_is_not_cancellable_again(user, tool, site):
    batch = services.issue_to_site(user=user, site=site, tools=[tool])
    services.cancel_batch(user=user, batch=batch)

    row = next(r for e in selectors.journal_entries()[0] for r in e["rows"] if r["type"] == "issued")

    assert row["is_cancelled"] and not row["can_cancel"] and row["hint"] == ""


def test_batch_cut_by_limit_is_loaded_whole(user, tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 3)])

    entries, _ = selectors.journal_entries(limit=1)               # лимит режет набор, а он догружается

    assert len(next(e for e in entries if e["is_set"])["rows"]) == 2


# ---------------------------------------------------------------------------
# Страницы
# ---------------------------------------------------------------------------

def test_journal_and_details_require_login(client, tool):
    for url in ("/journal/", f"/inventory/tool/{tool.pk}/"):
        response = client.get(url)
        assert response.status_code == 302 and response["Location"].startswith("/login/")


def test_journal_shows_cancel_buttons(admin_client, user, tool, stocked_hand_tool, site):
    batch = services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 3)])

    html = page(admin_client, "/journal/")

    assert f"/journal/cancel-batch/{batch}/" in html and "Отменить набор" in html
    assert f"/journal/cancel/tool/{ToolMovement.objects.filter(type='issued').get().pk}/" in html
    assert "Перфоратор" in html and site.name in html


def test_journal_set_is_one_accordion_row(admin_client, user, tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 3)])

    html = page(admin_client, "/journal/")

    assert html.count("<details") == 1                      # набор свёрнут в одну строку
    assert "2 поз." in html and site.name in html            # объект и число позиций
    assert "Перфоратор" in html and "Молоток × 3" in html     # позиции внутри и в превью строки


def test_journal_single_row_is_not_accordion(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    assert "<details" not in page(admin_client, "/journal/")


def test_inventory_shows_site_after_status(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    html = page(admin_client, "/inventory/")

    assert f'<span class="item-site" title="{site.name}">' in html


def test_journal_link_in_menu_and_on_home(admin_client):
    assert 'href="/journal/"' in page(admin_client, "/")


def test_position_pages_show_history(admin_client, user, tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 3)])

    tool_html = page(admin_client, f"/inventory/tool/{tool.pk}/")
    hand_html = page(admin_client, f"/inventory/hand/{stocked_hand_tool.pk}/")

    assert "Перфоратор" in tool_html and "Выдан" in tool_html and "Поставлен на баланс" in tool_html
    assert "Молоток" in hand_html and "× 3" in hand_html and "всего 10" in hand_html


def test_inventory_links_to_position_pages(admin_client, tool, stocked_hand_tool):
    html = page(admin_client, "/inventory/")

    assert f"/inventory/tool/{tool.pk}/" in html and f"/inventory/hand/{stocked_hand_tool.pk}/" in html


# ---------------------------------------------------------------------------
# Отмена
# ---------------------------------------------------------------------------

def test_cancel_movement_restores_tool(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])
    row = ToolMovement.objects.get(type="issued")

    response = admin_client.post(f"/journal/cancel/tool/{row.pk}/", {"next": "/journal/"}, follow=True)

    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE and tool.current_site is None
    assert response.redirect_chain[-1][0] == "/journal/"
    assert "Операция отменена" in response.content.decode()


def test_cancel_movement_of_hand_tool(admin_client, user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 4)])
    row = HandToolMovement.objects.get(type="issued")

    admin_client.post(f"/journal/cancel/hand/{row.pk}/")

    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 0


def test_cancel_batch_cancels_everything(admin_client, user, tool, stocked_hand_tool, site):
    batch = services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 3)])

    response = admin_client.post(f"/journal/cancel-batch/{batch}/", follow=True)

    tool.refresh_from_db(); stocked_hand_tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE and stocked_hand_tool.issued == 0
    assert "Набор отменён" in response.content.decode()


def test_cancel_batch_all_or_nothing_shows_reason(admin_client, user, tool, stocked_hand_tool, site):
    batch = services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 3)])
    services.receive_from_site(user=user, site=site, tools=[tool])

    response = admin_client.post(f"/journal/cancel-batch/{batch}/", follow=True)

    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 3                          # молотки тоже не отменились
    assert not HandToolMovement.objects.filter(is_cancelled=True).exists()
    assert "Перфоратор" in response.content.decode() and "только последнюю" in response.content.decode()


def test_cancel_added_is_refused_with_message(admin_client, tool):
    row = ToolMovement.objects.get(type="added")

    response = admin_client.post(f"/journal/cancel/tool/{row.pk}/", follow=True)

    row.refresh_from_db()
    assert not row.is_cancelled
    assert "постановку на баланс отменять нельзя" in response.content.decode()


def test_cancel_requires_post_and_login(admin_client, client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])
    row = ToolMovement.objects.get(type="issued")

    assert admin_client.get(f"/journal/cancel/tool/{row.pk}/").status_code == 405
    response = client.post(f"/journal/cancel/tool/{row.pk}/")
    assert response.status_code == 302 and response["Location"].startswith("/login/")
    row.refresh_from_db()
    assert not row.is_cancelled


def test_cancel_unknown_kind_is_404(admin_client):
    assert admin_client.post("/journal/cancel/bogus/1/").status_code == 404


def test_cancel_ignores_foreign_next(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])
    row = ToolMovement.objects.get(type="issued")

    response = admin_client.post(f"/journal/cancel/tool/{row.pk}/", {"next": "https://evil.example/"})

    assert response.status_code == 302 and response["Location"] == "/journal/"

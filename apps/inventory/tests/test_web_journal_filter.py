"""Журнал: фильтр по объекту и «Кто взял», имя получателя только в раскрытом наборе."""
from apps.inventory import selectors, services
from apps.sites.models import Site


def _issue(user, site, tool, hand, who):
    return services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(hand, 1)], taken_by=who)


def test_selector_filters_by_site_and_person(user, site, tool, stocked_hand_tool, category):
    other_site = Site.objects.create(name="Центрополис")
    other_tool = services.register_tool(user=user, name="Болгарка", category=category)
    _issue(user, site, tool, stocked_hand_tool, "Гиорги Беридзе")
    _issue(user, other_site, other_tool, stocked_hand_tool, "Нино Абашидзе")

    by_site, _ = selectors.journal_entries(site=other_site.pk)
    assert [e["site"] for e in by_site] == ["Центрополис"]
    assert by_site[0]["count"] == 2                                # набор целиком

    by_person, _ = selectors.journal_entries(taken_by="Гиорги Беридзе")
    assert [e["taken_by"] for e in by_person] == ["Гиорги Беридзе"]

    assert selectors.journal_entries(site=site.pk, taken_by="Нино Абашидзе")[0] == []

    filters = selectors.journal_filters()
    assert sorted(s.name for s in filters["sites"]) == sorted(["Центрополис", site.name])
    assert filters["people"] == ["Гиорги Беридзе", "Нино Абашидзе"]


def test_name_shown_only_inside_open_set(admin_client, admin_user, site, tool, stocked_hand_tool):
    _issue(admin_user, site, tool, stocked_hand_tool, "Гиорги Беридзе")
    html = admin_client.get("/journal/").content.decode()

    assert html.count("Гиорги Беридзе") >= 1
    assert 'class="set-person"' in html and "Получил:" in html
    summary = html.split("<summary", 1)[1].split("</summary>", 1)[0]
    assert "Гиорги Беридзе" not in summary                           # в заголовке набора имени нет


def test_journal_page_filter_and_my_requests(admin_client, admin_user, site, tool, stocked_hand_tool):
    admin_user.first_name, admin_user.last_name = "Гиорги", "Беридзе"
    admin_user.save()
    _issue(admin_user, site, tool, stocked_hand_tool, "Гиорги Беридзе")

    html = admin_client.get("/journal/").content.decode()
    assert "Мои заявки" in html                                       # имя пользователя есть в журнале

    filtered = admin_client.get("/journal/", {"who": "Нино Абашидзе"}).content.decode()
    assert "По этому фильтру операций нет" in filtered
    assert "Сбросить" in filtered

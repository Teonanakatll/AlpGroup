"""
API операций: выдача, приём с объекта, приём из ремонта.

Здесь проверяем только то, что API правильно передаёт данные в services и правильно
отвечает; сами правила учёта покрыты тестами services. Отправляем настоящий JSON,
как это будет делать фронтенд.
"""
from apps.inventory import services
from apps.inventory.models import HandToolMovement, Tool, ToolMovement


def post(client, url, body):
    return client.post(url, body, content_type="application/json")


def test_operations_require_login(client, tool, site):
    response = post(client, "/api/issue/", {"site": site.pk, "tools": [tool.pk]})
    assert response.status_code in (401, 403)


def test_issue_tool(admin_client, admin_user, tool, site):
    response = post(admin_client, "/api/issue/", {
        "site": site.pk, "tools": [tool.pk], "taken_by": "Иванов",
    })

    assert response.status_code == 201
    batch = response.json()["batch"]
    tool.refresh_from_db()
    assert tool.status == Tool.Status.ISSUED
    assert tool.current_site == site
    # Операция записана от имени вошедшего пользователя и с тем batch, что вернул API.
    row = ToolMovement.objects.get(batch=batch)
    assert row.created_by == admin_user
    assert row.taken_by == "Иванов"


def test_issue_hand_tool_and_tool_in_one_set(admin_client, tool, stocked_hand_tool, site):
    response = post(admin_client, "/api/issue/", {
        "site": site.pk,
        "tools": [tool.pk],
        "hand_tools": [{"hand_tool": stocked_hand_tool.pk, "quantity": 4}],
    })

    assert response.status_code == 201
    batch = response.json()["batch"]
    # У обоих журналов один общий batch (одно действие пользователя).
    assert ToolMovement.objects.filter(batch=batch).count() == 1
    assert HandToolMovement.objects.filter(batch=batch).count() == 1
    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 4


def test_service_refusal_is_400_with_all_errors_and_changes_nothing(
    admin_client, user, category, tool, site,
):
    free_tool = services.register_tool(user=user, name="Дрель", category=category)
    services.issue_to_site(user=user, site=site, tools=[tool])
    journal_before = ToolMovement.objects.count()

    # В наборе одна позиция уже выдана, другая свободна: не должно выдаться ни одна.
    response = post(admin_client, "/api/issue/", {"site": site.pk, "tools": [tool.pk, free_tool.pk]})

    assert response.status_code == 400
    body = response.json()
    assert body["detail"] == "Операция отклонена."
    assert len(body["errors"]) == 1
    assert "нельзя выдать" in body["errors"][0]
    free_tool.refresh_from_db()
    assert free_tool.status == Tool.Status.AVAILABLE
    assert ToolMovement.objects.count() == journal_before


def test_issue_more_than_available_is_refused(admin_client, stocked_hand_tool, site):
    response = post(admin_client, "/api/issue/", {
        "site": site.pk, "hand_tools": [{"hand_tool": stocked_hand_tool.pk, "quantity": 11}],
    })

    assert response.status_code == 400
    assert "запрошено 11" in response.json()["errors"][0]
    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 0


def test_empty_set_is_refused(admin_client, site):
    response = post(admin_client, "/api/issue/", {"site": site.pk})

    assert response.status_code == 400
    assert "Не выбрано" in response.json()["errors"][0]


def test_bad_input_is_refused_before_services(admin_client, tool, stocked_hand_tool, site):
    # Нет объекта.
    assert post(admin_client, "/api/issue/", {"tools": [tool.pk]}).status_code == 400
    # Такого объекта нет.
    assert post(admin_client, "/api/issue/", {"site": 999999, "tools": [tool.pk]}).status_code == 400
    # Такого инструмента нет.
    assert post(admin_client, "/api/issue/", {"site": site.pk, "tools": [999999]}).status_code == 400
    # Количество не меньше 1.
    bad_quantity = {"site": site.pk, "hand_tools": [{"hand_tool": stocked_hand_tool.pk, "quantity": 0}]}
    response = post(admin_client, "/api/issue/", bad_quantity)
    assert response.status_code == 400
    assert "hand_tools" in response.json()  # ошибка формата: ключ поля, а не detail/errors
    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE


def test_same_tool_twice_is_refused(admin_client, tool, site):
    response = post(admin_client, "/api/issue/", {"site": site.pk, "tools": [tool.pk, tool.pk]})

    assert response.status_code == 400
    assert "больше одного раза" in response.json()["errors"][0]


def test_receive_from_site(admin_client, user, tool, stocked_hand_tool, site):
    services.issue_to_site(
        user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 5)],
    )

    response = post(admin_client, "/api/receive/", {
        "site": site.pk,
        "tools": [tool.pk],
        "hand_tools": [{"hand_tool": stocked_hand_tool.pk, "quantity": 5}],
    })

    assert response.status_code == 201
    tool.refresh_from_db()
    stocked_hand_tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE
    assert stocked_hand_tool.issued == 0


def test_receive_from_wrong_site_is_refused(admin_client, user, tool, site):
    from apps.sites.models import Site
    other = Site.objects.create(name="Другой объект")
    services.issue_to_site(user=user, site=site, tools=[tool])

    response = post(admin_client, "/api/receive/", {"site": other.pk, "tools": [tool.pk]})

    assert response.status_code == 400
    assert "числится не на этом объекте" in response.json()["errors"][0]
    tool.refresh_from_db()
    assert tool.status == Tool.Status.ISSUED


def test_receive_from_servicing(admin_client, user, tool):
    services.send_to_servicing(user=user, tools=[tool])

    response = post(admin_client, "/api/receive-from-servicing/", {"tools": [tool.pk]})

    assert response.status_code == 201
    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE


def test_receive_from_servicing_refuses_tool_not_in_servicing(admin_client, tool):
    response = post(admin_client, "/api/receive-from-servicing/", {"tools": [tool.pk]})

    assert response.status_code == 400
    assert "нельзя принять из ремонта" in response.json()["errors"][0]


def test_returned_batch_can_be_cancelled(admin_client, user, tool, site):
    batch = post(admin_client, "/api/issue/", {"site": site.pk, "tools": [tool.pk]}).json()["batch"]

    services.cancel_batch(user=user, batch=batch)

    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE

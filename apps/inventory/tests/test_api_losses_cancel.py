"""
API: «не найден», списание, ремонт и отмена.

Как и в test_api_operations.py, проверяем только связку API и services:
данные доходят, ответ правильный, отказ не меняет данные.
"""
from apps.inventory import services
from apps.inventory.models import HandToolMovement, Tool, ToolMovement


def post(client, url, body):
    return client.post(url, body, content_type="application/json")


# ---------------------------------------------------------------------------
# Не найден
# ---------------------------------------------------------------------------

def test_missing_on_site(admin_client, user, tool, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool], hand_tools=[(stocked_hand_tool, 5)])

    response = post(admin_client, "/api/missing/", {
        "site": site.pk,
        "tools": [tool.pk],
        "hand_tools": [{"hand_tool": stocked_hand_tool.pk, "quantity": 2}],
    })

    assert response.status_code == 201
    tool.refresh_from_db()
    stocked_hand_tool.refresh_from_db()
    assert tool.status == Tool.Status.MISSING
    # Потерянное вычитается из total и из выданного (DECISIONS, раздел 14).
    assert (stocked_hand_tool.total, stocked_hand_tool.issued) == (8, 3)


def test_missing_refused_for_tool_not_on_site(admin_client, tool, site):
    response = post(admin_client, "/api/missing/", {"site": site.pk, "tools": [tool.pk]})

    assert response.status_code == 400
    assert "нельзя отметить не найденным" in response.json()["errors"][0]


# ---------------------------------------------------------------------------
# Списание
# ---------------------------------------------------------------------------

def test_write_off_from_warehouse_without_site(admin_client, tool, stocked_hand_tool):
    response = post(admin_client, "/api/write-off/", {
        "tools": [tool.pk],
        "hand_tools": [{"hand_tool": stocked_hand_tool.pk, "quantity": 3}],
        "note": "сломан",
    })

    assert response.status_code == 201
    tool.refresh_from_db()
    stocked_hand_tool.refresh_from_db()
    assert tool.status == Tool.Status.WRITTEN_OFF
    assert stocked_hand_tool.total == 7
    assert ToolMovement.objects.get(batch=response.json()["batch"]).site is None


def test_write_off_with_explicit_null_site_is_warehouse(admin_client, tool):
    response = post(admin_client, "/api/write-off/", {"site": None, "tools": [tool.pk]})

    assert response.status_code == 201


def test_write_off_from_site(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    response = post(admin_client, "/api/write-off/", {"site": site.pk, "tools": [tool.pk]})

    assert response.status_code == 201
    tool.refresh_from_db()
    assert tool.status == Tool.Status.WRITTEN_OFF


def test_write_off_refused_for_issued_tool_from_warehouse(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    response = post(admin_client, "/api/write-off/", {"tools": [tool.pk]})

    assert response.status_code == 400
    assert "нельзя списать" in response.json()["errors"][0]


# ---------------------------------------------------------------------------
# Ремонт
# ---------------------------------------------------------------------------

def test_servicing_round_trip(admin_client, tool):
    sent = post(admin_client, "/api/servicing/", {"tools": [tool.pk]})
    assert sent.status_code == 201
    tool.refresh_from_db()
    assert tool.status == Tool.Status.SERVICING

    back = post(admin_client, "/api/receive-from-servicing/", {"tools": [tool.pk]})
    assert back.status_code == 201
    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE


def test_servicing_from_site(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    response = post(admin_client, "/api/servicing/", {"site": site.pk, "tools": [tool.pk]})

    assert response.status_code == 201
    tool.refresh_from_db()
    assert tool.status == Tool.Status.SERVICING


def test_servicing_refused_for_issued_tool_from_warehouse(admin_client, user, tool, site):
    services.issue_to_site(user=user, site=site, tools=[tool])

    response = post(admin_client, "/api/servicing/", {"tools": [tool.pk]})

    assert response.status_code == 400
    assert "нельзя отправить в ремонт" in response.json()["errors"][0]


# ---------------------------------------------------------------------------
# Отмена набора
# ---------------------------------------------------------------------------

def test_cancel_batch(admin_client, admin_user, tool, site):
    batch = post(admin_client, "/api/issue/", {"site": site.pk, "tools": [tool.pk]}).json()["batch"]

    response = post(admin_client, "/api/cancel-batch/", {"batch": batch})

    assert response.status_code == 200
    assert response.json() == {"batch": batch, "cancelled": True}
    tool.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE
    row = ToolMovement.objects.get(batch=batch)
    assert row.is_cancelled is True
    assert row.cancelled_by == admin_user


def test_cancel_batch_refused_if_not_last_operation(admin_client, tool, site):
    issued = post(admin_client, "/api/issue/", {"site": site.pk, "tools": [tool.pk]}).json()["batch"]
    post(admin_client, "/api/receive/", {"site": site.pk, "tools": [tool.pk]})

    response = post(admin_client, "/api/cancel-batch/", {"batch": issued})

    assert response.status_code == 400
    assert "только последнюю" in response.json()["errors"][0]
    assert ToolMovement.objects.get(batch=issued).is_cancelled is False


def test_cancel_unknown_batch_is_refused(admin_client):
    response = post(admin_client, "/api/cancel-batch/", {"batch": "11111111-1111-1111-1111-111111111111"})

    assert response.status_code == 400
    assert "Набор не найден" in response.json()["errors"][0]


def test_cancel_batch_needs_valid_uuid(admin_client):
    assert post(admin_client, "/api/cancel-batch/", {"batch": "не-uuid"}).status_code == 400


# ---------------------------------------------------------------------------
# Отмена одной строки набора
# ---------------------------------------------------------------------------

def test_cancel_one_row_of_a_set(admin_client, user, category, tool, site):
    other = services.register_tool(user=user, name="Дрель", category=category)
    post(admin_client, "/api/issue/", {"site": site.pk, "tools": [tool.pk, other.pk]})
    wrong_row = ToolMovement.objects.get(tool=tool, type="issued")

    response = post(admin_client, "/api/cancel-movement/", {"kind": "tool", "id": wrong_row.pk})

    assert response.status_code == 200
    tool.refresh_from_db()
    other.refresh_from_db()
    assert tool.status == Tool.Status.AVAILABLE  # ошибочная позиция вернулась на склад
    assert other.status == Tool.Status.ISSUED    # остальной набор не тронут


def test_cancel_hand_tool_row(admin_client, user, stocked_hand_tool, site):
    services.issue_to_site(user=user, site=site, hand_tools=[(stocked_hand_tool, 4)])
    row = HandToolMovement.objects.get(hand_tool=stocked_hand_tool, type="issued")

    response = post(admin_client, "/api/cancel-movement/", {"kind": "hand_tool", "id": row.pk})

    assert response.status_code == 200
    stocked_hand_tool.refresh_from_db()
    assert stocked_hand_tool.issued == 0


def test_cancel_added_row_is_refused(admin_client, tool):
    row = ToolMovement.objects.get(tool=tool, type="added")

    response = post(admin_client, "/api/cancel-movement/", {"kind": "tool", "id": row.pk})

    assert response.status_code == 400
    assert "постановку на баланс отменять нельзя" in response.json()["errors"][0]


def test_cancel_movement_not_found_and_bad_kind(admin_client):
    assert post(admin_client, "/api/cancel-movement/", {"kind": "tool", "id": 999999}).status_code == 404
    assert post(admin_client, "/api/cancel-movement/", {"kind": "other", "id": 1}).status_code == 400

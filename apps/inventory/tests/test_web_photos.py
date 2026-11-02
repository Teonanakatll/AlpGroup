"""Фото штучных позиций: загрузка при постановке на баланс и на странице позиции."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.inventory import services
from apps.inventory.models import Tool, ToolPhoto


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path          # файлы тестов не попадают в настоящую папку media/


def png(name="a.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def test_first_photo_becomes_main_second_does_not(tool):
    services.add_tool_photos(tool=tool, images=[png("1.png"), png("2.png")])

    assert list(tool.photos.order_by("pk").values_list("is_main", flat=True)) == [True, False]
    services.add_tool_photos(tool=tool, images=[png("3.png")])
    assert tool.photos.filter(is_main=True).count() == 1


def test_set_main_and_delete_main_promotes_another(tool):
    first, second = services.add_tool_photos(tool=tool, images=[png("1.png"), png("2.png")])

    services.set_main_photo(photo=second)
    first.refresh_from_db(), second.refresh_from_db()
    assert (first.is_main, second.is_main) == (False, True)

    services.delete_photo(photo=second)
    first.refresh_from_db()
    assert first.is_main is True and tool.photos.count() == 1


def test_add_page_saves_photo_for_all_new_tools(admin_client, category):
    admin_client.post("/operations/add/", {"kind": "tool", "name": "Дрель", "category": category.pk,
                                           "quantity": 2, "photo": png()})

    photos = ToolPhoto.objects.filter(tool__name="Дрель")
    assert photos.count() == 2 and all(p.is_main for p in photos)
    assert len({p.image.name for p in photos}) == 1          # файл один на обе штуки


def test_add_page_rejects_non_image(admin_client, category):
    bad = SimpleUploadedFile("x.png", b"not an image", content_type="image/png")

    response = admin_client.post("/operations/add/", {"kind": "tool", "name": "Дрель",
                                                      "category": category.pk, "quantity": 1, "photo": bad})

    assert response.status_code == 200 and Tool.objects.count() == 0


def test_upload_several_photos_on_position_page(admin_client, tool):
    response = admin_client.post(f"/inventory/tool/{tool.pk}/photos/", {"photos": [png("1.png"), png("2.png")]})

    assert response.status_code == 302
    assert tool.photos.count() == 2
    html = admin_client.get(f"/inventory/tool/{tool.pk}/").content.decode()
    assert "Главное" in html and "Сделать главным" in html


def test_photo_actions_via_web(admin_client, tool):
    first, second = services.add_tool_photos(tool=tool, images=[png("1.png"), png("2.png")])

    admin_client.post(f"/inventory/photo/{second.pk}/main/")
    second.refresh_from_db()
    assert second.is_main is True

    admin_client.post(f"/inventory/photo/{second.pk}/delete/")
    assert tool.photos.count() == 1 and tool.photos.get().is_main is True


def test_photo_actions_need_login_and_post(client, admin_client, tool):
    photo = services.add_tool_photos(tool=tool, images=[png()])[0]

    assert client.post(f"/inventory/photo/{photo.pk}/delete/").status_code == 302
    assert admin_client.get(f"/inventory/photo/{photo.pk}/delete/").status_code == 405
    assert tool.photos.count() == 1

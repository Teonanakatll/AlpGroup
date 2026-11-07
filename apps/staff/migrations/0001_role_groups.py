"""Группы ролей (SPEC, разд. 7.1). Права проверяет apps/staff/roles.py по членству в группе."""
from django.db import migrations

GROUP_NAMES = ["Администратор", "Кладовщик", "Ответственное лицо", "Наблюдатель"]


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in GROUP_NAMES:
        Group.objects.get_or_create(name=name)


def delete_groups(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=GROUP_NAMES).delete()


class Migration(migrations.Migration):
    dependencies = [("auth", "0012_alter_user_first_name_max_length")]
    operations = [migrations.RunPython(create_groups, delete_groups)]

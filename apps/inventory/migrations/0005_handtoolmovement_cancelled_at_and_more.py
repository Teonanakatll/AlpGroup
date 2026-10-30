import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0004_handtoolmovement_batch_tool_current_site_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='handtoolmovement',
            name='cancelled_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Когда отменена'),
        ),
        migrations.AddField(
            model_name='handtoolmovement',
            name='cancelled_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Кто отменил'),
        ),
        migrations.AddField(
            model_name='toolmovement',
            name='cancelled_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Когда отменена'),
        ),
        migrations.AddField(
            model_name='toolmovement',
            name='cancelled_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Кто отменил'),
        ),
    ]

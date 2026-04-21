from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0029_add_metro_stations'),
    ]

    operations = [
        migrations.CreateModel(
            name='ApiActionLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('actor_role', models.CharField(choices=[('system', 'System'), ('admin', 'Admin'), ('manager', 'Manager'), ('applicant', 'Applicant'), ('user', 'User')], default='system', max_length=20)),
                ('method', models.CharField(max_length=10)),
                ('path', models.CharField(max_length=255)),
                ('endpoint', models.CharField(blank=True, max_length=120)),
                ('action', models.CharField(max_length=120)),
                ('success', models.BooleanField(default=True)),
                ('status_code', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('before_data', models.JSONField(blank=True, default=dict)),
                ('after_data', models.JSONField(blank=True, default=dict)),
                ('meta', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='api_action_logs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Лог API-действия',
                'verbose_name_plural': 'Логи API-действий',
                'ordering': ['-created_at'],
            },
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0038_alter_apiactionlog_actor_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='userdocument',
            name='driver_categories',
            field=models.CharField(blank=True, max_length=64, verbose_name='Категории ВУ'),
        ),
    ]

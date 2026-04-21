from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0020_add_interview'),
    ]

    operations = [
        migrations.AddField(
            model_name='calendarnote',
            name='note_time',
            field=models.TimeField(blank=True, null=True, verbose_name='Время'),
        ),
    ]

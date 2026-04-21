from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0021_calendarnote_note_time'),
    ]

    operations = [
        migrations.AddField(
            model_name='interview',
            name='reminded_1d',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='interview',
            name='reminded_1h',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='interview',
            name='reminded_now',
            field=models.BooleanField(default=False),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0022_interview_reminder_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='calendarnote',
            name='reminded',
            field=models.BooleanField(default=False),
        ),
    ]

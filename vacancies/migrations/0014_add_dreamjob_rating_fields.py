from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vacancies', '0013_add_employer_rating_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='employer',
            name='dreamjob_rating',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='employer',
            name='dreamjob_rating_raw',
            field=models.CharField(max_length=128, blank=True),
        ),
        migrations.AddField(
            model_name='employer',
            name='dreamjob_rating_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

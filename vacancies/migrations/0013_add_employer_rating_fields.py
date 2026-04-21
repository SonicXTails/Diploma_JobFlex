from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vacancies', '0012_add_review_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='employer',
            name='hh_rating',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='employer',
            name='rating_raw',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='employer',
            name='rating_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('vacancies', '0010_employer_hh_rating_employer_rating_raw_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='employer',
            name='hh_rating',
        ),
        migrations.RemoveField(
            model_name='employer',
            name='rating_raw',
        ),
        migrations.RemoveField(
            model_name='employer',
            name='rating_updated_at',
        ),
    ]

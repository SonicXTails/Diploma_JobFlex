from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("vacancies", "0008_employer_vacancy_employer"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="employer",
            name="primary_rating",
        ),
        migrations.RemoveField(
            model_name="employer",
            name="rating_sources",
        ),
        migrations.RemoveField(
            model_name="employer",
            name="rating_updated_at",
        ),
        migrations.AlterModelOptions(
            name="employer",
            options={"ordering": ("name",)},
        ),
    ]

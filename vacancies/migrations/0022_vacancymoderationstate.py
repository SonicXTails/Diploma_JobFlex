from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("vacancies", "0021_alter_bookmark_id_alter_employer_id_alter_hharea_id_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="VacancyModerationState",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("new", "Новая"), ("in_work", "В работе"), ("waiting", "Ожидание")], default="new", max_length=16)),
                ("note", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("moderator", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="vacancy_moderation_states", to="auth.user")),
                ("vacancy", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="moderation_states", to="vacancies.vacancy")),
            ],
            options={
                "verbose_name": "Состояние модерации вакансии",
                "verbose_name_plural": "Состояния модерации вакансий",
                "ordering": ("-updated_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="vacancymoderationstate",
            constraint=models.UniqueConstraint(fields=("vacancy", "moderator"), name="uniq_vacancy_moderator_state"),
        ),
    ]

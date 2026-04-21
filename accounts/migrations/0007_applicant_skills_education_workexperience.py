from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_applicant_new_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='applicant',
            name='skills',
            field=models.JSONField(blank=True, default=list, verbose_name='Навыки'),
        ),
        migrations.CreateModel(
            name='Education',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('level', models.CharField(
                    choices=[
                        ('secondary', 'Среднее'),
                        ('vocational', 'Среднее специальное'),
                        ('incomplete_higher', 'Неоконченное высшее'),
                        ('higher', 'Высшее'),
                        ('bachelor', 'Бакалавр'),
                        ('master', 'Магистр'),
                        ('candidate', 'Кандидат наук'),
                        ('doctor', 'Доктор наук'),
                    ],
                    max_length=30,
                    verbose_name='Уровень образования',
                )),
                ('institution', models.CharField(max_length=255, verbose_name='Учебное заведение')),
                ('graduation_year', models.IntegerField(blank=True, null=True, verbose_name='Год выпуска/окончания')),
                ('faculty', models.CharField(blank=True, max_length=255, verbose_name='Факультет')),
                ('specialization', models.CharField(blank=True, max_length=255, verbose_name='Специализация')),
                ('order', models.PositiveSmallIntegerField(default=0, verbose_name='Порядок')),
                ('applicant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='educations',
                    to='accounts.applicant',
                )),
            ],
            options={'verbose_name': 'Образование', 'verbose_name_plural': 'Образование', 'ordering': ['order']},
        ),
        migrations.CreateModel(
            name='WorkExperience',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('company', models.CharField(max_length=255, verbose_name='Компания')),
                ('position', models.CharField(max_length=255, verbose_name='Должность')),
                ('start_month', models.IntegerField(
                    blank=True, null=True,
                    choices=[(1,'Январь'),(2,'Февраль'),(3,'Март'),(4,'Апрель'),
                             (5,'Май'),(6,'Июнь'),(7,'Июль'),(8,'Август'),
                             (9,'Сентябрь'),(10,'Октябрь'),(11,'Ноябрь'),(12,'Декабрь')],
                    verbose_name='Месяц начала',
                )),
                ('start_year', models.IntegerField(blank=True, null=True, verbose_name='Год начала')),
                ('end_month', models.IntegerField(
                    blank=True, null=True,
                    choices=[(1,'Январь'),(2,'Февраль'),(3,'Март'),(4,'Апрель'),
                             (5,'Май'),(6,'Июнь'),(7,'Июль'),(8,'Август'),
                             (9,'Сентябрь'),(10,'Октябрь'),(11,'Ноябрь'),(12,'Декабрь')],
                    verbose_name='Месяц окончания',
                )),
                ('end_year', models.IntegerField(blank=True, null=True, verbose_name='Год окончания')),
                ('is_current', models.BooleanField(default=False, verbose_name='Работаю сейчас')),
                ('responsibilities', models.TextField(blank=True, verbose_name='Обязанности и достижения')),
                ('order', models.PositiveSmallIntegerField(default=0, verbose_name='Порядок')),
                ('applicant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='work_experiences',
                    to='accounts.applicant',
                )),
            ],
            options={'verbose_name': 'Опыт работы', 'verbose_name_plural': 'Опыт работы', 'ordering': ['order']},
        ),
    ]

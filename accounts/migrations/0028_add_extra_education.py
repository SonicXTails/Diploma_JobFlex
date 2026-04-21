from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0027_useruipreference'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExtraEducation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, verbose_name='Название')),
                ('description', models.TextField(blank=True, verbose_name='Описание')),
                ('order', models.PositiveSmallIntegerField(default=0, verbose_name='Порядок')),
                ('applicant', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='extra_educations',
                    to='accounts.applicant',
                )),
            ],
            options={
                'verbose_name': 'Доп. образование',
                'verbose_name_plural': 'Доп. образование',
                'ordering': ['order'],
            },
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vacancies', '0011_remove_employer_rating_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='Review',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('author', models.CharField(blank=True, max_length=128)),
                ('text', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('vacancy', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='reviews', to='vacancies.vacancy')),
            ],
            options={
                'ordering': ('-created_at',),
            },
        ),
    ]

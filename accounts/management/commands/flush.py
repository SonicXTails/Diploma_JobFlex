from django.contrib.auth import get_user_model
from django.core.management.commands.flush import Command as DjangoFlushCommand


class Command(DjangoFlushCommand):

    def handle(self, *args, **options):
        super().handle(*args, **options)

        User = get_user_model()
        db_alias = options.get('database', 'default')

        user, created = User.objects.using(db_alias).get_or_create(
            username='aedgy',
            defaults={
                'is_staff': True,
                'is_superuser': True,
                'is_active': True,
                'email': '',
            },
        )

        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password('aedgy123')
        user.save(using=db_alias)

        from accounts.models import Administrator

        Administrator.objects.using(db_alias).get_or_create(user=user)

        if created:
            self.stdout.write(self.style.SUCCESS('Default admin created: aedgy'))
        else:
            self.stdout.write(self.style.SUCCESS('Default admin refreshed: aedgy'))

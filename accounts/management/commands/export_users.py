from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from accounts.models import Applicant, Manager


class Command(BaseCommand):
    help = "Export all users with applicant and manager data"

    def handle(self, *args, **kwargs):

        users = User.objects.all()

        for u in users:
            print("\n" + "=" * 80)
            print("USER ID:", u.id)

            for k, v in u.__dict__.items():
                if not k.startswith("_"):
                    print(f"{k}: {v}")

            # Applicant
            if hasattr(u, "applicant"):
                print("\n--- APPLICANT ---")
                a = u.applicant
                for k, v in a.__dict__.items():
                    if not k.startswith("_"):
                        print(f"{k}: {v}")
            else:
                print("\n--- APPLICANT: NULL ---")

            # Manager
            if hasattr(u, "manager"):
                print("\n--- MANAGER ---")
                m = u.manager
                for k, v in m.__dict__.items():
                    if not k.startswith("_"):
                        print(f"{k}: {v}")
            else:
                print("\n--- MANAGER: NULL ---")
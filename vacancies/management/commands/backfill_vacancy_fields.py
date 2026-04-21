from django.core.management.base import BaseCommand

from vacancies.models import Vacancy


class Command(BaseCommand):
    help = "Backfill `salary_*`, `key_skills_text`, schedule/employment/label fields from `raw_json`"

    def handle(self, *args, **options):
        updated = 0
        qs = Vacancy.objects.all()
        for v in qs:
            changed = False
            raw = v.raw_json if isinstance(v.raw_json, dict) else {}

            sal = raw.get("salary") or {}
            sf = sal.get("from")
            st = sal.get("to")
            cur = sal.get("currency") or ""

            if v.salary_from != sf:
                v.salary_from = sf
                changed = True
            if v.salary_to != st:
                v.salary_to = st
                changed = True
            if v.salary_currency != cur:
                v.salary_currency = cur
                changed = True

            ks = raw.get("key_skills") or []
            if isinstance(ks, list):
                text = ", ".join([str(s.get("name")) for s in ks if isinstance(s, dict) and s.get("name")])
            else:
                text = ""

            if v.key_skills_text != text:
                v.key_skills_text = text
                changed = True

            # schedule / employment / label fields
            sched = raw.get("schedule") or {}
            new_schedule_id = str(sched.get("id") or "")
            new_schedule_name = str(sched.get("name") or "")
            emp = raw.get("employment") or {}
            new_employment_id = str(emp.get("id") or "")
            new_employment_name = str(emp.get("name") or "")
            ef = raw.get("employment_form") or {}
            new_ef_id = str(ef.get("id") or "")
            new_ef_name = str(ef.get("name") or "")
            new_intern = bool(raw.get("internship"))
            new_temp = bool(raw.get("accept_temporary"))
            new_incomplete = bool(raw.get("accept_incomplete_resumes"))
            new_kids = bool(raw.get("accept_kids"))

            for attr, new_val in [
                ("schedule_id", new_schedule_id),
                ("schedule_name", new_schedule_name),
                ("employment_id", new_employment_id),
                ("employment_name", new_employment_name),
                ("employment_form_id", new_ef_id),
                ("employment_form_name", new_ef_name),
                ("is_internship", new_intern),
                ("accept_temporary", new_temp),
                ("accept_incomplete_resumes", new_incomplete),
                ("accept_kids", new_kids),
            ]:
                if getattr(v, attr) != new_val:
                    setattr(v, attr, new_val)
                    changed = True

            if changed:
                v.save(update_fields=[
                    "salary_from", "salary_to", "salary_currency", "key_skills_text",
                    "schedule_id", "schedule_name",
                    "employment_id", "employment_name",
                    "employment_form_id", "employment_form_name",
                    "is_internship", "accept_temporary",
                    "accept_incomplete_resumes", "accept_kids",
                ])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Updated={updated}"))

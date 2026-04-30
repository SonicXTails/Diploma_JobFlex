"""
Fetch full vacancy details from HH API (/vacancies/{id}) for all vacancies
whose raw_json is missing a description, then update the stored raw_json.

Usage:
    python manage.py backfill_descriptions           # all vacancies missing description
    python manage.py backfill_descriptions --id 539  # single vacancy by local DB id
    python manage.py backfill_descriptions --limit 50 --delay 0.5
"""
import json
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from django.core.management.base import BaseCommand

from vacancies.models import Vacancy
from vacancies.hh_client import hh_openapi_headers


class Command(BaseCommand):
    help = "Backfill vacancy descriptions from HH detail API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--id",
            type=int,
            default=None,
            help="Local DB id of a single vacancy to update",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max number of vacancies to process (0 = unlimited)",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=0.4,
            help="Seconds to sleep between API requests (default 0.4)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-fetch even if description already exists",
        )

    def handle(self, *args, **options):
        single_id = options["id"]
        limit = options["limit"]
        delay = max(0.1, options["delay"])
        force = options["force"]

        if single_id:
            qs = Vacancy.objects.filter(id=single_id)
        else:
            qs = Vacancy.objects.all()
            if not force:
                # Only vacancies whose raw_json description is empty/missing
                qs = [v for v in qs if not (v.raw_json or {}).get("description")]
            else:
                qs = list(qs)

        if not qs:
            self.stdout.write(self.style.WARNING("No vacancies to process."))
            return

        if limit:
            qs = qs[:limit]

        total = len(qs)
        self.stdout.write(f"Processing {total} vacancies (delay={delay}s)…")

        ok = 0
        failed = 0

        for i, vacancy in enumerate(qs, start=1):
            hh_id = (vacancy.raw_json or {}).get("id") or vacancy.external_id
            if not hh_id:
                self.stdout.write(self.style.WARNING(f"  [{i}/{total}] DB#{vacancy.id} — no HH id, skipping"))
                failed += 1
                continue

            url = f"https://api.hh.ru/vacancies/{hh_id}"
            try:
                req = Request(url, headers=hh_openapi_headers())
                with urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except HTTPError as e:
                self.stdout.write(self.style.ERROR(
                    f"  [{i}/{total}] DB#{vacancy.id} HH#{hh_id} — HTTP {e.code}"
                ))
                failed += 1
                if e.code == 429:
                    self.stdout.write("  Rate-limited — sleeping 10 s…")
                    time.sleep(10)
                continue
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"  [{i}/{total}] DB#{vacancy.id} HH#{hh_id} — {e}"
                ))
                failed += 1
                continue

            desc = data.get("description", "")
            key_skills = data.get("key_skills", [])
            branded = data.get("branded_description", "")

            # Merge detail data into raw_json (detail is a superset of list item)
            merged = {**(vacancy.raw_json or {}), **data}
            vacancy.raw_json = merged
            vacancy.description = desc
            vacancy.branded_description = branded
            vacancy.key_skills_text = ", ".join(
                s.get("name", "") for s in key_skills if isinstance(s, dict)
            )
            vacancy.save(update_fields=["raw_json", "description",
                                        "branded_description", "key_skills_text"])

            desc_preview = desc[:60].replace("\n", " ") if desc else "(empty)"
            branded_mark = f"  branded={len(branded)}ch" if branded else ""
            self.stdout.write(
                f"  [{i}/{total}] DB#{vacancy.id} HH#{hh_id} — "
                f"desc={len(desc)}ch{branded_mark}  '{desc_preview}…'"
            )
            ok += 1

            if i < total:
                time.sleep(delay)

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. OK={ok}  Failed={failed}  Total={total}"
        ))

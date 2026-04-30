import json
import sys
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from vacancies.models import Vacancy, Employer
from vacancies.hh_client import hh_openapi_headers




class Command(BaseCommand):
    LAST_TS_CACHE_KEY = "hh_last_published_at_iso"
    def _console_safe(self, message: str) -> str:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        return message.encode(enc, errors="replace").decode(enc)

    help = "Fetch vacancies from HH API and save to database"
    DEFAULT_TEXTS = [
        "продавец",
        "кассир",
        "водитель",
        "бухгалтер",
        "менеджер",
        "администратор",
        "python",
    ]

    def add_arguments(self, parser):
        parser.add_argument("--text", default="", help="Search text (optional)")
        parser.add_argument(
            "--texts",
            default="",
            help="Comma-separated texts, e.g. 'продавец,бухгалтер,python'",
        )
        parser.add_argument(
            "--use-default-texts",
            action="store_true",
            help="Use built-in mix of IT and non-IT queries",
        )
        parser.add_argument("--pages", type=int, default=5, help="Max pages per query")
        parser.add_argument("--per-page", type=int, default=100, help="Items per page (max 100)")
        parser.add_argument("--area", type=int, default=None, help="HH area id (optional)")

    def handle(self, *args, **options):
        text = (options["text"] or "").strip()
        texts = (options["texts"] or "").strip()
        use_default_texts = options["use_default_texts"]
        pages = max(1, options["pages"])
        per_page = min(max(1, options["per_page"]), 100)
        area = options["area"]

        query_list = self._build_query_list(text, texts, use_default_texts)
        incremental_mode = (not text and not texts and not use_default_texts and area is None)
        since_dt = self._read_cursor() if incremental_mode else None

        created_total = 0
        updated_total = 0
        newest_seen = since_dt

        for query in query_list:
            query_title = query or "<all>"
            self.stdout.write(self._console_safe(f"Query: {query_title}"))

            first_page_payload = self._fetch_page(query, area, per_page, 0, since_dt=since_dt)
            total_pages = min(first_page_payload.get("pages", 1), pages)

            first_items = first_page_payload.get("items", [])
            if incremental_mode and not self._has_new_ids(first_items):
                self.stdout.write(self._console_safe("  Page 1: no new ids, stop incremental scan"))
                continue
            created_count, updated_count = self._save_items(first_items)
            newest_seen = self._max_dt(newest_seen, self._max_published(first_items))
            created_total += created_count
            updated_total += updated_count
            self.stdout.write(self._console_safe(
                f"  Page 1/{total_pages}: created={created_count}, updated={updated_count}"
            ))

            for page in range(1, total_pages):
                payload = self._fetch_page(query, area, per_page, page, since_dt=since_dt)
                items = payload.get("items", [])
                if not items:
                    break
                if since_dt and not self._has_newer(items, since_dt):
                    break
                if incremental_mode and not self._has_new_ids(items):
                    break

                created_count, updated_count = self._save_items(items)
                newest_seen = self._max_dt(newest_seen, self._max_published(items))
                created_total += created_count
                updated_total += updated_count
                self.stdout.write(self._console_safe(
                    f"  Page {page + 1}/{total_pages}: created={created_count}, updated={updated_count}"
                ))

        if incremental_mode and newest_seen:
            self._write_cursor(newest_seen)

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created={created_total}, Updated={updated_total}, Total in DB={Vacancy.objects.count()}"
        ))

    def _build_query_list(self, text, texts, use_default_texts):
        if use_default_texts:
            return self.DEFAULT_TEXTS

        if texts:
            values = [value.strip() for value in texts.split(",") if value.strip()]
            return values or [""]

        if text:
            return [text]

        return [""]

    def _fetch_page(self, query, area, per_page, page, since_dt=None):
        params = {
            "page": page,
            "per_page": per_page,
            "order_by": "publication_time",
        }
        if query:
            params["text"] = query
        if area:
            params["area"] = area
        if since_dt:
            params["date_from"] = since_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        return self._fetch("https://api.hh.ru/vacancies", params)

    def _fetch(self, base_url, params):
        url = f"{base_url}?{urlencode(params)}"
        request = Request(url, headers=hh_openapi_headers())
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    @transaction.atomic
    def _save_items(self, items):
        created_count = 0
        updated_count = 0

        for item in items:
            area = item.get("area") or {}
            country, region = self._extract_location(area)
            experience = item.get("experience") or {}
            flags = self._work_format_flags(item)
            work_format = self._primary_work_format(flags)
            # Prepare employer normalization: create or update Employer when possible
            emp_payload = item.get('employer') or {}
            employer_obj = None
            hh_id = emp_payload.get('id') if isinstance(emp_payload, dict) else None
            if hh_id:
                try:
                    employer_obj, created = Employer.objects.get_or_create(hh_id=str(hh_id), defaults={
                        'name': emp_payload.get('name','') or '',
                        'raw': emp_payload or {},
                    })
                    # keep raw up-to-date (merge simple replacement)
                    if not created:
                        employer_obj.raw = emp_payload or {}
                        employer_obj.name = emp_payload.get('name','') or employer_obj.name
                except Exception:
                    employer_obj = None

            defaults = {
                "title": item.get("name", ""),
                "company": (item.get("employer") or {}).get("name", ""),
                "country": country,
                "region": region,
                "experience_id": str(experience.get("id") or ""),
                "experience_name": str(experience.get("name") or ""),
                "work_format": work_format,
                "is_remote": flags["remote"],
                "is_hybrid": flags["hybrid"],
                "is_onsite": flags["onsite"],
                "url": item.get("alternate_url", ""),
                "published_at": self._parse_dt(item.get("published_at")),
                "raw_json": item,
                "salary_from": (item.get("salary") or {}).get("from"),
                "salary_to": (item.get("salary") or {}).get("to"),
                "salary_currency": (item.get("salary") or {}).get("currency") or "",
                "salary_period": "month",  # HH salaries are always per-month
                "key_skills_text": ", ".join([
                    str(s.get("name")) for s in (item.get("key_skills") or []) if isinstance(s, dict)
                ]),
                # schedule / employment / label fields
                "schedule_id": str((item.get("schedule") or {}).get("id") or ""),
                "schedule_name": str((item.get("schedule") or {}).get("name") or ""),
                "employment_id": str((item.get("employment") or {}).get("id") or ""),
                "employment_name": str((item.get("employment") or {}).get("name") or ""),
                "employment_form_id": str((item.get("employment_form") or {}).get("id") or ""),
                "employment_form_name": str((item.get("employment_form") or {}).get("name") or ""),
                "is_internship": bool(item.get("internship")),
                "accept_temporary": bool(item.get("accept_temporary")),
                "accept_incomplete_resumes": bool(item.get("accept_incomplete_resumes")),
                "accept_kids": bool(item.get("accept_kids")),
            }

            # attach employer instance if we found/created one
            if employer_obj:
                defaults['employer'] = employer_obj

            vacancy_obj, created = Vacancy.objects.update_or_create(
                external_id=str(item.get("id")),
                defaults=defaults,
            )
            created_count += int(created)
            updated_count += int(not created)
            # Description fetching is handled by backfill_descriptions_task (Celery beat)
            # which spaces requests at 0.5 s intervals to avoid HH rate-limiting.

        return created_count, updated_count

    def _extract_location(self, area):
        name = (area or {}).get("name") or ""
        if name in {"Казахстан", "Беларусь", "Узбекистан", "Грузия", "Армения", "Кыргызстан", "Азербайджан"}:
            return name, ""
        return "Россия", name

    def _work_format_flags(self, item):
        formats = item.get("work_format") or []
        if isinstance(formats, dict):
            formats = [formats]

        format_ids = {
            str(format_item.get("id", "")).lower()
            for format_item in formats
            if isinstance(format_item, dict)
        }
        schedule_id = ((item.get("schedule") or {}).get("id") or "").lower()
        label = (item.get("name") or "").lower()

        is_remote = "remote" in format_ids or schedule_id == "remote" or "удален" in label
        is_hybrid = "hybrid" in format_ids or "гибрид" in label
        is_onsite = "on_site" in format_ids or "onsite" in format_ids or "на месте" in label

        if not (is_remote or is_hybrid or is_onsite):
            is_onsite = True

        return {
            "remote": is_remote,
            "hybrid": is_hybrid,
            "onsite": is_onsite,
        }

    def _primary_work_format(self, flags):
        if flags["remote"]:
            return Vacancy.WorkFormat.REMOTE
        if flags["hybrid"]:
            return Vacancy.WorkFormat.HYBRID
        return Vacancy.WorkFormat.ONSITE

    def _parse_dt(self, value):
        if not value:
            return timezone.now()
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _max_published(self, items):
        best = None
        for item in items or []:
            dt = self._parse_dt(item.get("published_at"))
            best = self._max_dt(best, dt)
        return best

    def _max_dt(self, a, b):
        if a is None:
            return b
        if b is None:
            return a
        return a if a >= b else b

    def _has_newer(self, items, since_dt):
        for item in items or []:
            if self._parse_dt(item.get("published_at")) > since_dt:
                return True
        return False

    def _read_cursor(self):
        raw = (cache.get(self.LAST_TS_CACHE_KEY) or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    def _write_cursor(self, dt):
        cache.set(self.LAST_TS_CACHE_KEY, dt.astimezone(timezone.utc).isoformat(), timeout=60 * 60 * 24 * 30)

    def _has_new_ids(self, items):
        ids = [str(item.get("id") or "") for item in (items or []) if item.get("id")]
        if not ids:
            return False
        existing_ids = set(
            Vacancy.objects.filter(external_id__in=ids).values_list("external_id", flat=True)
        )
        return any(item_id not in existing_ids for item_id in ids)

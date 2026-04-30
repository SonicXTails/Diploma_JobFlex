from datetime import datetime, timedelta
from urllib.parse import urlparse, quote_plus, quote
import sys

import requests
import logging
from django.core.management.base import BaseCommand
from django.core.cache import cache
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from vacancies.models import Vacancy

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Fetch vacancies from trudvsem open API and save to database"
    LAST_TS_CACHE_KEY = "trudvsem_last_modify_at_iso"
    BOOTSTRAP_DONE_CACHE_KEY = "trudvsem_bootstrap_done"

    API_URL = "https://opendata.trudvsem.ru/api/v1/vacancies"

    def _console_safe(self, message: str) -> str:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        return message.encode(enc, errors="replace").decode(enc)

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=200, help="How many records to fetch")
        parser.add_argument("--offset", type=int, default=None, help="Offset for trudvsem API")
        parser.add_argument("--text", default="", help="Optional text filter")

    def handle(self, *args, **options):
        limit = max(1, int(options.get("limit") or 200))
        offset_opt = options.get("offset")
        offset = None if offset_opt is None else max(0, int(offset_opt))
        text = (options.get("text") or "").strip()
        recent_minutes = max(0, int(getattr(settings, "FALLBACK_TRUDVSEM_RECENT_MINUTES", 10)))
        existing_fallback = Vacancy.objects.filter(external_id__startswith="trudvsem-").count()
        bootstrap_done = bool(cache.get(self.BOOTSTRAP_DONE_CACHE_KEY))
        bootstrap_target = 10
        bootstrap_mode = (not bootstrap_done) and existing_fallback < bootstrap_target and offset is None
        recent_mode = (offset is None and recent_minutes > 0 and not bootstrap_mode)
        full_scan_mode = (offset is None and not bootstrap_mode and not recent_mode)
        cutoff = timezone.now() - timedelta(minutes=recent_minutes) if recent_mode else None
        cursor_dt = self._read_cursor() if recent_mode else None
        if cursor_dt:
            cutoff = cursor_dt
        max_pages_cap = max(1, int(getattr(settings, "FALLBACK_TRUDVSEM_MAX_PAGES_PER_RUN", 1000)))
        if bootstrap_mode:
            # First run: ensure at least a small visible dataset.
            limit = max(limit, bootstrap_target - existing_fallback)
        if recent_mode:
            # Incremental mode: fetch ALL pages with new vacancies after cursor/cutoff.
            # The loop stops naturally when a page has no newer rows.
            limit = max(limit, 50000)
        if full_scan_mode:
            # User-requested mode: walk all available pages from the start each run.
            limit = max(limit, 50000)

        self._migrate_legacy_external_ids()
        self._refresh_legacy_logo_quality_once()
        fetched_total = 0
        created_total = 0
        updated_total = 0
        newest_seen = cursor_dt
        current_offset = self._resolve_offset(offset)
        remaining = limit
        max_pages = max_pages_cap if (recent_mode or full_scan_mode) else max(1, (limit + 99) // 100)
        page = 0
        max_offset = 100
        empty_recent_streak = 0
        max_empty_recent_streak = 200
        while remaining > 0:
            page += 1
            page_limit = min(100, remaining)  # trudvsem max page size
            payload = self._fetch(limit=page_limit, offset=current_offset, text=text)
            raw_items = ((payload.get("results") or {}).get("vacancies") or [])
            if page == 1:
                total = int((payload.get("meta") or {}).get("total") or 0)
                if total > 0:
                    max_offset = max(1, min(1000, (total + 99) // 100))
            page_items = []
            for item in raw_items:
                v = item.get("vacancy") if isinstance(item, dict) else None
                if isinstance(v, dict):
                    page_items.append(v)
            got_raw = len(page_items)
            if got_raw == 0:
                break

            if recent_mode:
                page_items = [v for v in page_items if self._is_recent(v, cutoff)]
                if not page_items:
                    empty_recent_streak += 1
                    logger.info(
                        "Работа России: страница=%s offset=%s новых=0 streak=%s",
                        page, current_offset, empty_recent_streak,
                    )
                    current_offset = (current_offset + 1) % max_offset
                    remaining -= got_raw
                    if empty_recent_streak >= max_empty_recent_streak or page >= max_pages:
                        break
                    continue
                empty_recent_streak = 0
                logger.info(
                    "Работа России: страница=%s offset=%s новых=%s",
                    page, current_offset, len(page_items),
                )

            created_page, updated_page = self._save_items(page_items)
            fetched_total += len(page_items)
            created_total += created_page
            updated_total += updated_page
            newest_seen = self._max_dt(newest_seen, self._max_modified(page_items))
            got = got_raw
            current_offset = (current_offset + 1) % max_offset
            remaining -= got
            if got < page_limit or page >= max_pages:
                break
        self._store_offset(current_offset)
        if recent_mode and newest_seen:
            self._write_cursor(newest_seen)

        self.stdout.write(self._console_safe(
            f"trudvsem done. mode={'bootstrap' if bootstrap_mode else 'recent' if recent_mode else 'full' if full_scan_mode else 'cursor'} text={text or '<none>'} offset={offset} fetched={fetched_total} created={created_total} updated={updated_total}"
        ))
        if bootstrap_mode and fetched_total > 0:
            cache.set(self.BOOTSTRAP_DONE_CACHE_KEY, 1, timeout=60 * 60 * 24 * 365)

    def _next_fallback_text(self):
        raw = getattr(settings, "FALLBACK_TRUDVSEM_TEXTS", "")
        texts = [t.strip() for t in str(raw).split(",") if t.strip()]
        if not texts:
            texts = [
                "продавец", "кассир", "водитель", "бухгалтер", "менеджер",
                "администратор", "python", "аналитик", "разработчик",
            ]
        idx = int(cache.get("trudvsem_text_cursor", 0) or 0)
        text = texts[idx % len(texts)]
        cache.set("trudvsem_text_cursor", idx + 1, timeout=60 * 60 * 24 * 30)
        return text

    def _migrate_legacy_external_ids(self):
        """Convert legacy fallback ids from `trudvsem:<id>` to url-safe `trudvsem-<id>`."""
        legacy = list(Vacancy.objects.filter(external_id__startswith="trudvsem:").only("id", "external_id"))
        if not legacy:
            return
        for row in legacy:
            new_ext = row.external_id.replace("trudvsem:", "trudvsem-", 1)
            Vacancy.objects.filter(pk=row.pk).update(external_id=new_ext)
        self.stdout.write(f"trudvsem legacy ids migrated: {len(legacy)}")

    def _resolve_offset(self, offset):
        if offset is not None:
            return max(0, int(offset))
        return int(cache.get("trudvsem_offset_cursor", 0) or 0)

    def _store_offset(self, offset):
        cache.set("trudvsem_offset_cursor", int(offset), timeout=60 * 60 * 24 * 7)

    def _refresh_legacy_logo_quality_once(self):
        cache_key = "trudvsem_logo_quality_refreshed_v2"
        if cache.get(cache_key):
            return
        rows = list(
            Vacancy.objects.filter(external_id__startswith="trudvsem-").only("id", "company", "raw_json")[:2000]
        )
        if not rows:
            cache.set(cache_key, 1, timeout=60 * 60 * 24 * 30)
            return
        to_update = []
        for row in rows:
            raw = row.raw_json if isinstance(row.raw_json, dict) else {}
            emp = raw.get("employer") if isinstance(raw.get("employer"), dict) else {}
            logos = emp.get("logo_urls") if isinstance(emp.get("logo_urls"), dict) else {}
            original = str(logos.get("original") or "")
            if ("favicon.yandex.net/favicon/" in original and "?size=" in original and logos.get("fallback_svg")):
                continue
            company_site = self._as_text(emp.get("alternate_url"))
            company_name = self._as_text(emp.get("name")) or self._as_text(row.company)
            emp["logo_urls"] = self._logo_urls(company_site, company_name)
            raw["employer"] = emp
            row.raw_json = raw
            to_update.append(row)
        if to_update:
            Vacancy.objects.bulk_update(to_update, ["raw_json"], batch_size=200)
        cache.set(cache_key, 1, timeout=60 * 60 * 24 * 30)

    def _fetch(self, limit, offset, text):
        params = {"limit": limit, "offset": offset}
        if text:
            params["text"] = text
        try:
            r = requests.get(self.API_URL, params=params, timeout=25)
        except requests.exceptions.RequestException as exc:
            logger.warning("trudvsem request failed: offset=%s limit=%s err=%s", offset, limit, exc)
            return {"results": {"vacancies": []}, "meta": {}}
        if r.status_code >= 500:
            # API can sporadically fail on some offset values; try wrapped page zero.
            params["offset"] = 0
            try:
                r = requests.get(self.API_URL, params=params, timeout=25)
            except requests.exceptions.RequestException as exc:
                logger.warning("trudvsem fallback request failed: offset=0 limit=%s err=%s", limit, exc)
                return {"results": {"vacancies": []}, "meta": {}}
        r.raise_for_status()
        return r.json()

    def _parse_dt(self, value):
        if not value:
            return timezone.now()
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return timezone.now()

    def _is_recent(self, item, cutoff):
        if cutoff is None:
            return True
        dt = self._parse_dt(item.get("date_modify") or item.get("creation-date"))
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt > cutoff

    def _max_modified(self, items):
        best = None
        for item in items or []:
            dt = self._parse_dt(item.get("date_modify") or item.get("creation-date"))
            best = self._max_dt(best, dt)
        return best

    def _max_dt(self, a, b):
        if a is None:
            return b
        if b is None:
            return a
        return a if a >= b else b

    def _read_cursor(self):
        raw = (cache.get(self.LAST_TS_CACHE_KEY) or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    def _write_cursor(self, dt):
        cache.set(self.LAST_TS_CACHE_KEY, dt.isoformat(), timeout=60 * 60 * 24 * 30)

    def _as_text(self, value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            parts = []
            for v in value.values():
                t = self._as_text(v)
                if t:
                    parts.append(t)
            return " ".join(parts).strip()
        if isinstance(value, (list, tuple)):
            parts = []
            for v in value:
                t = self._as_text(v)
                if t:
                    parts.append(t)
            return " ".join(parts).strip()
        return str(value).strip()

    def _domain_from_url(self, url):
        u = self._as_text(url)
        if not u:
            return ""
        if "://" not in u:
            u = "https://" + u
        try:
            host = (urlparse(u).netloc or "").lower()
            if host.startswith("www."):
                host = host[4:]
            return host
        except Exception:
            return ""

    def _logo_urls(self, company_site, company_name):
        # Higher quality logo strategy:
        # - yandex favicon with explicit size for better sharpness;
        # - inline SVG as guaranteed crisp fallback.
        name = (company_name or "Company").strip() or "Company"
        letters = "".join([w[:1] for w in name.split()[:2]]).upper() or name[:1].upper()
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='256' height='256' viewBox='0 0 256 256'>"
            "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
            "<stop offset='0%' stop-color='#C2692A'/>"
            "<stop offset='100%' stop-color='#7D3F1C'/>"
            "</linearGradient></defs>"
            "<rect width='256' height='256' rx='36' fill='url(#g)'/>"
            f"<text x='128' y='145' text-anchor='middle' font-family='Inter,Arial,sans-serif' "
            "font-size='92' font-weight='700' fill='#ffffff'>"
            f"{letters}</text></svg>"
        )
        data_uri = "data:image/svg+xml;utf8," + quote(svg, safe=":/#?&=,+-._~!$'()*[]@")
        domain = self._domain_from_url(company_site)
        if domain:
            yandex_90 = f"https://favicon.yandex.net/favicon/{domain}?size=90&stub=1"
            yandex_240 = f"https://favicon.yandex.net/favicon/{domain}?size=240&stub=1"
            yandex_512 = f"https://favicon.yandex.net/favicon/{domain}?size=512&stub=1"
            return {"90": yandex_90, "240": yandex_240, "original": yandex_512, "fallback_svg": data_uri}
        return {"90": data_uri, "240": data_uri, "original": data_uri}

    def _map_item(self, item):
        ext_id = f"trudvsem-{item.get('id')}"
        title = self._as_text(item.get("job-name"))[:255]
        company = self._as_text((item.get("company") or {}).get("name"))[:255]
        region = self._as_text((item.get("region") or {}).get("name"))[:128]
        url = self._as_text(item.get("vac_url"))
        published_at = self._parse_dt(item.get("date_modify") or item.get("creation-date"))

        salary_from = item.get("salary_min")
        salary_to = item.get("salary_max")
        if not isinstance(salary_from, int):
            salary_from = None
        if not isinstance(salary_to, int):
            salary_to = None

        schedule_name = self._as_text(item.get("schedule"))[:128]
        duty = self._as_text(item.get("duty"))
        requirement = self._as_text(item.get("requirement"))
        requirements = self._as_text(item.get("requirements"))
        description = "\n\n".join([p for p in [duty, requirement, requirements] if p])
        company_site = self._as_text((item.get("company") or {}).get("site"))

        text_blob = " ".join(
            [
                title.lower(),
                schedule_name.lower(),
                duty.lower(),
                requirement.lower(),
                requirements.lower(),
            ]
        )
        is_remote = "удален" in text_blob or "дистан" in text_blob or "remote" in text_blob
        is_hybrid = "гибрид" in text_blob
        is_onsite = not (is_remote or is_hybrid)

        return ext_id, {
            "title": title,
            "company": company,
            "country": "Россия",
            "region": region,
            "experience_id": "",
            "experience_name": "",
            "work_format": (
                Vacancy.WorkFormat.REMOTE
                if is_remote
                else Vacancy.WorkFormat.HYBRID
                if is_hybrid
                else Vacancy.WorkFormat.ONSITE
            ),
            "is_remote": is_remote,
            "is_hybrid": is_hybrid,
            "is_onsite": is_onsite,
            "url": url,
            "published_at": published_at,
            "raw_json": {
                "source": "trudvsem",
                "employer": {
                    "id": self._as_text((item.get("company") or {}).get("companycode")) or ext_id,
                    "name": company,
                    "alternate_url": company_site,
                    "logo_urls": self._logo_urls(company_site, company),
                },
                **item,
            },
            "salary_from": salary_from,
            "salary_to": salary_to,
            "salary_currency": "RUR",
            "salary_period": "month",
            "key_skills_text": "",
            "description": description,
            "schedule_id": "",
            "schedule_name": schedule_name,
            "employment_id": "",
            "employment_name": "",
            "employment_form_id": "",
            "employment_form_name": "",
            "is_internship": False,
            "accept_temporary": False,
            "accept_incomplete_resumes": False,
            "accept_kids": False,
            "is_active": True,
        }

    @transaction.atomic
    def _save_items(self, items):
        if not items:
            return 0, 0

        now = timezone.now()
        mapped = {}
        for item in items:
            if not item.get("id"):
                continue
            ext_id, fields = self._map_item(item)
            mapped[ext_id] = fields

        ext_ids = list(mapped.keys())
        existing = {v.external_id: v for v in Vacancy.objects.filter(external_id__in=ext_ids)}

        to_create = []
        to_update = []
        for ext_id, fields in mapped.items():
            if ext_id in existing:
                obj = existing[ext_id]
                old_raw = obj.raw_json if isinstance(obj.raw_json, dict) else {}
                new_raw = fields.get("raw_json") if isinstance(fields.get("raw_json"), dict) else {}
                if (
                    old_raw.get("date_modify") == new_raw.get("date_modify")
                    and old_raw.get("salary_min") == new_raw.get("salary_min")
                    and old_raw.get("salary_max") == new_raw.get("salary_max")
                    and obj.title == fields.get("title")
                    and obj.url == fields.get("url")
                ):
                    continue
                for k, v in fields.items():
                    setattr(obj, k, v)
                obj.updated_at = now
                to_update.append(obj)
            else:
                to_create.append(Vacancy(external_id=ext_id, created_at=now, updated_at=now, **fields))

        if to_create:
            Vacancy.objects.bulk_create(to_create, batch_size=100)
        if to_update:
            update_fields = list(mapped[next(iter(mapped))].keys()) + ["updated_at"]
            for obj in to_update:
                payload = {name: getattr(obj, name) for name in update_fields}
                Vacancy.objects.filter(pk=obj.pk).update(**payload)

        return len(to_create), len(to_update)


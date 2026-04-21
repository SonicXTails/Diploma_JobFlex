import json
import re
import html as _html_unescape
import time
from datetime import timedelta
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand
from django.db.models import Q as models_Q
from django.utils import timezone

from vacancies.models import Employer

USER_AGENT = 'job-aggregator-diploma/1.0'
_RATING_PAT = r'totalRating["\']?\s*:\s*["\']?([0-5](?:[\.,][0-9]{1,2})?)["\']?'
_DJID_PAT = r'employerDjId["\']?\s*:\s*["\']?(\d+)["\']?'

# ── Defaults ──
DEFAULT_LIMIT = 50        # employers per run (0 = all)
DEFAULT_COOLDOWN_H = 12   # skip employers updated within this many hours


def _parse_rating(raw) -> float | None:
    """Parse a rating value into a float in (0, 5], or None."""
    if raw is None:
        return None
    try:
        v = float(str(raw).strip().replace(',', '.'))
        return v if 0 < v <= 5 else None
    except (ValueError, TypeError):
        return None


def fetch_employer_page(url: str) -> str:
    req = Request(url, headers={'User-Agent': USER_AGENT})
    with urlopen(req, timeout=20) as r:
        return r.read().decode('utf-8')


def _rating_from_ld(obj):
    """Extract ratingValue from a JSON-LD object."""
    if not isinstance(obj, dict):
        return None
    agg = obj.get('aggregateRating')
    if isinstance(agg, dict):
        return agg.get('ratingValue') or agg.get('rating')
    return obj.get('ratingValue') or obj.get('rating')


def extract_rating_from_html(html: str):
    """Extract employer rating from HH employer page HTML.

    Returns (rating_str | None, employer_dj_id | None).
    Targets the employer-aggregate totalRating (near employerDjId)
    to avoid picking up individual review scores.
    """
    html = _html_unescape.unescape(html)
    dj_id = None

    # Priority 1: employer-level totalRating near employerDjId (both orderings)
    for pat, id_grp, val_grp in [
        (_DJID_PAT + r'[^{}]{0,300}' + _RATING_PAT, 1, 2),
        (_RATING_PAT + r'[^{}]{0,300}' + _DJID_PAT, 2, 1),
    ]:
        m = re.search(pat, html, re.I)
        if m:
            dj_id = m.group(id_grp)
            v = _parse_rating(m.group(val_grp))
            if v:
                return str(v), dj_id
            break

    if not dj_id:
        m = re.search(_DJID_PAT, html, re.I)
        if m:
            dj_id = m.group(1)

    # Priority 2: JSON-LD aggregateRating
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.S | re.I,
    ):
        try:
            obj = json.loads(m.group(1))
            for o in (obj if isinstance(obj, list) else [obj]):
                v = _parse_rating(_rating_from_ld(o))
                if v:
                    return str(v), dj_id
        except Exception:
            continue

    # Priority 3: visible star symbols
    for m in re.finditer(r'([0-5](?:[\.,][0-9]{1,2})?)\s*(?:★|звез)', html, re.I):
        v = _parse_rating(m.group(1))
        if v:
            return str(v), dj_id

    return None, dj_id


class Command(BaseCommand):
    help = 'Fetch employer details from HH API / page scraping; store ratings.'

    def add_arguments(self, parser):
        parser.add_argument('--missing', action='store_true', help='Only employers with missing hh_rating')
        parser.add_argument('--limit', type=int, default=DEFAULT_LIMIT,
                            help=f'Max employers per run (0 = all, default {DEFAULT_LIMIT})')
        parser.add_argument('--delay', type=float, default=0.1, help='Seconds between HTTP requests')
        parser.add_argument('--cooldown', type=int, default=DEFAULT_COOLDOWN_H,
                            help=f'Skip employers updated within N hours (default {DEFAULT_COOLDOWN_H})')

    def handle(self, *args, **options):
        qs = Employer.objects.all()
        if options['missing']:
            qs = qs.filter(hh_rating__isnull=True)

        # Skip employers that were recently updated
        cooldown_hours = options.get('cooldown') or DEFAULT_COOLDOWN_H
        cutoff = timezone.now() - timedelta(hours=cooldown_hours)
        qs = qs.filter(
            models_Q(rating_updated_at__isnull=True) | models_Q(rating_updated_at__lt=cutoff)
        )

        limit = options.get('limit') or 0
        delay = options.get('delay') or 0.1

        employers = list(qs[:limit] if limit else qs.all())
        total = len(employers)
        self.stdout.write(f'Processing {total} employers (sequential)...')

        if not employers:
            self.stdout.write('Nothing to process.')
            return

        updated = 0
        skipped = 0
        start_time = time.monotonic()

        for emp in employers:
            try:
                candidate, source = self._fetch_rating(emp, delay)
                if self._save(emp, candidate, source):
                    updated += 1
                else:
                    skipped += 1
            except Exception:
                skipped += 1

        elapsed = time.monotonic() - start_time
        self.stdout.write(self.style.SUCCESS(
            f'Done in {elapsed:.1f}s. Updated={updated}, Skipped={skipped}'
        ))

    # ── private helpers ──

    def _fetch_rating(self, emp, delay):
        """Try API → HH page → DreamJob.  Return (candidate_str, source)."""
        candidate = dj_id = None

        # 1) HH API (fast, no scraping)
        if emp.hh_id:
            try:
                req = Request(f'https://api.hh.ru/employers/{emp.hh_id}',
                              headers={'User-Agent': USER_AGENT})
                with urlopen(req, timeout=10) as r:
                    data = json.loads(r.read().decode('utf-8'))
                for k in ('hh_rating', 'rating', 'ratingValue', 'rating_raw'):
                    if data.get(k):
                        candidate = data[k]
                        break
                if not candidate:
                    agg = data.get('aggregateRating')
                    if isinstance(agg, dict):
                        candidate = agg.get('ratingValue') or agg.get('rating')
            except Exception:
                pass  # will try page scrape

        # 2) HH page scrape (only if API didn't return a rating)
        if not candidate:
            for u in self._employer_urls(emp):
                try:
                    candidate, dj_id = extract_rating_from_html(fetch_employer_page(u))
                    if candidate:
                        break
                except Exception:
                    pass
                if delay:
                    time.sleep(delay)

        # Treat zero as missing
        if candidate is not None:
            try:
                if float(str(candidate).strip().replace(',', '.')) == 0:
                    candidate = None
            except Exception:
                pass

        # 3) DreamJob fallback (only if still nothing)
        if not candidate:
            candidate = self._try_dreamjob(emp, dj_id, delay)
            if candidate:
                return candidate, 'dreamjob'

        return candidate, 'hh'

    def _employer_urls(self, emp):
        urls = []
        raw = emp.raw if isinstance(emp.raw, dict) else {}
        alt = raw.get('alternate_url') or raw.get('url')
        if alt:
            urls.append(alt)
        if emp.hh_id:
            urls.append(f'https://hh.ru/employer/{emp.hh_id}')
        return urls

    def _try_dreamjob(self, emp, dj_id, delay):
        """Try DreamJob via dj_id, raw links, or name search. Return candidate or None."""
        try:
            from vacancies.dreamjob import (
                fetch_dreamjob_page, extract_rating_from_html as dj_extract,
                search_employer_links_by_name,
            )
        except Exception:
            return None

        urls = []
        if dj_id:
            urls.append(f'https://dreamjob.ru/employers/{dj_id}')
        raw = emp.raw if isinstance(emp.raw, dict) else {}
        for k in ('alternate_url', 'url', 'site'):
            v = raw.get(k)
            if isinstance(v, str) and 'dreamjob.ru' in v:
                urls.append(v)

        for u in urls:
            try:
                cand = dj_extract(fetch_dreamjob_page(u))
                if cand:
                    return cand
            except Exception:
                pass
            if delay:
                time.sleep(delay)

        try:
            for u in search_employer_links_by_name(emp.name):
                try:
                    cand = dj_extract(fetch_dreamjob_page(u))
                    if cand:
                        return cand
                except Exception:
                    pass
                if delay:
                    time.sleep(delay)
        except Exception:
            pass

        return None

    def _save(self, emp, candidate, source) -> bool:
        """Persist rating. Returns True if saved, False if skipped."""
        parsed = _parse_rating(candidate)
        if not parsed:
            return False

        now = timezone.now()
        if source == 'dreamjob':
            emp.dreamjob_rating = parsed
            emp.dreamjob_rating_raw = str(candidate)[:128]
            emp.dreamjob_rating_updated_at = now
            emp.save(update_fields=['dreamjob_rating', 'dreamjob_rating_raw', 'dreamjob_rating_updated_at'])
        else:
            emp.hh_rating = parsed
            emp.rating_raw = str(candidate)[:128]
            emp.rating_updated_at = now
            emp.save(update_fields=['hh_rating', 'rating_raw', 'rating_updated_at'])
        self.stdout.write(f'{emp.id} hh_id={emp.hh_id} -> {source}:{parsed}')
        return True

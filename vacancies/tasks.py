import json
import time
from datetime import timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from celery import shared_task
from django.core.management import call_command
from django.db import close_old_connections
import logging

logger = logging.getLogger(__name__)

HH_HEADERS = {'User-Agent': 'job-aggregator-diploma/1.0'}


def _close_connections():
    """Safely close stale DB connections in worker process."""
    try:
        close_old_connections()
    except Exception:
        pass


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def fetch_hh_task(self, pages=5, per_page=100, text='', texts='',
                  use_default_texts=False, area=None):
    """Fetch vacancies via the `fetch_hh` management command.

    Ratings are fetched lazily on demand (when user opens a vacancy).
    """
    _close_connections()
    try:
        kwargs = {}
        if pages:
            kwargs['pages'] = pages
        if per_page:
            kwargs['per_page'] = per_page
        if text:
            kwargs['text'] = text
        if texts:
            kwargs['texts'] = texts
        if use_default_texts:
            kwargs['use_default_texts'] = True
        if area is not None:
            kwargs['area'] = area
        call_command('fetch_hh', **kwargs)
    except Exception as exc:
        logger.exception('fetch_hh_task failed')
        raise self.retry(exc=exc)
    finally:
        _close_connections()
    return 'ok'


@shared_task(bind=True, max_retries=3, default_retry_delay=60, ignore_result=False)
def fetch_vacancy_description(self, vacancy_id):
    """Fetch full description for a single vacancy from the HH detail endpoint.

    Saves to dedicated `description` and `branded_description` fields so the
    list view never has to touch these large text blobs.
    Called automatically by fetch_hh_task for newly created vacancies.
    """
    from .models import Vacancy  # local import avoids circular import at module load

    _close_connections()
    try:
        vacancy = Vacancy.objects.get(id=vacancy_id)
    except Vacancy.DoesNotExist:
        logger.warning('fetch_vacancy_description: vacancy %s not found', vacancy_id)
        return 'not_found'

    hh_id = (vacancy.raw_json or {}).get('id') or vacancy.external_id
    if not hh_id:
        logger.warning('fetch_vacancy_description: vacancy %s has no HH id', vacancy_id)
        return 'no_hh_id'

    url = f'https://api.hh.ru/vacancies/{hh_id}'
    try:
        req = Request(url, headers=HH_HEADERS)
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except HTTPError as exc:
        if exc.code == 429:
            raise self.retry(exc=exc, countdown=60)
        if exc.code in (403, 404, 410):
            # Vacancy is archived, restricted, or deleted — no point retrying.
            # Write a sentinel so backfill won't keep picking it up.
            logger.info(
                'fetch_vacancy_description: vacancy %s HTTP %s — marking unavailable',
                vacancy_id, exc.code,
            )
            Vacancy.objects.filter(id=vacancy_id).update(
                description='__unavailable__'
            )
            return f'skipped:{exc.code}'
        raise self.retry(exc=exc)
    except Exception as exc:
        raise self.retry(exc=exc)

    vacancy.description = data.get('description', '') or ''
    vacancy.branded_description = data.get('branded_description', '') or ''
    vacancy.key_skills_text = ', '.join(
        s.get('name', '') for s in (data.get('key_skills') or []) if isinstance(s, dict)
    )
    vacancy.raw_json = {**(vacancy.raw_json or {}), **data}
    vacancy.save(update_fields=['description', 'branded_description',
                                'key_skills_text', 'raw_json'])

    _close_connections()
    desc_len = len(vacancy.description)
    branded_len = len(vacancy.branded_description)
    logger.info('fetch_vacancy_description: vacancy %s — desc=%d branded=%d',
                vacancy_id, desc_len, branded_len)
    return f'ok:desc={desc_len},branded={branded_len}'


@shared_task
def backfill_descriptions_task(limit=50):
    """Periodically queue description fetches for vacancies that still lack them.

    Uses Django's cache to avoid re-queuing vacancies that are already in-flight.
    Cache key expires after 10 minutes — long enough for a task to complete.
    """
    from .models import Vacancy
    from django.core.cache import cache

    _close_connections()
    ids = list(
        Vacancy.objects.filter(description='')
        .values_list('id', flat=True)
        .order_by('published_at')[:limit]
    )
    queued = 0
    for i, vid in enumerate(ids):
        cache_key = f'desc_inflight_{vid}'
        if cache.get(cache_key):
            continue  # already dispatched, skip
        cache.set(cache_key, 1, timeout=600)  # 10-minute TTL
        fetch_vacancy_description.apply_async(args=[vid], countdown=i * 0.5, priority=1)
        queued += 1
    logger.info('backfill_descriptions_task: queued %d (skipped %d in-flight)',
                queued, len(ids) - queued)
    return f'queued:{queued}'


@shared_task(bind=False, ignore_result=False)
def backup_database_task():
    """Create a rotating SQLite backup.

    Scheduled daily at 00:00 via Celery Beat.  Stores files under
    settings.BACKUP_DIR with the pattern ``db_backup_YYYYMMDD_HHMMSS.sqlite3``.
    Once more than DB_BACKUP_MAX_COUNT (default 3) files exist, the oldest is
    deleted so the count stays at the limit.
    """
    import sqlite3 as _sqlite3
    from contextlib import closing as _closing
    from pathlib import Path as _Path
    from datetime import datetime as _dt
    from django.conf import settings as _cfg

    db_path = _Path(_cfg.DATABASES['default']['NAME'])
    backup_dir = _Path(getattr(_cfg, 'BACKUP_DIR', db_path.parent / 'backups'))
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp   = _dt.now().strftime('%Y%m%d_%H%M%S')
    backup_path = backup_dir / f'db_backup_{timestamp}.sqlite3'

    # sqlite3.Connection.backup() uses SQLite's online backup API — safe in WAL mode.
    with _closing(_sqlite3.connect(str(db_path))) as src:
        with _closing(_sqlite3.connect(str(backup_path))) as dst:
            src.backup(dst)

    # Rotation: sorted ascending (oldest first); delete until <= max_count.
    max_count = getattr(_cfg, 'DB_BACKUP_MAX_COUNT', 3)
    existing  = sorted(backup_dir.glob('db_backup_*.sqlite3'))
    while len(existing) > max_count:
        existing[0].unlink()
        logger.info('backup_database_task: deleted oldest backup %s', existing[0].name)
        existing = existing[1:]

    logger.info('backup_database_task: created %s (total: %d)', backup_path.name, len(existing))
    return str(backup_path)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def fetch_employer_rating(self, employer_id):
    """Background scraping of employer rating from HH and DreamJob.

    Called when the rating API finds no cached value.  Scrapes both sources
    and persists the results so subsequent requests return instantly.
    """
    from .models import Employer
    from .management.commands.fetch_employer_details import (
        extract_rating_from_html, fetch_employer_page, _parse_rating,
    )
    from .dreamjob import (
        fetch_dreamjob_page,
        extract_rating_from_html as dj_extract,
        search_employer_links_by_name,
    )
    from .rating import _positive
    from django.utils import timezone

    _close_connections()
    try:
        emp = Employer.objects.get(id=employer_id)
    except Employer.DoesNotExist:
        return 'not_found'

    hh_val = _positive(emp.hh_rating)
    dj_val = _positive(emp.dreamjob_rating)

    # ── Scrape HH employer page ────────────────────────────
    dj_id = None
    if not hh_val:
        urls = []
        raw_emp = emp.raw if isinstance(emp.raw, dict) else {}
        alt = raw_emp.get('alternate_url') or raw_emp.get('url')
        if alt:
            urls.append(alt)
        if emp.hh_id:
            urls.append(f'https://hh.ru/employer/{emp.hh_id}')
        for u in urls:
            try:
                candidate, dj_id = extract_rating_from_html(fetch_employer_page(u))
                parsed = _parse_rating(candidate)
                if parsed:
                    hh_val = parsed
                    break
            except Exception:
                pass

    # ── Scrape DreamJob ────────────────────────────────────
    if not dj_val:
        dj_candidate = None
        if dj_id:
            try:
                dj_candidate = dj_extract(fetch_dreamjob_page(
                    f'https://dreamjob.ru/employers/{dj_id}'))
            except Exception:
                pass
        if not dj_candidate:
            raw_emp = emp.raw if isinstance(emp.raw, dict) else {}
            for k in ('alternate_url', 'url', 'site'):
                v = raw_emp.get(k)
                if isinstance(v, str) and 'dreamjob.ru' in v:
                    try:
                        dj_candidate = dj_extract(fetch_dreamjob_page(v))
                        if dj_candidate:
                            break
                    except Exception:
                        pass
        if not dj_candidate and emp.name:
            try:
                for dj_u in search_employer_links_by_name(emp.name):
                    try:
                        dj_candidate = dj_extract(fetch_dreamjob_page(dj_u))
                        if dj_candidate:
                            break
                    except Exception:
                        pass
            except Exception:
                pass
        parsed_dj = _parse_rating(dj_candidate) if dj_candidate else None
        if parsed_dj:
            dj_val = parsed_dj

    # ── Persist ────────────────────────────────────────────
    now = timezone.now()
    update_fields = []
    if hh_val and hh_val != _positive(emp.hh_rating):
        emp.hh_rating = hh_val
        emp.rating_updated_at = now
        update_fields += ['hh_rating', 'rating_updated_at']
    if dj_val and dj_val != _positive(emp.dreamjob_rating):
        emp.dreamjob_rating = dj_val
        emp.dreamjob_rating_updated_at = now
        update_fields += ['dreamjob_rating', 'dreamjob_rating_updated_at']
    if update_fields:
        emp.save(update_fields=update_fields)

    _close_connections()
    return f'hh={hh_val},dj={dj_val}'


@shared_task(bind=False, ignore_result=False)
def check_hh_vacancy_status_task(batch_size=50):
    """Soft-delete HH vacancies that are no longer available.

    Two-stage approach:
    1. TTL: instantly deactivate HH vacancies older than 35 days
       (HH max lifetime is 30 days; 5-day buffer for extensions).
    2. API check: for remaining active HH vacancies, request the HH API
       in small batches and deactivate any that return 404 / 410.
    """
    from .models import Vacancy
    from django.utils import timezone as tz

    _close_connections()

    # Stage 1 — TTL deactivation (no API needed)
    cutoff_ttl = tz.now() - timedelta(days=35)
    expired = Vacancy.objects.filter(
        created_by__isnull=True,
        is_active=True,
        published_at__lt=cutoff_ttl,
    ).update(is_active=False)

    # Stage 2 — API check for newer HH vacancies (oldest first)
    candidates = list(
        Vacancy.objects.filter(
            created_by__isnull=True,
            is_active=True,
        ).order_by('published_at').values_list('id', 'external_id')[:batch_size]
    )

    deactivated = 0
    for vid, ext_id in candidates:
        url = f'https://api.hh.ru/vacancies/{ext_id}'
        try:
            req = Request(url, headers=HH_HEADERS)
            with urlopen(req, timeout=10) as resp:
                resp.read()  # 200 OK — vacancy is still live
        except HTTPError as exc:
            if exc.code in (404, 410):
                Vacancy.objects.filter(id=vid).update(is_active=False)
                deactivated += 1
                logger.info('check_hh_vacancy_status_task: deactivated %s (HTTP %s)', ext_id, exc.code)
            elif exc.code == 429:
                logger.warning('check_hh_vacancy_status_task: rate-limited by HH, stopping early')
                break
        except Exception as exc:
            logger.debug('check_hh_vacancy_status_task: skipping %s — %s', ext_id, exc)
        time.sleep(0.3)  # stay within HH rate limits

    _close_connections()
    logger.info(
        'check_hh_vacancy_status_task: ttl_expired=%d api_deactivated=%d',
        expired, deactivated,
    )
    return f'ttl_expired:{expired},api_deactivated:{deactivated}'
import json
import time
from datetime import timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import requests

from celery import shared_task
from celery.exceptions import Retry
from celery.exceptions import MaxRetriesExceededError
from django.core.management import call_command
from django.db import close_old_connections
from django.conf import settings as dj_settings
from django.core.cache import cache
import logging
from vacancies.hh_client import hh_openapi_headers

logger = logging.getLogger(__name__)
INGEST_GLOBAL_LOCK_KEY = 'lock:vacancy_ingest_global'
INGEST_LOCK_TTL_SEC = 20 * 60

def _close_connections():
    """Safely close stale DB connections in worker process."""
    try:
        close_old_connections()
    except Exception:
        pass


def _run_command(name, **kwargs):
    payload = {k: v for k, v in kwargs.items() if v is not None and v != ''}
    call_command(name, **payload)


def _acquire_lock(key, timeout=INGEST_LOCK_TTL_SEC):
    return bool(cache.add(key, 1, timeout=timeout))


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def fetch_hh_task(self, pages=5, per_page=100, text='', texts='',
                  use_default_texts=False, area=None):
    """Fetch vacancies via the `fetch_hh` management command.

    Ratings are fetched lazily on demand (when user opens a vacancy).
    """
    _close_connections()
    hh_lock_key = 'lock:fetch_hh_task'
    if not _acquire_lock(hh_lock_key):
        return 'skipped:already_running'
    has_global_lock = False
    try:
        if not _acquire_lock(INGEST_GLOBAL_LOCK_KEY):
            # Another heavy ingest is writing to SQLite right now.
            # Retry shortly instead of dropping this cycle.
            raise self.retry(countdown=20)
        has_global_lock = True
        kwargs = {'pages': pages, 'per_page': per_page, 'text': text, 'texts': texts, 'area': area}
        if use_default_texts:
            kwargs['use_default_texts'] = True
        _run_command('fetch_hh', **kwargs)
    except Retry:
        raise
    except MaxRetriesExceededError:
        logger.warning('Импорт HH пропущен: очередь занята слишком долго')
        return 'skipped:ingest_busy_timeout'
    except Exception as exc:
        logger.exception('Ошибка задачи импорта HH')
        raise self.retry(exc=exc)
    finally:
        if has_global_lock:
            cache.delete(INGEST_GLOBAL_LOCK_KEY)
        cache.delete(hh_lock_key)
        _close_connections()
    return 'ok'


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def fetch_trudvsem_task(self, limit=200, offset=None, text=''):
    _close_connections()
    lock_key = 'lock:fetch_trudvsem_task'
    if not _acquire_lock(lock_key, timeout=15 * 60):
        return 'skipped:already_running'
    has_global_lock = False
    try:
        if not _acquire_lock(INGEST_GLOBAL_LOCK_KEY):
            # Another heavy ingest is writing to SQLite right now.
            # Retry shortly instead of dropping this cycle.
            raise self.retry(countdown=20)
        has_global_lock = True
        kwargs = {
            'limit': max(1, int(limit or 200)),
            'offset': max(0, int(offset)) if offset is not None else None,
            'text': text,
        }
        _run_command('fetch_trudvsem', **kwargs)
    except Retry:
        raise
    except MaxRetriesExceededError:
        logger.warning('Импорт Работа России пропущен: очередь занята слишком долго')
        return 'skipped:ingest_busy_timeout'
    except Exception as exc:
        logger.exception('Ошибка задачи импорта Работа России')
        raise self.retry(exc=exc)
    finally:
        if has_global_lock:
            cache.delete(INGEST_GLOBAL_LOCK_KEY)
        cache.delete(lock_key)
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
        logger.warning('Описание HH: вакансия id=%s не найдена', vacancy_id)
        return 'not_found'

    hh_id = (vacancy.raw_json or {}).get('id') or vacancy.external_id
    if not hh_id:
        logger.warning('Описание HH: у вакансии id=%s нет HH id', vacancy_id)
        return 'no_hh_id'

    url = f'https://api.hh.ru/vacancies/{hh_id}'
    try:
        req = Request(url, headers=hh_openapi_headers())
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except HTTPError as exc:
        if exc.code == 429:
            raise self.retry(exc=exc, countdown=60)
        if exc.code in (403, 404, 410):
            # Vacancy is archived, restricted, or deleted — no point retrying.
            # Write a sentinel so backfill won't keep picking it up.
            logger.info('Описание HH: вакансия id=%s HTTP %s, помечена недоступной', vacancy_id, exc.code)
            Vacancy.objects.filter(id=vacancy_id, is_moderator_deleted=False).update(
                description='__unavailable__',
                is_active=False,
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
    _fields = ['description', 'branded_description', 'key_skills_text', 'raw_json']
    if data.get('archived') and not vacancy.is_moderator_deleted:
        vacancy.is_active = False
        _fields.append('is_active')
    vacancy.save(update_fields=_fields)

    _close_connections()
    desc_len = len(vacancy.description)
    branded_len = len(vacancy.branded_description)
    logger.info('Описание HH: вакансия id=%s, desc=%d, branded=%d',
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
    logger.info('Добор описаний HH: в очереди=%d, пропущено(in-flight)=%d',
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
        logger.info('Бэкап БД: удален старый файл %s', existing[0].name)
        existing = existing[1:]

    logger.info('Бэкап БД: создан %s (всего файлов: %d)', backup_path.name, len(existing))
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
       in small batches and deactivate any that return 403/404/410 or JSON
       with archived=true (вакансия в архиве на hh.ru).
    """
    from .models import Vacancy
    from django.utils import timezone as tz

    _close_connections()

    # Stage 1 — TTL deactivation (no API needed)
    cutoff_ttl = tz.now() - timedelta(days=getattr(dj_settings, 'HH_STALE_TTL_DAYS', 35))
    expired = Vacancy.objects.filter(
        created_by__isnull=True,
        is_active=True,
    ).exclude(external_id__startswith='trudvsem-').filter(
        published_at__lt=cutoff_ttl,
    ).update(is_active=False)

    from_json = Vacancy.objects.filter(
        created_by__isnull=True,
        is_active=True,
        is_moderator_deleted=False,
        raw_json__archived=True,
    ).exclude(external_id__startswith='trudvsem-').update(is_active=False)

    # Stage 2 — API check (newest published first — чаще ещё в каталоге на сайте)
    candidates = list(
        Vacancy.objects.filter(
            created_by__isnull=True,
            is_active=True,
            is_moderator_deleted=False,
        ).exclude(external_id__startswith='trudvsem-')
        .order_by('-published_at').values_list('id', 'external_id')[:batch_size]
    )

    deactivated = 0
    for vid, ext_id in candidates:
        url = f'https://api.hh.ru/vacancies/{ext_id}'
        try:
            req = Request(url, headers=hh_openapi_headers())
            with urlopen(req, timeout=10) as resp:
                body = resp.read()
            try:
                data = json.loads(body.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.debug('HH статус: ответ не JSON %s', ext_id)
                time.sleep(0.3)
                continue
            if data.get('archived'):
                updated = Vacancy.objects.filter(
                    id=vid, is_moderator_deleted=False, is_active=True
                ).update(is_active=False)
                deactivated += int(updated)
                if updated:
                    logger.info('HH статус: архив на HH (archived) %s', ext_id)
        except HTTPError as exc:
            if exc.code in (403, 404, 410):
                updated = Vacancy.objects.filter(
                    id=vid, is_moderator_deleted=False, is_active=True
                ).update(is_active=False)
                deactivated += int(updated)
                if updated:
                    logger.info('HH статус: деактивирована %s (HTTP %s)', ext_id, exc.code)
            elif exc.code == 429:
                logger.warning('HH статус: лимит запросов, ранняя остановка проверки')
                break
        except Exception as exc:
            logger.debug('HH статус: пропуск %s, причина=%s', ext_id, exc)
        time.sleep(0.3)  # stay within HH rate limits

    _close_connections()
    logger.info(
        'HH статус: ttl_expired=%d, json_archived=%d, api_deactivated=%d',
        expired, from_json, deactivated,
    )
    return f'ttl_expired:{expired},json_archived:{from_json},api_deactivated:{deactivated}'


def reconcile_hh_archived_imports_core(*, api_batch=None, dry_run=False):
    """Снять с публикации импорты HH, которые на api.hh.ru уже в архиве (или 404).

    1) ``raw_json.archived == true`` — уже приходило из прошлых запросов к API.
    2) Опрос ``GET /vacancies/{id}`` для активных строк (сначала недавно опубликованные).
    """
    from .models import Vacancy

    _close_connections()

    api_batch = int(
        api_batch if api_batch is not None
        else getattr(dj_settings, 'HH_RECONCILE_ARCHIVED_BATCH', 500)
    )
    api_batch = max(0, min(api_batch, 5000))

    hh_active = dict(
        created_by__isnull=True,
        is_moderator_deleted=False,
        is_active=True,
    )
    result = {}

    qs_json = (
        Vacancy.objects.filter(**hh_active, raw_json__archived=True)
        .exclude(external_id__startswith='trudvsem-')
    )
    n_json = qs_json.count()
    result['active_with_archived_flag_in_json'] = n_json
    if dry_run:
        result['would_deactivate_from_json'] = n_json
    elif n_json:
        result['deactivated_from_json'] = qs_json.update(is_active=False)

    if api_batch == 0:
        _close_connections()
        return result

    candidates = list(
        Vacancy.objects.filter(**hh_active)
        .exclude(external_id__startswith='trudvsem-')
        .order_by('-published_at')
        .values_list('id', 'external_id')[:api_batch]
    )
    result['api_probe_scheduled'] = len(candidates)
    if dry_run:
        _close_connections()
        return result

    deactivated_api = 0
    hit_429 = False
    for vid, ext_id in candidates:
        if not ext_id:
            continue
        url = f'https://api.hh.ru/vacancies/{ext_id}'
        try:
            req = Request(url, headers=hh_openapi_headers())
            with urlopen(req, timeout=10) as resp:
                body = resp.read()
            try:
                data = json.loads(body.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                time.sleep(0.25)
                continue
            if data.get('archived'):
                deactivated_api += Vacancy.objects.filter(
                    id=vid, is_moderator_deleted=False, is_active=True,
                ).update(is_active=False)
        except HTTPError as exc:
            if exc.code in (403, 404, 410):
                deactivated_api += Vacancy.objects.filter(
                    id=vid, is_moderator_deleted=False, is_active=True,
                ).update(is_active=False)
            elif exc.code == 429:
                logger.warning('HH reconcile: rate limit, stopping API probe early')
                hit_429 = True
                break
        except Exception:
            pass
        time.sleep(0.25)

    result['deactivated_from_api'] = deactivated_api
    result['stopped_for_429'] = hit_429
    logger.info(
        'HH reconcile archived: json_off=%s api_off=%s probed=%s',
        result.get('deactivated_from_json', result.get('would_deactivate_from_json', 0)),
        deactivated_api,
        len(candidates),
    )
    _close_connections()
    return result


def purge_inactive_hh_vacancies_core(
    *, batch_size=None, dry_run=False, reconcile_batch=None, skip_reconcile=False,
):
    """Сверка с HH (архив), затем жёсткое удаление давно неактивных импортов.

    Удаляются только ``is_active=False`` и ``published_at`` старше порога
    (без проверки ``updated_at`` — иначе строки после импорта не попадали в выборку).
    """
    from django.utils import timezone as tz

    from .models import Vacancy

    _close_connections()
    merged = {}
    if not skip_reconcile:
        merged['reconcile'] = reconcile_hh_archived_imports_core(
            api_batch=reconcile_batch,
            dry_run=dry_run,
        )

    if not getattr(dj_settings, 'HH_INACTIVE_PURGE_ENABLED', True):
        merged['skipped_purge'] = 'disabled'
        return merged

    days = max(7, int(getattr(dj_settings, 'HH_INACTIVE_PURGE_MIN_AGE_DAYS', 90)))
    batch = batch_size if batch_size is not None else int(
        getattr(dj_settings, 'HH_INACTIVE_PURGE_BATCH', 2000)
    )
    batch = max(1, min(int(batch), 10000))

    cutoff = tz.now() - timedelta(days=days)
    base_qs = (
        Vacancy.objects.filter(
            created_by__isnull=True,
            is_active=False,
            is_moderator_deleted=False,
            published_at__lt=cutoff,
        )
        .exclude(external_id__startswith='trudvsem-')
        .order_by('published_at')
    )
    ids = list(base_qs.values_list('id', flat=True)[:batch])
    if dry_run:
        merged['dry_run'] = True
        merged['would_delete'] = len(ids)
        merged['sample_ids'] = ids[:20]
        return merged
    if not ids:
        merged['deleted_total'] = 0
        merged['vacancy_ids_requested'] = 0
        return merged

    deleted_total, details = Vacancy.objects.filter(pk__in=ids).delete()
    logger.info(
        'HH purge inactive: vacancies_requested=%s ORM_deleted_total=%s per_model=%s',
        len(ids), deleted_total, details,
    )
    _close_connections()
    merged['deleted_total'] = deleted_total
    merged['vacancy_ids_requested'] = len(ids)
    merged['per_model'] = details
    return merged


def purge_hh_imports_by_db_age_core(*, days=None, batch_size=None, dry_run=False):
    """Жёстко удалить HH-импорты, у которых ``created_at`` старше порога (дней в нашей БД).

    Не трогает вакансии с сайта (``created_by`` задан) и строки ``trudvsem-*``.
    """
    from django.utils import timezone as tz

    from .models import Vacancy

    _close_connections()
    out = {}
    if not getattr(dj_settings, 'HH_IMPORT_DB_AGE_PURGE_ENABLED', True):
        out['skipped'] = 'disabled'
        return out

    eff_days = days if days is not None else int(
        getattr(dj_settings, 'HH_IMPORT_DB_AGE_PURGE_DAYS', 7)
    )
    eff_days = max(1, int(eff_days))
    batch = batch_size if batch_size is not None else int(
        getattr(dj_settings, 'HH_IMPORT_DB_AGE_PURGE_BATCH', 5000)
    )
    batch = max(1, min(int(batch), 50000))

    cutoff = tz.now() - timedelta(days=eff_days)
    base_qs = (
        Vacancy.objects.filter(created_by__isnull=True, created_at__lt=cutoff)
        .exclude(external_id__startswith='trudvsem-')
        .order_by('created_at')
    )
    ids = list(base_qs.values_list('id', flat=True)[:batch])
    out['cutoff_iso'] = cutoff.isoformat()
    out['days'] = eff_days
    if dry_run:
        out['dry_run'] = True
        out['would_delete'] = len(ids)
        out['sample_ids'] = ids[:20]
        return out
    if not ids:
        out['deleted_total'] = 0
        out['vacancy_ids_requested'] = 0
        return out

    deleted_total, details = Vacancy.objects.filter(pk__in=ids).delete()
    logger.info(
        'HH purge by DB age: vacancies_requested=%s ORM_deleted_total=%s per_model=%s',
        len(ids), deleted_total, details,
    )
    _close_connections()
    out['deleted_total'] = deleted_total
    out['vacancy_ids_requested'] = len(ids)
    out['per_model'] = details
    return out


@shared_task(bind=False, ignore_result=False)
def purge_inactive_hh_vacancies_task():
    """Scheduled: reconcile HH archived state, then hard-delete old inactive imports."""
    return purge_inactive_hh_vacancies_core()


@shared_task(bind=False, ignore_result=False)
def purge_hh_imports_by_db_age_task():
    """Scheduled: hard-delete HH imports older than HH_IMPORT_DB_AGE_PURGE_DAYS in our DB."""
    return purge_hh_imports_by_db_age_core()


@shared_task(bind=False, ignore_result=False)
def check_trudvsem_vacancy_status_task(batch_size=100):
    """Hard-delete Trudvsem vacancies that are stale or gone on source."""
    from .models import Vacancy
    from django.utils import timezone as tz

    _close_connections()
    ttl_days = max(1, int(getattr(dj_settings, 'FALLBACK_TRUDVSEM_TTL_DAYS', 5)))
    cutoff = tz.now() - timedelta(days=ttl_days)

    # Stage 1: hard-delete stale rows not refreshed for TTL period.
    stale_deleted, _ = Vacancy.objects.filter(
        created_by__isnull=True,
        external_id__startswith='trudvsem-',
        updated_at__lt=cutoff,
    ).delete()

    # Stage 2: source availability probe for recent rows.
    candidates = list(
        Vacancy.objects.filter(
            created_by__isnull=True,
            external_id__startswith='trudvsem-',
        )
        .order_by('updated_at')
        .values_list('id', 'url')[:batch_size]
    )

    source_deleted = 0
    for vid, url in candidates:
        target = (url or '').strip()
        if not target:
            continue
        try:
            resp = requests.get(target, timeout=10, allow_redirects=True)
            if resp.status_code == 404:
                Vacancy.objects.filter(id=vid).delete()
                source_deleted += 1
        except requests.RequestException:
            # Network issues should not delete records.
            continue
        time.sleep(0.1)

    _close_connections()
    logger.info(
        'Работа России статус: stale_deleted=%d, source_deleted=%d',
        stale_deleted, source_deleted,
    )
    return f'stale_deleted:{stale_deleted},source_deleted:{source_deleted}'
import os
from celery import Celery
from celery.schedules import crontab
from celery.signals import heartbeat_sent, worker_ready, worker_shutdown
from django.conf import settings as django_settings

from .service_status import mark_celery_alive, mark_celery_stopped

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('job_aggregator')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


@worker_ready.connect
def _mark_worker_ready(**kwargs):
    mark_celery_alive()
    if not getattr(django_settings, 'VACANCY_FETCH_ON_STARTUP', True):
        return
    # Warm start: kick off both sources immediately, without waiting first beat interval.
    try:
        from vacancies.tasks import fetch_hh_task, fetch_trudvsem_task
        fetch_hh_task.delay(
            pages=getattr(django_settings, 'HH_STARTUP_FETCH_PAGES', 1),
            per_page=getattr(django_settings, 'HH_STARTUP_FETCH_PER_PAGE', 10),
        )
        fetch_trudvsem_task.delay(
            limit=getattr(django_settings, 'FALLBACK_TRUDVSEM_STARTUP_LIMIT', 10),
        )
    except Exception:
        pass


@heartbeat_sent.connect
def _mark_worker_heartbeat(**kwargs):
    mark_celery_alive()


@worker_shutdown.connect
def _mark_worker_shutdown(**kwargs):
    mark_celery_stopped()

# ─── Periodic schedule ───────────────────────────────────────────────────────
# Pipeline order:  vacancies → ratings → regions/experience (dictionaries)
#
# To change the interval, edit SYNC_INTERVAL_SECONDS below.
# Current: 180 seconds (3 minutes) — for testing.
# Production recommendation: 600 (10 min) or 3600 (1 hour).

SYNC_INTERVAL_SECONDS = getattr(django_settings, 'HH_SYNC_INTERVAL_SEC', 600)
HH_FETCH_PAGES = getattr(django_settings, 'HH_FETCH_PAGES', 3)
HH_FETCH_PER_PAGE = getattr(django_settings, 'HH_FETCH_PER_PAGE', 50)
TRUDVSEM_INTERVAL_SECONDS = getattr(
    django_settings,
    'FALLBACK_TRUDVSEM_SYNC_INTERVAL_SEC',
    SYNC_INTERVAL_SECONDS,
)
TRUDVSEM_LIMIT = getattr(django_settings, 'FALLBACK_TRUDVSEM_LIMIT', 200)

app.conf.beat_schedule = {
    'fetch-vacancies': {
        'task': 'vacancies.tasks.fetch_hh_task',
        'schedule': SYNC_INTERVAL_SECONDS,
        'kwargs': {'pages': HH_FETCH_PAGES, 'per_page': HH_FETCH_PER_PAGE},
    },
    # After each vacancy fetch wave, fill in any missing descriptions.
    # Offset by 30 s so it runs after fetch_hh_task finishes.
    'backfill-descriptions': {
        'task': 'vacancies.tasks.backfill_descriptions_task',
        'schedule': SYNC_INTERVAL_SECONDS,
        'kwargs': {'limit': getattr(django_settings, 'HH_BACKFILL_LIMIT', 80)},
    },
    # Soft-delete HH vacancies that are no longer available: TTL + API check.
    # Runs every 6 hours; checks 50 vacancies per run via the HH API.
    'check-hh-vacancy-status': {
        'task': 'vacancies.tasks.check_hh_vacancy_status_task',
        'schedule': getattr(django_settings, 'HH_STALE_CHECK_INTERVAL_SEC', 21600),
        'kwargs': {'batch_size': getattr(django_settings, 'HH_STALE_CHECK_BATCH', 50)},
    },
    'check-trudvsem-vacancy-status': {
        'task': 'vacancies.tasks.check_trudvsem_vacancy_status_task',
        'schedule': getattr(django_settings, 'FALLBACK_TRUDVSEM_STATUS_CHECK_INTERVAL_SEC', 3600),
        'kwargs': {'batch_size': getattr(django_settings, 'FALLBACK_TRUDVSEM_STATUS_CHECK_BATCH', 100)},
    },
    'fetch-trudvsem-fallback': {
        'task': 'vacancies.tasks.fetch_trudvsem_task',
        'schedule': TRUDVSEM_INTERVAL_SECONDS,
        'kwargs': {'limit': TRUDVSEM_LIMIT},
    },
    # Rotating database backup daily at 00:00 (keeps last DB_BACKUP_MAX_COUNT copies).
    'backup-database': {
        'task': 'vacancies.tasks.backup_database_task',
        'schedule': crontab(hour=0, minute=0),  # every day at 00:00
    },
    # Send interview reminders (1 day before, 1 hour before, 5 min before).
    'notify-interview-reminders': {
        'task': 'accounts.tasks.notify_interview_reminders_task',
        'schedule': 60,    # every 1 minute — needed for the 5-min window
    },
    # Send calendar-note reminders close to the exact note time.
    'notify-calendar-note-reminders': {
        'task': 'accounts.tasks.notify_calendar_note_reminders_task',
        'schedule': 60,    # every 1 minute
    },
}

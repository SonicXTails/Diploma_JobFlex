import os
from celery import Celery
from celery.schedules import crontab
from celery.signals import heartbeat_sent, worker_ready, worker_shutdown

from .service_status import mark_celery_alive, mark_celery_stopped

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('job_aggregator')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


@worker_ready.connect
def _mark_worker_ready(**kwargs):
    mark_celery_alive()


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

SYNC_INTERVAL_SECONDS = 180  # <── change this value to adjust the interval

app.conf.beat_schedule = {
    'fetch-vacancies': {
        'task': 'vacancies.tasks.fetch_hh_task',
        'schedule': SYNC_INTERVAL_SECONDS,
    },
    # After each vacancy fetch wave, fill in any missing descriptions.
    # Offset by 30 s so it runs after fetch_hh_task finishes.
    'backfill-descriptions': {
        'task': 'vacancies.tasks.backfill_descriptions_task',
        'schedule': SYNC_INTERVAL_SECONDS,
        'kwargs': {'limit': 100},
    },
    # Soft-delete HH vacancies that are no longer available: TTL + API check.
    # Runs every 6 hours; checks 50 vacancies per run via the HH API.
    'check-hh-vacancy-status': {
        'task': 'vacancies.tasks.check_hh_vacancy_status_task',
        'schedule': 21600,  # 6 hours
        'kwargs': {'batch_size': 50},
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

"""Hard-delete HH imports that have sat in our DB longer than N days (by ``created_at``)."""

from django.conf import settings
from django.core.management.base import BaseCommand

from vacancies.tasks import purge_hh_imports_by_db_age_core


class Command(BaseCommand):
    help = (
        "Deletes HH import rows (created_by is null, not trudvsem-*) whose created_at "
        f"is older than HH_IMPORT_DB_AGE_PURGE_DAYS (default {settings.HH_IMPORT_DB_AGE_PURGE_DAYS}). "
        "Site-posted vacancies are never removed. "
        f"Disable via HH_IMPORT_DB_AGE_PURGE_ENABLED=false."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report counts only; no deletes.',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=None,
            help=f"Min age in DB in days (default {settings.HH_IMPORT_DB_AGE_PURGE_DAYS}).",
        )
        parser.add_argument(
            '--batch',
            type=int,
            default=None,
            help=f"Max rows to delete this run (default {settings.HH_IMPORT_DB_AGE_PURGE_BATCH}).",
        )

    def handle(self, *args, **opts):
        r = purge_hh_imports_by_db_age_core(
            days=opts['days'],
            batch_size=opts['batch'],
            dry_run=opts['dry_run'],
        )
        if r.get('skipped') == 'disabled':
            self.stdout.write(
                self.style.WARNING(
                    'Skipped (HH_IMPORT_DB_AGE_PURGE_ENABLED=false).'
                )
            )
            return
        if opts['dry_run']:
            self.stdout.write(
                f"[dry-run] Would delete HH imports: {r.get('would_delete', 0)} "
                f"(created_at before {r.get('cutoff_iso')}, days={r.get('days')}, "
                f"sample_ids={r.get('sample_ids')})"
            )
            return
        if r.get('vacancy_ids_requested', 0) == 0:
            self.stdout.write('No HH import rows matched DB-age criteria (nothing deleted).')
            return
        self.stdout.write(self.style.SUCCESS(
            f"Hard-delete ORM total count: {r.get('deleted_total', 0)} "
            f"(vacancy rows: {r.get('vacancy_ids_requested', 0)}). "
            f"Per-model: {r.get('per_model')}"
        ))

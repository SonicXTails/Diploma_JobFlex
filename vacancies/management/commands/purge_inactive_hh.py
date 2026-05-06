"""Reconcile archived HH vacancies + hard-delete old inactive HH imports."""

from django.conf import settings
from django.core.management.base import BaseCommand

from vacancies.tasks import purge_inactive_hh_vacancies_core


class Command(BaseCommand):
    help = (
        "1) Matches DB with api.hh.ru: marks HH imports inactive when archived/404 "
        "(up to HH_RECONCILE_ARCHIVED_BATCH API calls, plus fast path raw_json.archived). "
        "2) Deletes inactive HH rows older than HH_INACTIVE_PURGE_MIN_AGE_DAYS (published_at only). "
        "Site vacancies and trudvsem-* are never touched."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='No updates/deletes: report counts only.',
        )
        parser.add_argument(
            '--batch',
            type=int,
            default=None,
            help=f"Max vacancies to hard-delete this run (default {settings.HH_INACTIVE_PURGE_BATCH}).",
        )
        parser.add_argument(
            '--reconcile-batch',
            type=int,
            default=None,
            help=f"Max active HH rows to probe via API (default {settings.HH_RECONCILE_ARCHIVED_BATCH}).",
        )
        parser.add_argument(
            '--skip-reconcile',
            action='store_true',
            help='Only run hard-delete phase (already inactive rows).',
        )

    def handle(self, *args, **opts):
        r = purge_inactive_hh_vacancies_core(
            batch_size=opts['batch'],
            dry_run=opts['dry_run'],
            reconcile_batch=opts['reconcile_batch'],
            skip_reconcile=opts['skip_reconcile'],
        )

        if not opts['skip_reconcile']:
            rec = r.get('reconcile') or {}
            if opts['dry_run']:
                self.stdout.write(
                    f"[dry-run] Reconcile: would_deactivate_from_json={rec.get('would_deactivate_from_json', 0)}, "
                    f"active_rows_with_archived_in_json={rec.get('active_with_archived_flag_in_json', 0)}, "
                    f"api_rows_would_probe={rec.get('api_probe_scheduled', 0)}"
                )
            else:
                self.stdout.write(
                    f"Reconcile: deactivated_from_json={rec.get('deactivated_from_json', 0)}, "
                    f"deactivated_from_api={rec.get('deactivated_from_api', 0)}, "
                    f"api_probes={rec.get('api_probe_scheduled', 0)}"
                    + (f", stopped_429={rec.get('stopped_for_429')}" if rec.get('stopped_for_429') else '')
                )

        if r.get('skipped_purge') == 'disabled':
            self.stdout.write(
                self.style.WARNING('Hard-delete disabled (HH_INACTIVE_PURGE_ENABLED=false). Reconcile still ran unless --skip-reconcile.')
            )
            return

        if opts['dry_run']:
            self.stdout.write(
                f"[dry-run] Would hard-delete inactive vacancies: {r.get('would_delete', 0)} "
                f"(min published age days: {settings.HH_INACTIVE_PURGE_MIN_AGE_DAYS}, "
                f"sample_ids={r.get('sample_ids')})"
            )
            return

        if r.get('deleted_total', 0) == 0 and r.get('vacancy_ids_requested', 0) == 0:
            self.stdout.write('Hard-delete: no inactive HH rows matched age criteria (nothing deleted).')
            return

        self.stdout.write(self.style.SUCCESS(
            f"Hard-delete ORM total count: {r.get('deleted_total', 0)} "
            f"(vacancy rows in batch: {r.get('vacancy_ids_requested', 0)}). "
            f"Per-model: {r.get('per_model')}"
        ))

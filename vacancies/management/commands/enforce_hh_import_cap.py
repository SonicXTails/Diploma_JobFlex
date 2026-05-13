"""Trim imported vacancies (created_by is null) down to HH_IMPORT_TOTAL_CAP, oldest first."""

from django.conf import settings
from django.core.management.base import BaseCommand

from vacancies.tasks import enforce_hh_import_cap_core


class Command(BaseCommand):
    help = (
        "Deletes oldest import rows by created_at until count ≤ HH_IMPORT_TOTAL_CAP. "
        "Site-created vacancies are never touched. "
        f"Cap 0 (default on localhost) disables the command. On Render set HH_IMPORT_TOTAL_CAP "
        f"(e.g. {getattr(settings, 'HH_IMPORT_TOTAL_CAP', 0) or 1000})."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report counts only; no deletes.',
        )
        parser.add_argument(
            '--cap',
            type=int,
            default=None,
            help=f"Override cap (default from settings HH_IMPORT_TOTAL_CAP, currently {settings.HH_IMPORT_TOTAL_CAP}).",
        )

    def handle(self, *args, **opts):
        r = enforce_hh_import_cap_core(
            cap=opts['cap'],
            dry_run=opts['dry_run'],
        )
        if r.get('skipped') == 'disabled':
            self.stdout.write(
                self.style.WARNING(
                    'Skipped: HH_IMPORT_TOTAL_CAP is 0 or unset (no limit enforced).'
                )
            )
            return
        if opts['dry_run']:
            self.stdout.write(
                f"[dry-run] Would delete {r.get('would_delete', 0)} import rows "
                f"(cap={r.get('cap')}, before={r.get('before')}, "
                f"sample_ids={r.get('sample_ids')})"
            )
            return
        if r.get('vacancy_ids_requested', 0) == 0:
            self.stdout.write(
                f"Nothing to delete (imports before trim: {r.get('before', 0)}, cap={r.get('cap')})."
            )
            return
        self.stdout.write(self.style.SUCCESS(
            f"Cap enforce: deleted ORM count {r.get('deleted_total', 0)} "
            f"(vacancy ids {r.get('vacancy_ids_requested')}). "
            f"Per-model: {r.get('per_model')}"
        ))

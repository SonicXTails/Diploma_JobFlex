"""Management command: restore the SQLite database from a backup file.

Usage:
    python manage.py restore_db <backup_file>

<backup_file> can be:
    - An absolute path to any .sqlite3 file.
    - A bare filename (e.g. db_backup_20260308_120000.sqlite3) that will be
      resolved relative to settings.BACKUP_DIR.

A safety snapshot of the current database is written to BACKUP_DIR before
overwriting so you can undo the restore manually if needed.

Example:
    python manage.py restore_db db_backup_20260308_120000.sqlite3
"""

import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections


class Command(BaseCommand):
    help = 'Restore the SQLite database from a backup file.'

    def add_arguments(self, parser):
        parser.add_argument(
            'backup_file',
            help=(
                'Path to the backup .sqlite3 file, or just the filename '
                '(resolved relative to settings.BACKUP_DIR).'
            ),
        )
        parser.add_argument(
            '--no-safety',
            action='store_true',
            default=False,
            help="Skip creating a safety snapshot of the current database before restoring.",
        )

    def handle(self, *args, **options):
        backup_arg = options['backup_file']
        no_safety  = options['no_safety']

        db_path    = Path(settings.DATABASES['default']['NAME'])
        backup_dir = Path(getattr(settings, 'BACKUP_DIR',
                                  db_path.parent / 'backups'))

        backup_path = Path(backup_arg)
        if not backup_path.is_absolute() or not backup_path.exists():
            # Try resolving as a bare filename inside BACKUP_DIR
            candidate = backup_dir / backup_arg
            if candidate.exists():
                backup_path = candidate
            else:
                raise CommandError(
                    f'Backup file not found: {backup_arg}\n'
                    f'(Searched in {backup_dir})'
                )

        if not backup_path.exists():
            raise CommandError(f'Backup file not found: {backup_path}')

        self.stdout.write(f'Restoring from: {backup_path}')
        self.stdout.write(f'Target DB:      {db_path}')

        # Close all active database connections
        for conn in connections.all():
            try:
                conn.close()
            except Exception:
                pass

        # Safety snapshot
        if not no_safety:
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts      = datetime.now().strftime('%Y%m%d_%H%M%S')
            safety  = backup_dir / f'before_restore_{ts}.sqlite3'
            try:
                shutil.copy2(str(db_path), str(safety))
                self.stdout.write(f'Safety copy saved: {safety.name}')
            except Exception as exc:
                self.stderr.write(f'Warning: could not create safety copy: {exc}')

        # Restore using SQLite's online backup API (WAL-safe)
        try:
            with closing(sqlite3.connect(str(backup_path))) as src:
                with closing(sqlite3.connect(str(db_path))) as dst:
                    src.backup(dst)
        except Exception as exc:
            raise CommandError(f'Restore failed: {exc}')

        self.stdout.write(
            self.style.SUCCESS(
                f'\nDatabase successfully restored from {backup_path.name}.\n'
                'Restart the Django server to ensure a fresh connection pool.'
            )
        )

"""Та же последовательность, что у продовой схемы: импорт HH + enforce cap.

Запуск из CI или с ПК при подставленном ``DATABASE_URL`` базы Render — см. render.yaml
и ``.github/workflows/render-hh-import.yml``.
"""

import os

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        'Smoke test for production: fetch_hh then enforce_hh_import_cap '
        '(matches Render cron startCommand defaults).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--pages',
            type=int,
            default=1,
            help='Passed to fetch_hh (default 1, same as Render cron).',
        )
        parser.add_argument(
            '--per-page',
            type=int,
            default=40,
            help='Passed to fetch_hh (default 40, same as Render cron).',
        )
        parser.add_argument(
            '--dry-run-cap',
            action='store_true',
            help='Run enforce_hh_import_cap with --dry-run only (no deletes).',
        )

    def handle(self, *args, **opts):
        targeting_render = os.environ.get('JOBFLEX_USE_RENDER_DB', '').strip().lower() in (
            '1', 'true', 'yes', 'on',
        )
        if (
            not os.environ.get('RENDER')
            and not os.environ.get('GITHUB_ACTIONS')
            and not targeting_render
        ):
            self.stdout.write(self.style.WARNING(
                'Подсказка: сайт на Render использует БД из панели Render, не локальную SQLite/Postgres. '
                'Без Shell: файл .env.render + JOBFLEX_USE_RENDER_DB=1 (см. tools/run_render_import.ps1) '
                'или секреты в GitHub Actions «Render HH import».'
            ))
        pages = max(1, int(opts['pages']))
        per_page = min(max(1, int(opts['per_page'])), 100)
        self.stdout.write(f'--- fetch_hh --pages {pages} --per-page {per_page} ---')
        call_command('fetch_hh', pages=pages, per_page=per_page)
        self.stdout.write('--- enforce_hh_import_cap ---')
        cap_kwargs = {}
        if opts['dry_run_cap']:
            cap_kwargs['dry_run'] = True
        call_command('enforce_hh_import_cap', **cap_kwargs)
        self.stdout.write(self.style.SUCCESS('render_prod_smoke: done'))

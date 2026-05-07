"""Та же последовательность, что у Cron на Render: импорт HH + enforce cap.

Запуск в Render Shell (web): ``python manage.py render_prod_smoke``
(параметры по умолчанию совпадают с jobflex-hh-import в render.yaml).
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
        if not os.environ.get('RENDER'):
            self.stdout.write(self.style.WARNING(
                'Подсказка: открытый сайт на Render читает БД Render. '
                'Обновление прода — запуск этой команды в Shell сервиса web на Render, '
                'не на своём ПК.'
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

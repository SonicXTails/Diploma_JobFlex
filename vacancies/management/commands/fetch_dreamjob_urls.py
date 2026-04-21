import time
from django.core.management.base import BaseCommand
from django.utils import timezone

from vacancies.dreamjob import fetch_dreamjob_page, extract_rating_from_html, extract_company_name_from_html, parse_rating_candidate
from vacancies.models import Employer


class Command(BaseCommand):
    help = 'Fetch employer ratings from DreamJob public pages. Usage: manage.py fetch_dreamjob_urls <url1> <url2> ...'

    def add_arguments(self, parser):
        parser.add_argument('urls', nargs='+', help='DreamJob employer URLs')
        parser.add_argument('--delay', type=float, default=0.7, help='Seconds to sleep between requests')

    def handle(self, *args, **options):
        urls = options['urls']
        delay = options.get('delay', 0.7) or 0.7

        from difflib import SequenceMatcher

        for u in urls:
            try:
                html = fetch_dreamjob_page(u)
            except Exception as e:
                self.stderr.write(f'Failed to fetch {u}: {e}')
                continue

            name = extract_company_name_from_html(html) or ''
            candidate = extract_rating_from_html(html)
            parsed = parse_rating_candidate(candidate)

            if not name:
                self.stdout.write(f'No company name detected on {u}; candidate={candidate}')
                time.sleep(delay)
                continue

            norm_name = normalize_company_name(name)
            # build candidate list from DB with normalized names
            best = None
            best_score = 0.0
            for emp in Employer.objects.all():
                en = normalize_company_name(emp.name)
                if not en:
                    continue
                score = SequenceMatcher(a=norm_name, b=en).ratio()
                if score > best_score:
                    best_score = score
                    best = emp

            # threshold for fuzzy match
            if best and best_score >= 0.70:
                emp = best
                if parsed is not None:
                    emp.dreamjob_rating = parsed
                    emp.dreamjob_rating_raw = str(candidate)[:128]
                    emp.dreamjob_rating_updated_at = timezone.now()
                    emp.save(update_fields=['dreamjob_rating', 'dreamjob_rating_raw', 'dreamjob_rating_updated_at'])
                    self.stdout.write(f'Updated Employer id={emp.id} name="{emp.name}" -> {parsed} (score={best_score:.2f})')
                else:
                    self.stdout.write(f'Candidate found for {emp.name} but could not parse: {candidate} (score={best_score:.2f})')
            else:
                # fallback: try simple icontains
                qs = Employer.objects.filter(name__icontains=name)
                if qs.exists():
                    emp = qs.first()
                    if parsed is not None:
                        emp.dreamjob_rating = parsed
                        emp.dreamjob_rating_raw = str(candidate)[:128]
                        emp.dreamjob_rating_updated_at = timezone.now()
                        emp.save(update_fields=['dreamjob_rating', 'dreamjob_rating_raw', 'dreamjob_rating_updated_at'])
                        self.stdout.write(f'Updated Employer id={emp.id} name="{emp.name}" -> {parsed} (icontains)')
                    else:
                        self.stdout.write(f'Candidate found for {emp.name} but could not parse: {candidate} (icontains)')
                else:
                    self.stdout.write(f'No Employer match for "{name}" (from {u}); candidate={candidate} (best_score={best_score:.2f})')

            time.sleep(delay)

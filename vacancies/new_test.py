"""
Tests for the vacancies app.

Coverage:
  - vacancy_branded_frame_view (iframe HTML, X-Frame-Options, 404)
  - vacancy_description_api    (data return, pending trigger, 404)
  - backfill_descriptions_task (dedup via cache, limit, skip in-flight)
  - fetch_vacancy_description  (saves fields, no-hh-id, not-found)
  - VacancyDetailView          (200, branded branch, plain branch)
"""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from django.test import TestCase, Client
from django.urls import reverse
from django.core.cache import cache

from vacancies.models import Vacancy, Employer


# ─── helpers ──────────────────────────────────────────────────────────────────

def make_vacancy(
    external_id='test-1',
    title='Test Vacancy',
    description='',
    branded_description='',
    raw_json=None,
):
    """Create a minimal Vacancy row suitable for tests."""
    return Vacancy.objects.create(
        external_id=external_id,
        title=title,
        company='Test Corp',
        country='Россия',
        url='https://hh.ru/vacancy/123',
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        description=description,
        branded_description=branded_description,
        raw_json=raw_json or {'id': '123456'},
    )


# ─── vacancy_branded_frame_view ───────────────────────────────────────────────

class BrandedFrameViewTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.vacancy = make_vacancy(
            branded_description='<h1>Hello Employer</h1>',
        )

    def _url(self, pk=None):
        return reverse('vacancy-branded-frame', args=[pk or self.vacancy.pk])

    def test_returns_200_with_content(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Hello Employer', resp.content)

    def test_content_type_is_html(self):
        resp = self.client.get(self._url())
        self.assertIn('text/html', resp['Content-Type'])

    def test_xframe_options_absent(self):
        """@xframe_options_exempt must remove the deny header."""
        resp = self.client.get(self._url())
        self.assertNotIn('X-Frame-Options', resp)

    def test_postmessage_script_present(self):
        resp = self.client.get(self._url())
        self.assertIn(b'postMessage', resp.content)
        self.assertIn(b'branded-height', resp.content)

    def test_falls_back_to_description(self):
        v = make_vacancy(
            external_id='plain-1',
            description='<p>Plain text desc</p>',
            branded_description='',
        )
        resp = self.client.get(reverse('vacancy-branded-frame', args=[v.pk]))
        self.assertIn(b'Plain text desc', resp.content)

    def test_404_for_missing_vacancy(self):
        resp = self.client.get(reverse('vacancy-branded-frame', args=[99999]))
        self.assertEqual(resp.status_code, 404)

    def test_background_color_set(self):
        """iframe body must have light background so dark employer text is readable."""
        resp = self.client.get(self._url())
        self.assertIn(b'#faf8f5', resp.content)


# ─── vacancy_description_api ─────────────────────────────────────────────────

class DescriptionApiTests(TestCase):

    def setUp(self):
        self.client = Client()

    def _url(self, pk):
        return reverse('vacancy-description-api', args=[pk])

    def test_returns_description_when_filled(self):
        v = make_vacancy(
            external_id='api-1',
            description='<p>Some desc</p>',
            branded_description='<b>brand</b>',
        )
        resp = self.client.get(self._url(v.pk))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['pending'])
        self.assertIn('Some desc', data['description'])
        self.assertIn('brand', data['branded'])

    def test_returns_pending_when_empty(self):
        v = make_vacancy(external_id='api-2')
        with patch('vacancies.tasks.fetch_vacancy_description.apply_async') as mock_task:
            resp = self.client.get(self._url(v.pk))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['pending'])
        mock_task.assert_called_once_with(args=[v.id], priority=9)

    def test_404_for_missing_vacancy(self):
        resp = self.client.get(self._url(99999))
        self.assertEqual(resp.status_code, 404)

    def test_returns_unavailable_when_sentinel(self):
        v = make_vacancy(external_id='api-unav', description='__unavailable__')
        resp = self.client.get(self._url(v.pk))
        data = resp.json()
        self.assertFalse(data['pending'])
        self.assertTrue(data['unavailable'])
        self.assertEqual(data['description'], '')

    def test_only_description_filled_not_pending(self):
        v = make_vacancy(external_id='api-3', description='<p>desc only</p>')
        resp = self.client.get(self._url(v.pk))
        data = resp.json()
        self.assertFalse(data['pending'])


# ─── backfill_descriptions_task ──────────────────────────────────────────────

class BackfillTaskTests(TestCase):

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_queues_vacancies_without_description(self):
        v1 = make_vacancy(external_id='bf-1')
        v2 = make_vacancy(external_id='bf-2')
        with patch('vacancies.tasks.fetch_vacancy_description.apply_async') as mock_task:
            from vacancies.tasks import backfill_descriptions_task
            result = backfill_descriptions_task()
        self.assertIn('queued:2', result)
        self.assertEqual(mock_task.call_count, 2)

    def test_skips_filled_vacancies(self):
        make_vacancy(external_id='bf-filled', description='<p>already here</p>')
        with patch('vacancies.tasks.fetch_vacancy_description.apply_async') as mock_task:
            from vacancies.tasks import backfill_descriptions_task
            backfill_descriptions_task()
        mock_task.assert_not_called()

    def test_respects_limit(self):
        for i in range(10):
            make_vacancy(external_id=f'bf-limit-{i}')
        with patch('vacancies.tasks.fetch_vacancy_description.apply_async') as mock_task:
            from vacancies.tasks import backfill_descriptions_task
            backfill_descriptions_task(limit=3)
        self.assertEqual(mock_task.call_count, 3)

    def test_deduplication_skips_inflight(self):
        """Second call must not re-queue a vacancy already in the cache."""
        v = make_vacancy(external_id='bf-dedup')
        with patch('vacancies.tasks.fetch_vacancy_description.apply_async') as mock_task:
            from vacancies.tasks import backfill_descriptions_task
            backfill_descriptions_task()   # first run — queues v
            backfill_descriptions_task()   # second run — v still empty but in cache
        # Should only have been dispatched once
        self.assertEqual(mock_task.call_count, 1)


# ─── fetch_vacancy_description task ──────────────────────────────────────────

def _make_hh_response(description='<p>desc</p>', branded=''):
    """Build a fake urlopen response with HH JSON payload."""
    payload = json.dumps({
        'id': '123456',
        'description': description,
        'branded_description': branded,
        'key_skills': [{'name': 'Python'}, {'name': 'Django'}],
    }).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class FetchVacancyDescriptionTaskTests(TestCase):

    def test_saves_description_and_branded(self):
        v = make_vacancy(external_id='fvd-1')
        with patch('vacancies.tasks.urlopen', return_value=_make_hh_response(
            description='<p>Full desc</p>',
            branded='<div class="brand">Brand</div>',
        )):
            from vacancies.tasks import fetch_vacancy_description
            result = fetch_vacancy_description(v.id)

        v.refresh_from_db()
        self.assertIn('Full desc', v.description)
        self.assertIn('Brand', v.branded_description)
        self.assertIn('ok:desc=', result)

    def test_saves_key_skills(self):
        v = make_vacancy(external_id='fvd-2')
        with patch('vacancies.tasks.urlopen', return_value=_make_hh_response()):
            from vacancies.tasks import fetch_vacancy_description
            fetch_vacancy_description(v.id)
        v.refresh_from_db()
        self.assertIn('Python', v.key_skills_text)
        self.assertIn('Django', v.key_skills_text)

    def test_returns_not_found_for_missing_vacancy(self):
        from vacancies.tasks import fetch_vacancy_description
        result = fetch_vacancy_description(99999)
        self.assertEqual(result, 'not_found')

    def test_marks_unavailable_on_403(self):
        v = make_vacancy(external_id='fvd-403')
        from urllib.error import HTTPError
        http_err = HTTPError(url='', code=403, msg='Forbidden', hdrs=None, fp=None)
        with patch('vacancies.tasks.urlopen', side_effect=http_err):
            from vacancies.tasks import fetch_vacancy_description
            result = fetch_vacancy_description(v.id)
        self.assertEqual(result, 'skipped:403')
        v.refresh_from_db()
        self.assertEqual(v.description, '__unavailable__')

    def test_returns_no_hh_id_when_raw_json_empty(self):
        v = make_vacancy(external_id='fvd-3', raw_json={})
        # Force external_id to empty so hh_id resolution yields nothing
        Vacancy.objects.filter(pk=v.pk).update(external_id='', raw_json={})
        from vacancies.tasks import fetch_vacancy_description
        result = fetch_vacancy_description(v.id)
        self.assertEqual(result, 'no_hh_id')


# ─── VacancyDetailView ────────────────────────────────────────────────────────

class VacancyDetailViewTests(TestCase):

    def setUp(self):
        self.client = Client()

    def test_detail_page_200(self):
        v = make_vacancy(external_id='detail-1', description='<p>hello</p>')
        resp = self.client.get(reverse('vacancy-detail', args=[v.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_detail_page_404_for_missing(self):
        resp = self.client.get(reverse('vacancy-detail', args=[99999]))
        self.assertEqual(resp.status_code, 404)

    def test_branded_iframe_rendered_when_branded_present(self):
        v = make_vacancy(
            external_id='detail-branded',
            branded_description='<div>brand</div>',
        )
        resp = self.client.get(reverse('vacancy-detail', args=[v.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'branded-frame')
        # SSR iframe src should point to the branded frame URL
        self.assertContains(resp, f'/{v.pk}/branded/')

    def test_plain_description_rendered_when_no_branded(self):
        v = make_vacancy(
            external_id='detail-plain',
            description='<p>Plain description</p>',
        )
        resp = self.client.get(reverse('vacancy-detail', args=[v.pk]))
        self.assertContains(resp, 'vd-description')

    def test_skeleton_shown_when_both_empty(self):
        v = make_vacancy(external_id='detail-empty')
        resp = self.client.get(reverse('vacancy-detail', args=[v.pk]))
        self.assertContains(resp, 'desc-skeleton')
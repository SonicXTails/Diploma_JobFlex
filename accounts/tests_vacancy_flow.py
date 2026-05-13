from datetime import datetime, timezone
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Applicant, Application, Manager
from vacancies.models import Bookmark, Vacancy


def _make_site_vacancy(*, external_id: str, created_by: User) -> Vacancy:
    return Vacancy.objects.create(
        external_id=external_id,
        title='Python Developer',
        company='Test Company',
        country='Россия',
        url='http://localhost/site-vacancy',
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        raw_json={},
        created_by=created_by,
        is_active=True,
    )


def _make_hh_vacancy(*, external_id: str) -> Vacancy:
    return Vacancy.objects.create(
        external_id=external_id,
        title='Imported HH Vacancy',
        company='HH Company',
        country='Россия',
        url='https://hh.ru/vacancy/123',
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        raw_json={'id': '123'},
        created_by=None,
        is_active=True,
    )


class VacancyDetailInteractionsTests(TestCase):
    """Control checks for applicant/manager interactions around one vacancy."""

    def setUp(self):
        self.applicant_user = User.objects.create_user(
            username='applicant_flow',
            email='applicant_flow@example.com',
            password='test-pass-123',
        )
        Applicant.objects.create(user=self.applicant_user, telegram='@applicant_flow')

        self.manager_user = User.objects.create_user(
            username='manager_flow',
            email='manager_flow@example.com',
            password='test-pass-123',
        )
        Manager.objects.create(user=self.manager_user, telegram='@manager_flow')

        self.vacancy = _make_site_vacancy(external_id='site-flow-1', created_by=self.manager_user)

    def test_applicant_can_toggle_bookmark(self):
        self.client.force_login(self.applicant_user)
        url = reverse('accounts:api_toggle_bookmark', args=[self.vacancy.pk])

        first = self.client.post(url)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()['bookmarked'])
        self.assertTrue(Bookmark.objects.filter(user=self.applicant_user, vacancy=self.vacancy).exists())

        second = self.client.post(url)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()['bookmarked'])
        self.assertFalse(Bookmark.objects.filter(user=self.applicant_user, vacancy=self.vacancy).exists())

    def test_applicant_can_apply_with_cover_letter(self):
        self.client.force_login(self.applicant_user)
        apply_resp = self.client.post(
            reverse('accounts:api_apply'),
            data=json.dumps({'vacancy_id': self.vacancy.pk, 'cover_letter': 'Хочу у вас работать'}),
            content_type='application/json',
        )
        self.assertEqual(apply_resp.status_code, 200, apply_resp.content)
        self.assertTrue(apply_resp.json()['created'])

        app = Application.objects.get(vacancy=self.vacancy, applicant=self.applicant_user)
        self.assertEqual(app.cover_letter, 'Хочу у вас работать')
        self.assertEqual(app.status, Application.STATUS_PENDING)

    def test_repeat_apply_updates_cover_letter_while_pending(self):
        self.client.force_login(self.applicant_user)
        url = reverse('accounts:api_apply')

        first = self.client.post(
            url,
            data=json.dumps({'vacancy_id': self.vacancy.pk, 'cover_letter': 'Первая версия'}),
            content_type='application/json',
        )
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()['created'])

        second = self.client.post(
            url,
            data=json.dumps({'vacancy_id': self.vacancy.pk, 'cover_letter': 'Обновленная версия'}),
            content_type='application/json',
        )
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()['created'])

        app = Application.objects.get(vacancy=self.vacancy, applicant=self.applicant_user)
        self.assertEqual(app.cover_letter, 'Обновленная версия')

    def test_manager_can_update_application_status(self):
        app = Application.objects.create(
            vacancy=self.vacancy,
            applicant=self.applicant_user,
            cover_letter='Initial',
            status=Application.STATUS_PENDING,
        )
        self.client.force_login(self.manager_user)
        resp = self.client.post(
            reverse('accounts:api_application_status', args=[app.pk]),
            data=json.dumps({'status': Application.STATUS_ACCEPTED}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], Application.STATUS_ACCEPTED)
        app.refresh_from_db()
        self.assertEqual(app.status, Application.STATUS_ACCEPTED)

    def test_non_applicant_cannot_apply(self):
        self.client.force_login(self.manager_user)
        resp = self.client.post(
            reverse('accounts:api_apply'),
            data=json.dumps({'vacancy_id': self.vacancy.pk, 'cover_letter': 'test'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json().get('error'), 'not_applicant')

    def test_applicant_cannot_apply_to_own_vacancy(self):
        own_vacancy = _make_site_vacancy(external_id='site-own-1', created_by=self.applicant_user)
        self.client.force_login(self.applicant_user)
        resp = self.client.post(
            reverse('accounts:api_apply'),
            data=json.dumps({'vacancy_id': own_vacancy.pk, 'cover_letter': 'test'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json().get('error'), 'own_vacancy')

    def test_applicant_cannot_apply_to_hh_vacancy(self):
        hh_vacancy = _make_hh_vacancy(external_id='hh-flow-1')
        self.client.force_login(self.applicant_user)
        resp = self.client.post(
            reverse('accounts:api_apply'),
            data=json.dumps({'vacancy_id': hh_vacancy.pk, 'cover_letter': 'test'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get('error'), 'hh_vacancy')

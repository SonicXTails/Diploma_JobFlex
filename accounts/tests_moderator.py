from datetime import datetime, timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Administrator, Moderator, Manager
from vacancies.models import Vacancy, VacancyReport


def _make_site_vacancy(external_id='site-test-1'):
    return Vacancy.objects.create(
        external_id=external_id,
        title='Site vacancy',
        company='Site company',
        country='Россия',
        url='http://localhost/site-vacancy',
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        raw_json={},
    )


class ModeratorRoleTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='admin-pass-123',
            is_superuser=True,
            is_staff=True,
        )
        Administrator.objects.create(user=self.admin)

    def test_admin_can_create_moderator_from_admin_users_page(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('accounts:admin_users'),
            data={
                'action': 'create_moderator',
                'new_moderator_username': 'mod1',
                'new_moderator_email': 'mod1@example.com',
                'new_moderator_password': 'mod-pass-123',
                'new_moderator_first_name': 'Mod',
                'new_moderator_last_name': 'Erator',
            },
        )
        self.assertEqual(resp.status_code, 302)
        created_user = User.objects.filter(username='mod1').first()
        self.assertIsNotNone(created_user)
        self.assertTrue(Moderator.objects.filter(user=created_user).exists())

    def test_moderator_profile_redirects_from_profile_to_workspace(self):
        user = User.objects.create_user(
            username='moderator-user',
            email='moderator@example.com',
            password='mod-pass-123',
        )
        Moderator.objects.create(user=user)
        self.client.force_login(user)

        resp = self.client.get(reverse('accounts:profile'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('accounts:moderator_analytics'))

    def test_non_moderator_cannot_update_report_status(self):
        reporter = User.objects.create_user('reporter', 'reporter@example.com', 'test-pass-123')
        vac = _make_site_vacancy()
        report = VacancyReport.objects.create(
            vacancy=vac,
            user=reporter,
            reason_code=VacancyReport.REASON_SPAM,
            reason_text='spam',
        )
        self.client.force_login(reporter)
        resp = self.client.post(
            reverse('report-self-status', args=[report.pk]),
            data='{"self_status":"done","moderator_note":"ok"}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_manager_cannot_open_moderator_workspace(self):
        manager_user = User.objects.create_user('manager1', 'manager1@example.com', 'test-pass-123')
        Manager.objects.create(user=manager_user, telegram='@manager1')
        self.client.force_login(manager_user)
        resp = self.client.get(reverse('accounts:moderator_analytics'))
        self.assertEqual(resp.status_code, 403)


from datetime import datetime, timedelta, timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone as dj_timezone

from accounts.models import Applicant, Application, CalendarNote, Interview, Manager
from vacancies.models import Vacancy


def _vacancy_for_manager(*, external_id: str, manager_user: User, title: str) -> Vacancy:
    return Vacancy.objects.create(
        external_id=external_id,
        title=title,
        company='Demo Company',
        country='Россия',
        region='Москва',
        url='http://localhost/manager-vacancy',
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        raw_json={},
        created_by=manager_user,
        is_active=True,
    )


class ManagerAnalyticsCalendarTests(TestCase):
    def setUp(self):
        self.manager_user = User.objects.create_user('mgr_analytics', 'mgr_analytics@example.com', 'pw-test-123')
        Manager.objects.create(user=self.manager_user, telegram='@mgr_analytics')

        self.other_manager_user = User.objects.create_user('mgr_other_analytics', 'mgr_other_analytics@example.com', 'pw-test-123')
        Manager.objects.create(user=self.other_manager_user, telegram='@mgr_other_analytics')

        self.applicant_user = User.objects.create_user('app_analytics', 'app_analytics@example.com', 'pw-test-123')
        Applicant.objects.create(user=self.applicant_user, telegram='@app_analytics', city='Москва')

    def test_manager_analytics_page_denies_non_manager(self):
        self.client.force_login(self.applicant_user)
        denied_resp = self.client.get(reverse('accounts:manager_analytics'))
        self.assertEqual(denied_resp.status_code, 302)
        self.assertEqual(denied_resp.url, reverse('vacancy-list'))

    def test_manager_calendar_events_include_only_own_data(self):
        target_dt = dj_timezone.now() + timedelta(days=1)
        target_date = target_dt.date()

        own_vac = _vacancy_for_manager(
            external_id='mgr-cal-own',
            manager_user=self.manager_user,
            title='Own vacancy',
        )
        foreign_vac = _vacancy_for_manager(
            external_id='mgr-cal-foreign',
            manager_user=self.other_manager_user,
            title='Foreign vacancy',
        )

        own_app = Application.objects.create(
            vacancy=own_vac,
            applicant=self.applicant_user,
            cover_letter='Own application',
            status=Application.STATUS_PENDING,
        )
        Application.objects.filter(pk=own_app.pk).update(
            created_at=datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
        )

        foreign_app = Application.objects.create(
            vacancy=foreign_vac,
            applicant=self.applicant_user,
            cover_letter='Foreign application',
            status=Application.STATUS_PENDING,
        )
        Application.objects.filter(pk=foreign_app.pk).update(
            created_at=datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
        )

        Interview.objects.create(
            manager=self.manager_user,
            applicant=self.applicant_user,
            vacancy=own_vac,
            scheduled_at=target_dt,
            status=Interview.STATUS_SCHEDULED,
            location='Zoom',
        )
        CalendarNote.objects.create(
            user=self.manager_user,
            date=target_date,
            title='Manager note',
            text='Prepare interview questions',
            color='#c2a35a',
        )

        self.client.force_login(self.manager_user)
        resp = self.client.get(
            reverse('accounts:api_manager_calendar_events'),
            {'date': target_date.isoformat()},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        payload = resp.json()
        events = payload.get('events', [])
        month_marks = payload.get('month_marks', {})

        event_types = {e.get('type') for e in events}
        self.assertIn('application', event_types)
        self.assertIn('interview', event_types)
        self.assertIn('note', event_types)

        # Ensure we do not leak foreign manager vacancy data.
        titles_joined = ' | '.join(str(e.get('title') or '') + ' ' + str(e.get('sub') or '') for e in events)
        self.assertIn('Own vacancy', titles_joined)
        self.assertNotIn('Foreign vacancy', titles_joined)

        self.assertIn(target_date.isoformat(), month_marks)
        self.assertTrue(month_marks[target_date.isoformat()])

    def test_api_manager_calendar_forbidden_for_non_manager(self):
        self.client.force_login(self.applicant_user)
        resp = self.client.get(reverse('accounts:api_manager_calendar_events'), {'date': '2026-05-08'})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json().get('error'), 'forbidden')

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone as dj_timezone

from accounts.models import Applicant, Application, CalendarNote, Chat, Interview, Manager
from vacancies.models import Vacancy


def _make_site_vacancy(*, external_id: str, created_by: User) -> Vacancy:
    return Vacancy.objects.create(
        external_id=external_id,
        title='QA Local Vacancy',
        company='QA Company',
        country='Россия',
        url='http://localhost/local-vacancy',
        published_at=dj_timezone.now(),
        raw_json={},
        created_by=created_by,
        is_active=True,
    )


class InterviewChatCalendarTests(TestCase):
    def setUp(self):
        self.manager_user = User.objects.create_user('mgr_itv', 'mgr_itv@example.com', 'pw-test-123')
        Manager.objects.create(user=self.manager_user, telegram='@mgr_itv')

        self.applicant_user = User.objects.create_user('app_itv', 'app_itv@example.com', 'pw-test-123')
        Applicant.objects.create(user=self.applicant_user, telegram='@app_itv')

        self.other_user = User.objects.create_user('plain_user', 'plain@example.com', 'pw-test-123')

        self.vacancy = _make_site_vacancy(external_id='itv-local-1', created_by=self.manager_user)
        self.application = Application.objects.create(
            vacancy=self.vacancy,
            applicant=self.applicant_user,
            cover_letter='Cover letter',
            status=Application.STATUS_PENDING,
        )

    @patch('accounts.tasks.send_interview_notification_task.apply_async')
    @patch('accounts.views.send_mail')
    @patch('accounts.views.send_hello_async')
    @patch('accounts.views.notify_new_chat_message')
    def test_manager_can_schedule_interview_and_application_becomes_accepted(
        self,
        _mock_notify,
        _mock_tg,
        _mock_mail,
        _mock_apply_async,
    ):
        self.client.force_login(self.manager_user)
        resp = self.client.post(
            reverse('accounts:api_interview_schedule'),
            data=json.dumps({
                'applicant_user_id': self.applicant_user.pk,
                'vacancy_id': self.vacancy.pk,
                'date': (dj_timezone.now() + timedelta(days=2)).strftime('%Y-%m-%d'),
                'time': '11:30',
                'location': 'Zoom',
                'notes': 'Bring resume',
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()['ok'])

        itv = Interview.objects.get(manager=self.manager_user, applicant=self.applicant_user)
        self.assertEqual(itv.status, Interview.STATUS_SCHEDULED)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.STATUS_ACCEPTED)
        self.assertTrue(Chat.objects.filter(manager=self.manager_user, applicant=self.applicant_user).exists())

    def test_non_manager_cannot_schedule_interview(self):
        self.client.force_login(self.applicant_user)
        resp = self.client.post(
            reverse('accounts:api_interview_schedule'),
            data=json.dumps({
                'applicant_user_id': self.applicant_user.pk,
                'date': '2026-05-20',
                'time': '10:00',
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json().get('error'), 'forbidden')

    @patch('accounts.tasks.send_interview_notification_task.apply_async')
    @patch('accounts.views.send_mail')
    @patch('accounts.views.send_hello_async')
    @patch('accounts.views.notify_new_chat_message')
    def test_schedule_accepts_form_encoded_payload(
        self,
        _mock_notify,
        _mock_tg,
        _mock_mail,
        _mock_apply_async,
    ):
        self.client.force_login(self.manager_user)
        resp = self.client.post(
            reverse('accounts:api_interview_schedule'),
            data={
                'applicant_user_id': str(self.applicant_user.pk),
                'vacancy_id': str(self.vacancy.pk),
                'date': (dj_timezone.now() + timedelta(days=3)).strftime('%Y-%m-%d'),
                'time': '12:15',
                'location': 'Office',
                'notes': 'Bring docs',
            },
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()['ok'])

    @patch('accounts.views.send_mail')
    @patch('accounts.views.send_hello_async')
    @patch('accounts.views.notify_new_chat_message')
    def test_interview_cancel_with_reject_sets_application_rejected(self, _mock_notify, _mock_tg, _mock_mail):
        itv = Interview.objects.create(
            manager=self.manager_user,
            applicant=self.applicant_user,
            vacancy=self.vacancy,
            scheduled_at=dj_timezone.now() + timedelta(days=1),
            status=Interview.STATUS_SCHEDULED,
        )
        self.application.status = Application.STATUS_ACCEPTED
        self.application.save(update_fields=['status'])

        self.client.force_login(self.manager_user)
        resp = self.client.delete(
            reverse('accounts:api_interview_cancel'),
            data=json.dumps({'id': itv.pk, 'action': 'reject'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        itv.refresh_from_db()
        self.assertEqual(itv.status, Interview.STATUS_CANCELLED)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.STATUS_REJECTED)

    @patch('accounts.views.notify_new_chat_message')
    def test_chat_start_send_and_fetch_messages(self, _mock_notify):
        self.client.force_login(self.manager_user)
        start = self.client.post(
            reverse('accounts:api_chat_start'),
            data=json.dumps({'applicant_user_id': self.applicant_user.pk}),
            content_type='application/json',
        )
        self.assertEqual(start.status_code, 200)
        chat_id = start.json()['chat_id']

        sent = self.client.post(
            reverse('accounts:api_chat_send', args=[chat_id]),
            data=json.dumps({'text': 'Hello from manager'}),
            content_type='application/json',
        )
        self.assertEqual(sent.status_code, 200, sent.content)
        self.assertTrue(sent.json()['ok'])

        self.client.logout()
        self.client.force_login(self.applicant_user)
        msgs = self.client.get(reverse('accounts:api_chat_messages', args=[chat_id]), {'since': 0})
        self.assertEqual(msgs.status_code, 200)
        payload = msgs.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(len(payload['messages']), 1)
        self.assertEqual(payload['messages'][0]['text'], 'Hello from manager')

    def test_only_manager_can_start_chat(self):
        self.client.force_login(self.applicant_user)
        resp = self.client.post(
            reverse('accounts:api_chat_start'),
            data=json.dumps({'applicant_user_id': self.applicant_user.pk}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json().get('error'), 'only_managers')

    def test_resume_open_marks_pending_application_viewed_for_manager(self):
        self.application.status = Application.STATUS_PENDING
        self.application.save(update_fields=['status'])

        self.client.force_login(self.manager_user)
        # Use resume_word_view because it updates status before redirecting to resume_pdf
        # when no DOC/DOCX file is uploaded, and avoids template-rendering issues in tests.
        resp = self.client.get(reverse('accounts:resume_word_view', args=[self.applicant_user.applicant.pk]))
        self.assertEqual(resp.status_code, 302)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, Application.STATUS_VIEWED)

    def test_applicant_calendar_events_contains_own_application(self):
        target_day = self.application.created_at.date().isoformat()
        self.client.force_login(self.applicant_user)
        resp = self.client.get(reverse('accounts:api_calendar_events'), {'date': target_day})
        self.assertEqual(resp.status_code, 200)
        events = resp.json()['events']
        self.assertTrue(any(e.get('type') == 'application' for e in events))

    def test_manager_calendar_events_contains_application_interview_and_note(self):
        dt = dj_timezone.now() + timedelta(days=1)
        Interview.objects.create(
            manager=self.manager_user,
            applicant=self.applicant_user,
            vacancy=self.vacancy,
            scheduled_at=dt,
            status=Interview.STATUS_SCHEDULED,
        )
        CalendarNote.objects.create(
            user=self.manager_user,
            date=dt.date(),
            title='Check candidate',
            text='Prepare questions',
            color='#c2a35a',
        )
        # Force application date to same day for deterministic event aggregation.
        Application.objects.filter(pk=self.application.pk).update(
            created_at=datetime.combine(dt.date(), datetime.min.time(), tzinfo=timezone.utc)
        )
        self.application.refresh_from_db()

        self.client.force_login(self.manager_user)
        resp = self.client.get(reverse('accounts:api_manager_calendar_events'), {'date': dt.date().isoformat()})
        self.assertEqual(resp.status_code, 200, resp.content)
        events = resp.json()['events']
        types = {e.get('type') for e in events}
        self.assertIn('application', types)
        self.assertIn('interview', types)
        self.assertIn('note', types)

from datetime import datetime, timezone
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import Moderator, Applicant, Administrator
from vacancies.models import (
    Vacancy, VacancyReport, VacancyModerationState,
    ModeratorDeletionReport, ModeratorDeletionPhoto,
)


def _make_png_bytes():
    """1x1 transparent PNG — valid image content for ImageField tests."""
    try:
        from PIL import Image
        buf = BytesIO()
        Image.new('RGBA', (1, 1), (0, 0, 0, 0)).save(buf, format='PNG')
        return buf.getvalue()
    except Exception:
        # Minimal valid PNG header (1x1 transparent).
        return (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00\x01'
            b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        )


def _make_vacancy(external_id='site-vac', *, hh=False):
    url = 'https://hh.ru/vacancy/123' if hh else 'http://localhost/site-vacancy'
    return Vacancy.objects.create(
        external_id=external_id,
        title='Vacancy',
        company='Company',
        country='Россия',
        url=url,
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        raw_json={},
    )


class VacancyReportApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('user1', 'user1@example.com', 'test-pass-123')
        Applicant.objects.create(user=self.user, telegram='@user1')
        self.moderator_user = User.objects.create_user('mod1', 'mod1@example.com', 'test-pass-123')
        Moderator.objects.create(user=self.moderator_user)
        self.admin_user = User.objects.create_user(
            'admin1', 'admin1@example.com', 'test-pass-123', is_superuser=True, is_staff=True
        )
        Administrator.objects.create(user=self.admin_user)

    def test_user_can_report_only_once(self):
        vac = _make_vacancy('site-report-1')
        self.client.force_login(self.user)

        url = reverse('vacancy-report', args=[vac.pk])
        first = self.client.post(
            url,
            data='{"reason_code":"scam","reason_text":"Suspicious"}',
            content_type='application/json',
        )
        second = self.client.post(
            url,
            data='{"reason_code":"spam","reason_text":"Spam"}',
            content_type='application/json',
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(VacancyReport.objects.filter(user=self.user, vacancy=vac).count(), 1)
        self.assertTrue(second.json().get('already_reported'))

    def test_user_cannot_report_hh_vacancy(self):
        vac = _make_vacancy('hh-report-1', hh=True)
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse('vacancy-report', args=[vac.pk]),
            data='{"reason_code":"scam","reason_text":"Suspicious"}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get('error'), 'hh_vacancy_not_reportable')

    def test_other_reason_requires_text(self):
        vac = _make_vacancy('site-report-2')
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse('vacancy-report', args=[vac.pk]),
            data='{"reason_code":"other","reason_text":""}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get('error'), 'reason_text_required')

    def test_moderator_cannot_report_vacancy(self):
        vac = _make_vacancy('site-report-4')
        self.client.force_login(self.moderator_user)
        resp = self.client.post(
            reverse('vacancy-report', args=[vac.pk]),
            data='{"reason_code":"scam","reason_text":"Suspicious"}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json().get('error'), 'forbidden_role')

    def test_admin_cannot_report_vacancy(self):
        vac = _make_vacancy('site-report-5')
        self.client.force_login(self.admin_user)
        resp = self.client.post(
            reverse('vacancy-report', args=[vac.pk]),
            data='{"reason_code":"scam","reason_text":"Suspicious"}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json().get('error'), 'forbidden_role')

    def test_moderator_updates_self_status(self):
        vac = _make_vacancy('site-report-3')
        report = VacancyReport.objects.create(
            vacancy=vac,
            user=self.user,
            reason_code=VacancyReport.REASON_MISLEADING,
            reason_text='Wrong description',
        )
        self.client.force_login(self.moderator_user)
        resp = self.client.post(
            reverse('report-self-status', args=[report.pk]),
            data='{"self_status":"in_work","moderator_note":"Checking now"}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        report.refresh_from_db()
        self.assertEqual(report.self_status, VacancyReport.SELF_STATUS_IN_WORK)
        self.assertEqual(report.reviewed_by, self.moderator_user)

    def test_moderator_updates_vacancy_card_state(self):
        vac = _make_vacancy('site-report-6')
        self.client.force_login(self.moderator_user)
        resp = self.client.post(
            reverse('vacancy-moderation-state', args=[vac.pk]),
            data='{"status":"waiting","note":"Жду ответ от менеджера"}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        state = VacancyModerationState.objects.get(vacancy=vac, moderator=self.moderator_user)
        self.assertEqual(state.status, VacancyModerationState.STATUS_WAITING)
        self.assertEqual(state.note, 'Жду ответ от менеджера')

    def test_non_moderator_cannot_update_vacancy_card_state(self):
        vac = _make_vacancy('site-report-7')
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse('vacancy-moderation-state', args=[vac.pk]),
            data='{"status":"in_work","note":"try"}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)


class ModeratorVacancyDeletionTests(TestCase):
    def setUp(self):
        self.applicant_user = User.objects.create_user('applicant', 'a@example.com', 'pw-test-123')
        Applicant.objects.create(user=self.applicant_user, telegram='@a')
        self.moderator_user = User.objects.create_user('modx', 'm@example.com', 'pw-test-123')
        Moderator.objects.create(user=self.moderator_user)
        self.admin_user = User.objects.create_user(
            'adminx', 'x@example.com', 'pw-test-123', is_superuser=True, is_staff=True,
        )
        Administrator.objects.create(user=self.admin_user)

    def test_moderator_deletes_vacancy_and_creates_report(self):
        vac = _make_vacancy('site-del-1')
        VacancyReport.objects.create(
            vacancy=vac, user=self.applicant_user,
            reason_code=VacancyReport.REASON_SCAM, reason_text='fraud',
        )
        self.client.force_login(self.moderator_user)
        photo = SimpleUploadedFile('evidence.png', _make_png_bytes(), content_type='image/png')
        resp = self.client.post(
            reverse('moderator-vacancy-delete', args=[vac.pk]),
            data={'reason': 'Это явный скам.', 'photos': [photo]},
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertTrue(body['ok'])
        vac.refresh_from_db()
        self.assertTrue(vac.is_moderator_deleted)
        self.assertFalse(vac.is_active)
        report = ModeratorDeletionReport.objects.get(pk=body['report_id'])
        self.assertEqual(report.moderator, self.moderator_user)
        self.assertEqual(report.reports_count, 1)
        self.assertEqual(report.dominant_reason_code, 'scam')
        self.assertEqual(report.photos.count(), 1)

    def test_non_moderator_cannot_delete_vacancy(self):
        vac = _make_vacancy('site-del-2')
        self.client.force_login(self.applicant_user)
        resp = self.client.post(
            reverse('moderator-vacancy-delete', args=[vac.pk]),
            data={'reason': 'test'},
        )
        self.assertEqual(resp.status_code, 403)

    def test_deletion_requires_reason(self):
        vac = _make_vacancy('site-del-3')
        self.client.force_login(self.moderator_user)
        resp = self.client.post(
            reverse('moderator-vacancy-delete', args=[vac.pk]),
            data={'reason': ''},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get('error'), 'reason_required')

    def test_deleted_vacancy_hidden_from_public(self):
        vac = _make_vacancy('site-del-4')
        vac.is_moderator_deleted = True
        vac.is_active = False
        vac.save(update_fields=['is_moderator_deleted', 'is_active'])
        self.client.force_login(self.applicant_user)
        resp = self.client.get(reverse('vacancy-detail', args=[vac.external_id]))
        self.assertEqual(resp.status_code, 404)

    def test_admin_can_restore_vacancy(self):
        vac = _make_vacancy('site-del-5')
        self.client.force_login(self.moderator_user)
        self.client.post(
            reverse('moderator-vacancy-delete', args=[vac.pk]),
            data={'reason': 'Мошенничество'},
        )
        report = ModeratorDeletionReport.objects.get(vacancy=vac)
        self.client.logout()
        self.client.force_login(self.admin_user)
        resp = self.client.post(
            reverse('moderator-report-restore', args=[report.pk]),
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        report.refresh_from_db()
        vac.refresh_from_db()
        self.assertTrue(report.is_restored)
        self.assertEqual(report.restored_by, self.admin_user)
        self.assertFalse(vac.is_moderator_deleted)
        self.assertTrue(vac.is_active)

    def test_non_admin_cannot_restore_vacancy(self):
        vac = _make_vacancy('site-del-6')
        self.client.force_login(self.moderator_user)
        self.client.post(
            reverse('moderator-vacancy-delete', args=[vac.pk]),
            data={'reason': 'reason'},
        )
        report = ModeratorDeletionReport.objects.get(vacancy=vac)
        self.client.logout()
        self.client.force_login(self.moderator_user)
        resp = self.client.post(
            reverse('moderator-report-restore', args=[report.pk]),
        )
        self.assertEqual(resp.status_code, 403)

    def test_admin_pdf_download(self):
        vac = _make_vacancy('site-del-7')
        self.client.force_login(self.moderator_user)
        self.client.post(
            reverse('moderator-vacancy-delete', args=[vac.pk]),
            data={'reason': 'Мошенничество'},
        )
        report = ModeratorDeletionReport.objects.get(vacancy=vac)
        self.client.logout()
        self.client.force_login(self.admin_user)
        resp = self.client.get(
            reverse('accounts:admin_moderator_report_pdf', args=[report.pk]),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF'))

    def test_admin_reports_page_lists_report(self):
        vac = _make_vacancy('site-del-8')
        self.client.force_login(self.moderator_user)
        self.client.post(
            reverse('moderator-vacancy-delete', args=[vac.pk]),
            data={'reason': 'Мошенничество'},
        )
        self.client.logout()
        self.client.force_login(self.admin_user)
        resp = self.client.get(reverse('accounts:admin_moderator_reports'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Отчёты модераторов')
        self.assertContains(resp, vac.title)

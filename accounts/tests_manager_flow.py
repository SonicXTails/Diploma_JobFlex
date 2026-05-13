from datetime import datetime, timezone

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Applicant, Application, Manager
from vacancies.models import Vacancy
from vacancies.views import _parse_vacancy_post


def _create_site_vacancy(*, external_id: str, created_by: User, title: str = 'Manager Vacancy') -> Vacancy:
    return Vacancy.objects.create(
        external_id=external_id,
        title=title,
        company='Demo Company',
        country='Россия',
        region='Москва',
        url='http://localhost/demo-vacancy',
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        raw_json={},
        created_by=created_by,
        is_active=True,
    )


class ManagerFlowTests(TestCase):
    def setUp(self):
        self.manager_user = User.objects.create_user('mgr_flow2', 'mgr_flow2@example.com', 'pw-test-123')
        Manager.objects.create(user=self.manager_user, telegram='@mgr_flow2', company='Demo Company')

        self.other_manager_user = User.objects.create_user('mgr_other', 'mgr_other@example.com', 'pw-test-123')
        Manager.objects.create(user=self.other_manager_user, telegram='@mgr_other', company='Other Company')

        self.applicant_user = User.objects.create_user('app_flow2', 'app_flow2@example.com', 'pw-test-123')
        Applicant.objects.create(user=self.applicant_user, telegram='@app_flow2', city='Москва')

    def test_manager_can_create_edit_toggle_and_delete_vacancy(self):
        self.client.force_login(self.manager_user)

        create_resp = self.client.post(
            reverse('vacancy-create'),
            data={
                'title': 'Backend Engineer',
                'company': 'Demo Company',
                'region': 'Москва',
                'description': 'Ищем backend-разработчика с опытом командной разработки на Django.',
                'experience_id': 'between1And3',
                'employment_id': 'full',
                'key_skills': 'Python, Django',
                'work_schedule': '5/2',
                'hours_per_day': '8',
                'contact_phone': '+7 (999) 123-45-67',
                'salary_currency': 'RUR',
            },
        )
        self.assertEqual(create_resp.status_code, 302)
        vac = Vacancy.objects.filter(created_by=self.manager_user, title='Backend Engineer').first()
        self.assertIsNotNone(vac)

        edit_resp = self.client.post(
            reverse('vacancy-edit', args=[vac.pk]),
            data={
                'title': 'Senior Backend Engineer',
                'company': 'Demo Company',
                'region': 'Москва',
                'description': 'Обновлённое описание вакансии для senior backend-разработчика в продуктовой команде.',
                'experience_id': 'between3And6',
                'employment_id': 'full',
                'key_skills': 'Python, Django, PostgreSQL',
                'work_schedule': '5/2',
                'hours_per_day': '8',
                'contact_phone': '+7 (999) 123-45-67',
                'salary_currency': 'RUR',
            },
        )
        self.assertEqual(edit_resp.status_code, 302)
        vac.refresh_from_db()
        self.assertEqual(vac.title, 'Senior Backend Engineer')

        toggle_resp = self.client.patch(reverse('vacancy-toggle-active', args=[vac.pk]))
        self.assertEqual(toggle_resp.status_code, 200)
        self.assertFalse(toggle_resp.json()['is_active'])
        vac.refresh_from_db()
        self.assertFalse(vac.is_active)

        delete_resp = self.client.post(reverse('vacancy-delete', args=[vac.pk]))
        self.assertEqual(delete_resp.status_code, 302)
        self.assertFalse(Vacancy.objects.filter(pk=vac.pk).exists())

    def test_non_manager_cannot_create_vacancy(self):
        self.client.force_login(self.applicant_user)
        resp = self.client.post(
            reverse('vacancy-create'),
            data={'title': 'X', 'company': 'Y', 'region': 'Москва'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('vacancy-list'))

    def test_manager_create_rejects_latin_city_and_too_few_required_fields(self):
        data, errors = _parse_vacancy_post({
            'title': 'Backend Engineer',
            'company': 'Demo Company',
            'region': 'Moscow',
            'description': 'Коротко',
            'salary_currency': 'RUR',
        })
        self.assertIsInstance(data, dict)
        self.assertIn('region', errors)
        self.assertIn('description', errors)
        self.assertIn('key_skills', errors)
        self.assertIn('work_schedule', errors)
        self.assertIn('hours_per_day', errors)
        self.assertIn('contact_phone', errors)

    def test_manager_can_export_csv_for_own_vacancy(self):
        vac = _create_site_vacancy(external_id='mgr-csv-1', created_by=self.manager_user, title='CSV Vacancy')
        Application.objects.create(vacancy=vac, applicant=self.applicant_user, cover_letter='Hello')

        self.client.force_login(self.manager_user)
        resp = self.client.get(reverse('accounts:export_applications_csv', args=[vac.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('text/csv', resp['Content-Type'])
        body = resp.content.decode('utf-8-sig')
        self.assertIn('Сопроводительное письмо', body)
        self.assertIn('app_flow2@example.com', body)
        self.assertIn('Hello', body)

    def test_manager_cannot_access_other_manager_applications_or_csv(self):
        vac = _create_site_vacancy(external_id='mgr-private-1', created_by=self.manager_user, title='Private Vacancy')
        Application.objects.create(vacancy=vac, applicant=self.applicant_user, cover_letter='Private')

        self.client.force_login(self.other_manager_user)
        page_resp = self.client.get(reverse('accounts:vacancy_applications', args=[vac.pk]))
        csv_resp = self.client.get(reverse('accounts:export_applications_csv', args=[vac.pk]))

        self.assertEqual(page_resp.status_code, 302)
        self.assertEqual(page_resp.url, reverse('vacancy-list'))
        self.assertEqual(csv_resp.status_code, 302)
        self.assertEqual(csv_resp.url, reverse('vacancy-list'))

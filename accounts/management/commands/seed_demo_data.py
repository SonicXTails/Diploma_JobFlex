import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import (
    Applicant,
    Application,
    CalendarNote,
    Chat,
    Education,
    ExtraEducation,
    FilterPreset,
    Interview,
    Manager,
    Message,
    UserUiPreference,
    WorkExperience,
)
from vacancies.models import Bookmark, Employer, Review, Vacancy, VacancyView


class Command(BaseCommand):
    help = "Populate database with realistic demo data for UI testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default="DemoPass123!",
            help="Password for all demo users (default: DemoPass123!)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(42)
        password = options["password"]
        now = timezone.now()

        managers = self._create_managers(password=password)
        applicants = self._create_applicants(password=password)
        hh_employers = self._create_hh_employers()
        vacancies = self._create_vacancies(managers=managers, employers=hh_employers, now=now)

        self._create_reviews(vacancies=vacancies)
        applications = self._create_applications(applicants=applicants, vacancies=vacancies, now=now)
        self._create_bookmarks_and_views(applicants=applicants, vacancies=vacancies, now=now)
        self._create_chats_and_messages(applications=applications, now=now)
        self._create_interviews(applications=applications, now=now)
        self._create_calendar_notes(users=[*managers, *applicants], now=now)
        self._create_filter_presets(applicants=applicants)
        self._create_ui_preferences(users=[*managers, *applicants])

        self.stdout.write(self.style.SUCCESS("Demo data successfully seeded."))
        self.stdout.write(
            self.style.WARNING(
                "Manager users: demo_manager_1..4 | Applicant users: demo_applicant_1..10"
            )
        )
        self.stdout.write(self.style.WARNING(f"Password for all demo users: {password}"))

    def _create_user(self, username, password, first_name, last_name, email):
        user, _ = User.objects.get_or_create(username=username)
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        user.is_active = True
        user.set_password(password)
        user.save()
        return user

    def _create_managers(self, password):
        companies = [
            "ООО Альфа Тех",
            "ЗАО Север-Логистика",
            "ИП Соколова",
            "JobFlex Partners",
        ]
        cities = ["Москва", "Санкт-Петербург", "Казань", "Екатеринбург"]
        managers = []

        for i in range(1, 5):
            user = self._create_user(
                username=f"demo_manager_{i}",
                password=password,
                first_name=f"Менеджер{i}",
                last_name="Тестов",
                email=f"manager{i}@demo.local",
            )
            manager, _ = Manager.objects.get_or_create(user=user)
            manager.patronymic = "Иванович" if i % 2 else ""
            manager.company = companies[i - 1]
            manager.phone = f"+7 (9{i}1) 123-45-6{i}"
            manager.telegram = f"@demomgr{i}" if i != 4 else ""
            manager.consent_email = i % 2 == 1
            manager.consent_telegram = i in (1, 3)
            manager.save()
            managers.append(user)

            # Mirror manager city into applicant profile if it already exists.
            # (Role switch UX in project relies on shared user and can display either profile.)
            applicant = Applicant.objects.filter(user=user).first()
            if applicant:
                applicant.city = cities[i - 1]
                applicant.save(update_fields=["city"])

        return managers

    def _create_applicants(self, password):
        first_names = ["Алексей", "Мария", "Денис", "Ольга", "Руслан", "Елена", "Игорь", "Светлана", "Павел", "Наталья"]
        last_names = ["Петров", "Смирнова", "Кузнецов", "Иванова", "Соколов", "Волкова", "Лебедев", "Козлова", "Новиков", "Орлова"]
        cities = ["Москва", "Санкт-Петербург", "Новосибирск", "Казань", "Самара", "Уфа", "Тула", "Краснодар", "Томск", "Воронеж"]
        citizenships = ["RU", "BY", "KZ", "KG", "AM", "TJ", "UZ", "UA", "MD", "AZ"]
        applicants = []

        for i in range(1, 11):
            user = self._create_user(
                username=f"demo_applicant_{i}",
                password=password,
                first_name=first_names[i - 1],
                last_name=last_names[i - 1],
                email=f"applicant{i}@demo.local" if i % 3 != 0 else "",
            )
            applicant, _ = Applicant.objects.get_or_create(user=user)
            applicant.patronymic = "Сергеевич" if i % 2 else ""
            applicant.telegram = f"@demoapp{i}"
            applicant.phone = f"+7 (90{i}) 55{i}-2{i}-0{i}"
            applicant.gender = "M" if i % 2 else "F"
            applicant.city = cities[i - 1]
            applicant.birth_date = timezone.localdate() - timedelta(days=365 * (20 + i))
            applicant.citizenship = citizenships[i - 1]
            applicant.skills = random.sample(
                ["Python", "Django", "SQL", "Docker", "Git", "React", "Figma", "Excel", "1C", "Linux"],
                k=4,
            )
            applicant.consent_email = bool(user.email) and (i % 2 == 0)
            applicant.consent_telegram = i % 2 == 1
            applicant.salary_expectation_from = 70000 + i * 15000
            applicant.salary_expectation_to = applicant.salary_expectation_from + 60000
            applicant.desired_position = random.choice(
                ["Python-разработчик", "Аналитик данных", "Менеджер проектов", "QA инженер"]
            )
            applicant.about_me = "Ищу интересные проекты, где можно расти и приносить пользу команде."
            if i % 2 == 0:
                applicant.location_type = "metro"
                applicant.metro_city_id = "1"
                applicant.metro_station_id = f"{10+i}"
                applicant.metro_station_name = random.choice(["Курская", "Технопарк", "Площадь Ленина", "Горьковская"])
                applicant.metro_line_name = random.choice(["Сокольническая", "Арбатско-Покровская", "Невско-Василеостровская"])
                applicant.metro_line_color = random.choice(["#d32f2f", "#388e3c", "#1976d2"])
                applicant.metro_stations = [
                    {
                        "cityId": "1",
                        "stationId": applicant.metro_station_id,
                        "stationName": applicant.metro_station_name,
                        "lineName": applicant.metro_line_name,
                        "lineColor": applicant.metro_line_color,
                    }
                ]
                applicant.address = ""
            else:
                applicant.location_type = "address"
                applicant.address = f"г. {cities[i - 1]}, ул. Тестовая, д. {i * 3}"
                applicant.metro_stations = []
            applicant.save()
            applicants.append(user)

            self._upsert_education_and_experience(applicant=applicant, index=i)

        return applicants

    def _upsert_education_and_experience(self, applicant, index):
        Education.objects.filter(applicant=applicant).delete()
        WorkExperience.objects.filter(applicant=applicant).delete()
        ExtraEducation.objects.filter(applicant=applicant).delete()

        Education.objects.create(
            applicant=applicant,
            level=random.choice(["bachelor", "master", "higher", "vocational"]),
            institution=random.choice(
                ["МГУ", "СПбГУ", "КФУ", "НГУ", "МГТУ им. Баумана", "ИТМО"]
            ),
            graduation_year=2012 + index,
            faculty=random.choice(["Информатика", "Экономика", "Менеджмент", "Прикладная математика"]),
            specialization=random.choice(["Разработка ПО", "Аналитика", "Логистика", "Финансы"]),
            order=0,
        )
        if index % 3 == 0:
            Education.objects.create(
                applicant=applicant,
                level="candidate",
                institution="НИУ ВШЭ",
                graduation_year=2020 + (index % 4),
                faculty="Исследовательский факультет",
                specialization="Data Science",
                order=1,
            )

        WorkExperience.objects.create(
            applicant=applicant,
            company=random.choice(["Яндекс", "Сбер", "Т-Банк", "Ozon", "VK"]),
            position=random.choice(["Инженер", "Аналитик", "Координатор проектов"]),
            start_month=1 + (index % 12),
            start_year=2016 + index % 5,
            end_month=6 + (index % 6),
            end_year=2021 + (index % 3),
            is_current=False,
            responsibilities="Работа с клиентскими задачами, автоматизация рутины, взаимодействие с командой.",
            order=0,
        )
        WorkExperience.objects.create(
            applicant=applicant,
            company=random.choice(["Wildberries", "Авито", "Ростелеком", "Контур"]),
            position=random.choice(["Senior Специалист", "Team Lead", "Продуктовый аналитик"]),
            start_month=2,
            start_year=2022,
            end_month=None,
            end_year=None,
            is_current=True,
            responsibilities="Веду ключевые процессы и помогаю развивать продукт.",
            order=1,
        )

        ExtraEducation.objects.create(
            applicant=applicant,
            name=random.choice(["Курс по Docker", "SQL Advanced", "Английский B2"]),
            description="Практический интенсив с проектной работой.",
            order=0,
        )

    def _create_hh_employers(self):
        employer_specs = [
            ("hh-demo-001", "ТехноСофт", "https://logo.clearbit.com/yandex.ru"),
            ("hh-demo-002", "ФинГрупп", "https://logo.clearbit.com/sber.ru"),
            ("hh-demo-003", "Логистик Про", "https://logo.clearbit.com/ozon.ru"),
        ]
        employers = []
        for hh_id, name, logo in employer_specs:
            employer, _ = Employer.objects.get_or_create(hh_id=hh_id, defaults={"name": name})
            employer.name = name
            employer.logo_url = logo
            employer.hh_rating = random.choice([3.9, 4.2, 4.5, 4.7])
            employer.dreamjob_rating = random.choice([3.8, 4.1, 4.3, 4.6])
            employer.raw = {"logo_urls": {"original": logo}}
            employer.save()
            employers.append(employer)
        return employers

    def _create_vacancies(self, managers, employers, now):
        vacancies = []

        # HH-like vacancies
        for i in range(1, 16):
            employer = employers[(i - 1) % len(employers)]
            external_id = f"demo_hh_{i:03d}"
            vacancy, _ = Vacancy.objects.get_or_create(
                external_id=external_id,
                defaults={"title": f"HH Вакансия {i}", "country": "Россия", "published_at": now},
            )
            vacancy.title = random.choice(
                [
                    "Backend Python Developer",
                    "Data Analyst",
                    "HR Manager",
                    "DevOps Engineer",
                    "Frontend Developer",
                ]
            )
            vacancy.company = employer.name
            vacancy.employer = employer
            vacancy.country = "Россия"
            vacancy.region = random.choice(["Москва", "Санкт-Петербург", "Казань", "Новосибирск"])
            vacancy.experience_id = random.choice(["noExperience", "between1And3", "between3And6"])
            vacancy.experience_name = random.choice(["Без опыта", "1-3 года", "3-6 лет"])
            vacancy.salary_from = random.choice([None, 80000, 120000, 180000])
            vacancy.salary_to = random.choice([None, 150000, 220000, 280000])
            vacancy.salary_currency = "RUR" if (vacancy.salary_from or vacancy.salary_to) else ""
            vacancy.work_format = random.choice([Vacancy.WorkFormat.REMOTE, Vacancy.WorkFormat.HYBRID, Vacancy.WorkFormat.ONSITE])
            vacancy.is_remote = vacancy.work_format == Vacancy.WorkFormat.REMOTE
            vacancy.is_hybrid = vacancy.work_format == Vacancy.WorkFormat.HYBRID
            vacancy.is_onsite = vacancy.work_format == Vacancy.WorkFormat.ONSITE
            vacancy.schedule_id = random.choice(["fullDay", "shift", "flexible", "remote"])
            vacancy.schedule_name = random.choice(["Полный день", "Сменный график", "Гибкий график"])
            vacancy.employment_id = random.choice(["full", "part", "project"])
            vacancy.employment_name = random.choice(["Полная занятость", "Частичная занятость", "Проектная работа"])
            vacancy.employment_form_id = random.choice(["office", "remote", "mixed"])
            vacancy.employment_form_name = random.choice(["Офис", "Удалённо", "Смешанный"])
            vacancy.is_internship = i % 5 == 0
            vacancy.accept_temporary = i % 4 == 0
            vacancy.accept_incomplete_resumes = i % 3 == 0
            vacancy.accept_kids = i % 7 == 0
            vacancy.url = f"https://hh.ru/vacancy/{900000 + i}"
            vacancy.published_at = now - timedelta(days=i)
            vacancy.raw_json = {"source": "hh", "employer": {"logo_urls": {"original": employer.logo_url}}}
            vacancy.description = "Подробное описание вакансии с обязанностями, требованиями и условиями."
            vacancy.branded_description = "<p>Брендированное описание компании и команды.</p>"
            vacancy.key_skills_text = "Python, SQL, Git, Командная работа"
            vacancy.created_by = None
            vacancy.is_active = True
            vacancy.save()
            vacancies.append(vacancy)

        # Site-created vacancies by managers
        for i in range(1, 13):
            manager_user = managers[(i - 1) % len(managers)]
            external_id = f"demo_site_{i:03d}"
            vacancy, _ = Vacancy.objects.get_or_create(
                external_id=external_id,
                defaults={"title": f"Site Vacancy {i}", "country": "Россия", "published_at": now},
            )
            vacancy.title = random.choice(
                [
                    "Менеджер по продажам",
                    "Python-разработчик",
                    "Оператор поддержки",
                    "Системный аналитик",
                    "Маркетолог",
                ]
            )
            vacancy.company = getattr(getattr(manager_user, "manager", None), "company", "") or manager_user.get_full_name()
            vacancy.country = "Россия"
            vacancy.region = random.choice(["Москва", "Самара", "Краснодар", "Пермь"])
            vacancy.experience_id = random.choice(["noExperience", "between1And3", "between3And6"])
            vacancy.experience_name = random.choice(["Без опыта", "1-3 года", "3-6 лет"])
            vacancy.salary_from = random.choice([50000, 70000, 95000, 130000])
            vacancy.salary_to = vacancy.salary_from + random.choice([30000, 50000, 80000])
            vacancy.salary_currency = "RUR"
            vacancy.work_format = random.choice([Vacancy.WorkFormat.ONSITE, Vacancy.WorkFormat.HYBRID, Vacancy.WorkFormat.REMOTE])
            vacancy.is_remote = vacancy.work_format == Vacancy.WorkFormat.REMOTE
            vacancy.is_hybrid = vacancy.work_format == Vacancy.WorkFormat.HYBRID
            vacancy.is_onsite = vacancy.work_format == Vacancy.WorkFormat.ONSITE
            vacancy.schedule_id = random.choice(["fullDay", "shift", "flexible"])
            vacancy.schedule_name = random.choice(["Полный день", "Сменный график", "Гибкий график"])
            vacancy.employment_id = random.choice(["full", "part", "project", "volunteer"])
            vacancy.employment_name = random.choice(["Полная занятость", "Частичная занятость", "Проектная работа"])
            vacancy.employment_form_id = random.choice(["office", "remote", "mixed"])
            vacancy.employment_form_name = random.choice(["Офис", "Удалённо", "Смешанный"])
            vacancy.is_internship = i % 6 == 0
            vacancy.accept_temporary = i % 3 == 0
            vacancy.accept_incomplete_resumes = i % 2 == 0
            vacancy.accept_kids = i % 5 == 0
            vacancy.url = ""
            vacancy.published_at = now - timedelta(days=(i + 2))
            vacancy.raw_json = {"source": "site"}
            vacancy.key_skills_text = random.choice(
                [
                    "Коммуникация, CRM, B2B",
                    "Python, Django, PostgreSQL",
                    "Поддержка клиентов, HelpDesk",
                    "SQL, BI, аналитика",
                ]
            )
            vacancy.description = "Требуется специалист в команду для развития направления."
            vacancy.branded_description = ""
            vacancy.created_by = manager_user
            vacancy.is_active = i % 8 != 0
            vacancy.employee_type = random.choice(["permanent", "temporary", ""])
            vacancy.contract_labor = i % 2 == 0
            vacancy.contract_gpc = i % 4 == 0
            vacancy.work_schedule = random.choice(["5/2", "2/2", "6/1", "Свободный"])
            vacancy.hours_per_day = random.choice(["4", "6", "8", "10"])
            vacancy.has_night_shifts = i % 5 == 0
            vacancy.salary_gross = i % 2 == 1
            vacancy.salary_period = random.choice(["month", "project"])
            vacancy.payment_frequency = random.choice(["weekly", "biweekly", "monthly"])
            vacancy.work_address = f"г. {vacancy.region}, ул. Рабочая, д. {10 + i}"
            vacancy.hide_address = i % 7 == 0
            vacancy.address_comment = random.choice(["Бизнес-центр", "Вход со двора", "Рядом с метро", ""])
            vacancy.lat = 55.75 + (i * 0.01)
            vacancy.lon = 37.61 + (i * 0.01)
            vacancy.contact_phone = f"+7 (901) 700-1{i:02d}"
            vacancy.metro_station_name = random.choice(["Курская", "Таганская", "Белорусская", "Площадь Ленина"])
            vacancy.metro_line_color = random.choice(["#d32f2f", "#1976d2", "#388e3c"])
            vacancy.metro_line_name = random.choice(["Красная", "Синяя", "Зелёная"])
            vacancy.metro_city_id = "1"
            vacancy.benefits_text = "ДМС, обучение, гибкий график, корпоративные мероприятия."
            vacancy.requirements_text = "Ответственность, коммуникабельность, опыт работы с релевантными инструментами."
            vacancy.working_conditions_text = "Современный офис, наставничество, понятные KPI."
            vacancy.save()
            vacancies.append(vacancy)

        return vacancies

    def _create_reviews(self, vacancies):
        texts = [
            "Отличный процесс собеседования, быстро дали обратную связь.",
            "Интересные задачи и адекватная команда.",
            "Прозрачные условия, понятные требования.",
            "Хорошая коммуникация с HR и руководителем.",
        ]
        for i, vacancy in enumerate(vacancies[:20], start=1):
            Review.objects.get_or_create(
                vacancy=vacancy,
                author=f"Гость{i}",
                text=texts[i % len(texts)],
            )

    def _create_applications(self, applicants, vacancies, now):
        site_vacancies = [v for v in vacancies if v.created_by_id and v.is_active]
        statuses = [Application.STATUS_PENDING, Application.STATUS_VIEWED, Application.STATUS_ACCEPTED, Application.STATUS_REJECTED]
        applications = []

        for idx, applicant_user in enumerate(applicants, start=1):
            chosen = random.sample(site_vacancies, k=min(4, len(site_vacancies)))
            for j, vacancy in enumerate(chosen, start=1):
                app, _ = Application.objects.get_or_create(
                    vacancy=vacancy,
                    applicant=applicant_user,
                    defaults={"cover_letter": "Готов быстро включиться в работу.", "status": statuses[(idx + j) % 4]},
                )
                app.cover_letter = random.choice(
                    [
                        "Хочу применить опыт в вашей команде.",
                        "Готов к тестовому заданию и интервью в удобное время.",
                        "Имею релевантный опыт и сильную мотивацию.",
                        "Ищу долгосрочный проект, где можно развиваться.",
                    ]
                )
                app.status = statuses[(idx + j) % 4]
                app.save(update_fields=["cover_letter", "status"])
                applications.append(app)
        return applications

    def _create_bookmarks_and_views(self, applicants, vacancies, now):
        active_vacancies = [v for v in vacancies if v.is_active]
        for i, user in enumerate(applicants, start=1):
            for vacancy in random.sample(active_vacancies, k=min(8, len(active_vacancies))):
                Bookmark.objects.get_or_create(user=user, vacancy=vacancy)
            for step, vacancy in enumerate(random.sample(active_vacancies, k=min(10, len(active_vacancies))), start=1):
                view, _ = VacancyView.objects.get_or_create(user=user, vacancy=vacancy)
                view.viewed_at = now - timedelta(days=step, hours=i)
                view.save(update_fields=["viewed_at"])

    def _create_chats_and_messages(self, applications, now):
        text_pairs = [
            ("Здравствуйте! Подскажите, пожалуйста, детали по вакансии.", "Добрый день! Конечно, давайте обсудим."),
            ("Когда удобно пройти интервью?", "Завтра в 14:00 или в пятницу в 11:00."),
            ("Есть ли удаленный формат?", "Да, гибридный формат возможен после испытательного срока."),
        ]

        for app in applications[:30]:
            if not app.vacancy.created_by_id:
                continue
            manager_user = app.vacancy.created_by
            applicant_user = app.applicant
            chat, _ = Chat.objects.get_or_create(manager=manager_user, applicant=applicant_user)
            for pidx, (q_text, a_text) in enumerate(text_pairs):
                q_msg, _ = Message.objects.get_or_create(
                    chat=chat,
                    sender=applicant_user,
                    text=q_text,
                )
                q_msg.created_at = now - timedelta(days=3 - pidx, hours=2)
                q_msg.is_read = True
                q_msg.save(update_fields=["created_at", "is_read"])

                a_msg, _ = Message.objects.get_or_create(
                    chat=chat,
                    sender=manager_user,
                    text=a_text,
                )
                a_msg.created_at = now - timedelta(days=3 - pidx, hours=1)
                a_msg.is_read = pidx % 2 == 0
                a_msg.save(update_fields=["created_at", "is_read"])

    def _create_interviews(self, applications, now):
        accepted_apps = [a for a in applications if a.status == Application.STATUS_ACCEPTED]
        for idx, app in enumerate(accepted_apps[:20], start=1):
            if not app.vacancy.created_by_id:
                continue
            status = random.choice([Interview.STATUS_SCHEDULED, Interview.STATUS_CANCELLED, Interview.STATUS_DONE])
            interview, _ = Interview.objects.get_or_create(
                manager=app.vacancy.created_by,
                applicant=app.applicant,
                vacancy=app.vacancy,
                scheduled_at=now + timedelta(days=(idx % 10) + 1, hours=idx % 5),
            )
            interview.location = random.choice(
                ["Google Meet", "Zoom", "Офис на Курской", "Telegram call", "MS Teams"]
            )
            interview.notes = "Подготовить кейс и обсудить предыдущий опыт."
            interview.status = status
            interview.reminded_1d = status != Interview.STATUS_SCHEDULED
            interview.reminded_1h = status == Interview.STATUS_DONE
            interview.reminded_now = status == Interview.STATUS_DONE
            interview.save()

    def _create_calendar_notes(self, users, now):
        colors = ["#c2a35a", "#f59e0b", "#22c55e", "#3b82f6", "#a855f7", "#ef4444"]
        note_titles = [
            "Созвон с HR",
            "Тестовое задание",
            "Фоллоу-ап по отклику",
            "Собеседование",
            "Дедлайн портфолио",
            "Обновить резюме",
        ]
        for idx, user in enumerate(users, start=1):
            for d in range(-8, 12, 4):
                note_date = timezone.localdate() + timedelta(days=d + (idx % 3))
                title = note_titles[(idx + d) % len(note_titles)]
                note_text = f"{title}: подготовить материалы и отметить результат."
                note_time = None if (idx + d) % 3 == 0 else timezone.datetime(2026, 1, 1, (9 + idx) % 24, (10 * idx) % 60).time()
                CalendarNote.objects.get_or_create(
                    user=user,
                    date=note_date,
                    title=title,
                    text=note_text,
                    defaults={
                        "color": colors[(idx + d) % len(colors)],
                        "note_time": note_time,
                        "reminded": (idx + d) % 4 == 0,
                    },
                )

    def _create_filter_presets(self, applicants):
        for idx, user in enumerate(applicants, start=1):
            FilterPreset.objects.update_or_create(
                user=user,
                name="Удаленка + высокий доход",
                defaults={
                    "filters": {
                        "q": "python",
                        "region": random.choice(["Москва", "Санкт-Петербург", "Казань"]),
                        "salary_from": 120000 + idx * 5000,
                        "remote_only": True,
                        "experience": ["between1And3", "between3And6"],
                    }
                },
            )
            FilterPreset.objects.update_or_create(
                user=user,
                name="Стажировка / старт карьеры",
                defaults={
                    "filters": {
                        "q": "",
                        "is_internship": True,
                        "accept_incomplete_resumes": True,
                        "employment": ["part", "project"],
                        "schedule": ["flexible"],
                    }
                },
            )

    def _create_ui_preferences(self, users):
        for idx, user in enumerate(users, start=1):
            UserUiPreference.objects.update_or_create(
                user=user,
                defaults={"theme": "dark" if idx % 2 == 0 else "light"},
            )

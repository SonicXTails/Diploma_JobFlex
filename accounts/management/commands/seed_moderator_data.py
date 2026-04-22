"""Management command: populate demo data for the moderator role.

Run after seed_demo_data has already been executed:
    python manage.py seed_moderator_data
    python manage.py seed_moderator_data --password MyPass1!

Creates:
  • 3 demo moderator accounts (demo_moderator_1..3)
  • VacancyReport rows (user complaints) on site-created vacancies
  • VacancyModerationState entries so moderators have a realistic complaint feed
  • 2 ModeratorDeletionReport rows (one active, one already restored)
    with placeholder images so the admin reports page has content

All objects use get_or_create, so re-running is safe.
"""

import io
import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import CalendarNote, Moderator
from vacancies.models import (
    ModeratorDeletionPhoto,
    ModeratorDeletionReport,
    Vacancy,
    VacancyModerationState,
    VacancyReport,
)


def _tiny_png() -> bytes:
    """Return a minimal valid 2×2 red PNG (no Pillow dependency)."""
    import base64
    # pre-encoded 2x2 solid-red PNG
    b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAADklEQVQI12P4z8BQ"
        "DwADhQGAWjR9awAAAABJRU5ErkJggg=="
    )
    return base64.b64decode(b64)


class Command(BaseCommand):
    help = "Seed demo data for the Moderator role (complaints, states, deletion reports)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default="DemoPass123!",
            help="Password for demo moderator accounts (default: DemoPass123!)",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(7)
        password = options["password"]
        now = timezone.now()

        moderators = self._create_moderators(password=password)
        applicants = self._get_demo_applicants()
        site_vacancies = self._get_site_vacancies()

        if not site_vacancies:
            self.stdout.write(
                self.style.WARNING(
                    "No site-created vacancies found. Run seed_demo_data first."
                )
            )
            return

        if not applicants:
            self.stdout.write(
                self.style.WARNING(
                    "No demo applicants found. Run seed_demo_data first."
                )
            )
            return

        reports = self._create_vacancy_reports(applicants=applicants, site_vacancies=site_vacancies, now=now)
        self._create_moderation_states(moderators=moderators, site_vacancies=site_vacancies, now=now)
        self._create_deletion_reports(moderators=moderators, site_vacancies=site_vacancies, now=now)
        self._create_calendar_notes(moderators=moderators, now=now)

        self.stdout.write(self.style.SUCCESS("Moderator demo data seeded successfully."))
        self.stdout.write(self.style.WARNING(
            "Moderator accounts: demo_moderator_1, demo_moderator_2, demo_moderator_3"
        ))
        self.stdout.write(self.style.WARNING(f"Password: {password}"))
        self.stdout.write(self.style.WARNING(
            f"Created {len(reports)} user complaint(s) on site vacancies."
        ))

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _create_user(self, username, password, first_name, last_name, email):
        user, _ = User.objects.get_or_create(username=username)
        user.first_name = first_name
        user.last_name = last_name
        user.email = email
        user.is_active = True
        user.set_password(password)
        user.save()
        return user

    # ------------------------------------------------------------------ #
    #  Moderators                                                          #
    # ------------------------------------------------------------------ #

    def _create_moderators(self, password):
        specs = [
            ("demo_moderator_1", "Анастасия", "Фёдорова", "mod1@demo.local"),
            ("demo_moderator_2", "Виктор",    "Зайцев",   "mod2@demo.local"),
            ("demo_moderator_3", "Полина",    "Власова",  "mod3@demo.local"),
        ]
        moderators = []
        for username, first, last, email in specs:
            user = self._create_user(username, password, first, last, email)
            mod, _ = Moderator.objects.get_or_create(user=user)
            mod.patronymic = random.choice(["Александровна", "Владимировна", "Сергеевна",
                                             "Иванович", "Петрович", ""])
            mod.phone = f"+7 (915) {random.randint(100, 999)}-{random.randint(10,99)}-{random.randint(10,99)}"
            mod.notes = "Демо-модератор для тестирования интерфейса."
            mod.save()
            moderators.append(user)
        return moderators

    # ------------------------------------------------------------------ #
    #  Existing demo data lookups                                          #
    # ------------------------------------------------------------------ #

    def _get_demo_applicants(self):
        return list(
            User.objects.filter(username__startswith="demo_applicant_")
                        .order_by("username")
        )

    def _get_site_vacancies(self):
        """Return site-created (non-HH) active vacancies, excluding already-deleted ones."""
        return list(
            Vacancy.objects.filter(
                external_id__startswith="demo_site_",
                is_moderator_deleted=False,
            ).order_by("external_id")
        )

    # ------------------------------------------------------------------ #
    #  Vacancy reports (user complaints)                                   #
    # ------------------------------------------------------------------ #

    REASONS = [
        (VacancyReport.REASON_SCAM,        "Просят переводить деньги или купить что-то до работы."),
        (VacancyReport.REASON_SPAM,        "Вакансия — скрытая реклама курсов."),
        (VacancyReport.REASON_MISLEADING,  "Реальные условия отличаются от описания."),
        (VacancyReport.REASON_SUSPICIOUS,  "Работодатель не отвечает на вопросы, требует NDA сразу."),
        (VacancyReport.REASON_OTHER,       "Вакансия выглядит подозрительно."),
    ]

    def _create_vacancy_reports(self, applicants, site_vacancies, now):
        created = []
        # Pick at most 8 vacancies to receive complaints
        target_vacancies = site_vacancies[:8]
        reason_pool = self.REASONS

        for vac_idx, vacancy in enumerate(target_vacancies):
            # Each vacancy gets 2-5 reporters (different applicants)
            num_reporters = min(2 + (vac_idx % 4), len(applicants))
            reporters = random.sample(applicants, k=num_reporters)
            for user_idx, user in enumerate(reporters):
                reason_code, reason_text = reason_pool[(vac_idx + user_idx) % len(reason_pool)]
                self_status = random.choice([
                    VacancyReport.SELF_STATUS_NEW,
                    VacancyReport.SELF_STATUS_IN_WORK,
                    VacancyReport.SELF_STATUS_NEW,   # weight NEW higher
                ])
                report, created_now = VacancyReport.objects.get_or_create(
                    vacancy=vacancy,
                    user=user,
                    defaults={
                        "reason_code": reason_code,
                        "reason_text": reason_text,
                        "self_status": self_status,
                    },
                )
                if not created_now:
                    # Update existing to keep data fresh
                    report.reason_code = reason_code
                    report.reason_text = reason_text
                    report.self_status = self_status
                    report.save(update_fields=["reason_code", "reason_text", "self_status"])
                created.append(report)
        return created

    # ------------------------------------------------------------------ #
    #  Moderation states (per moderator, per vacancy card)                 #
    # ------------------------------------------------------------------ #

    def _create_moderation_states(self, moderators, site_vacancies, now):
        statuses = [
            VacancyModerationState.STATUS_NEW,
            VacancyModerationState.STATUS_IN_WORK,
            VacancyModerationState.STATUS_WAITING,
        ]
        notes = [
            "Проверить историю менеджера — были жалобы ранее.",
            "Запросить дополнительные документы у работодателя.",
            "Похоже на паттерн мошенничества, нужна второе мнение.",
            "Ожидаю ответа от менеджера по почте.",
            "Вакансия выглядит нормально, оставил под наблюдением.",
            "",
        ]
        # Give each moderator states for the first 6 reported vacancies
        target = site_vacancies[:6]
        for mod_idx, mod_user in enumerate(moderators):
            for vac_idx, vacancy in enumerate(target):
                status = statuses[(mod_idx + vac_idx) % len(statuses)]
                note = notes[(mod_idx * 2 + vac_idx) % len(notes)]
                VacancyModerationState.objects.update_or_create(
                    vacancy=vacancy,
                    moderator=mod_user,
                    defaults={"status": status, "note": note},
                )

    # ------------------------------------------------------------------ #
    #  Deletion reports                                                    #
    # ------------------------------------------------------------------ #

    def _create_deletion_reports(self, moderators, site_vacancies, now):
        if len(site_vacancies) < 3 or not moderators:
            return

        png = _tiny_png()

        # --- Report 1: active (not restored) ---
        vac1 = site_vacancies[-1]     # last site vacancy → soft-deleted
        mod_user = moderators[0]
        manager_user = vac1.created_by

        # soft-delete the vacancy if not already deleted
        if not vac1.is_moderator_deleted:
            vac1.is_moderator_deleted = True
            vac1.is_active = False
            vac1.save(update_fields=["is_moderator_deleted", "is_active"])

        rep1, _ = ModeratorDeletionReport.objects.get_or_create(
            vacancy=vac1,
            moderator=mod_user,
            defaults={
                "manager": manager_user,
                "reason": (
                    "Вакансия содержит признаки мошенничества: от соискателя требуют "
                    "приобрести оборудование за собственный счёт, возврат якобы гарантирован "
                    "после испытательного срока. Несколько пользователей подтвердили схему."
                ),
                "vacancy_title": vac1.title,
                "vacancy_company": vac1.company,
                "vacancy_description": vac1.description[:500] if vac1.description else "",
                "vacancy_external_id": vac1.external_id or "",
                "manager_full_name": manager_user.get_full_name() if manager_user else "",
                "manager_email": manager_user.email if manager_user else "",
                "moderator_full_name": mod_user.get_full_name(),
                "moderator_email": mod_user.email,
                "reports_count": VacancyReport.objects.filter(vacancy=vac1).count(),
                "dominant_reason_code": VacancyReport.REASON_SCAM,
                "dominant_reason_label": "Подозрение на мошенничество",
                "is_restored": False,
            },
        )
        # Attach a demo photo if none yet
        if not rep1.photos.exists():
            ModeratorDeletionPhoto.objects.create(
                report=rep1,
                image=ContentFile(png, name="screenshot_evidence.png"),
                order=0,
            )

        # --- Report 2: restored by admin ---
        vac2 = site_vacancies[-2]
        mod_user2 = moderators[1] if len(moderators) > 1 else moderators[0]
        manager_user2 = vac2.created_by

        admin_user = User.objects.filter(is_superuser=True).first()

        rep2, _ = ModeratorDeletionReport.objects.get_or_create(
            vacancy=vac2,
            moderator=mod_user2,
            defaults={
                "manager": manager_user2,
                "reason": (
                    "Описание вводило в заблуждение: указана полная занятость, "
                    "по факту предлагается работа по ГПХ без социальных гарантий. "
                    "Менеджер согласился скорректировать объявление."
                ),
                "vacancy_title": vac2.title,
                "vacancy_company": vac2.company,
                "vacancy_description": vac2.description[:500] if vac2.description else "",
                "vacancy_external_id": vac2.external_id or "",
                "manager_full_name": manager_user2.get_full_name() if manager_user2 else "",
                "manager_email": manager_user2.email if manager_user2 else "",
                "moderator_full_name": mod_user2.get_full_name(),
                "moderator_email": mod_user2.email,
                "reports_count": VacancyReport.objects.filter(vacancy=vac2).count(),
                "dominant_reason_code": VacancyReport.REASON_MISLEADING,
                "dominant_reason_label": "Некорректное описание вакансии",
                "is_restored": True,
                "restored_by": admin_user,
                "restored_at": now - timedelta(days=1),
            },
        )
        # Ensure vacancy itself is visible again (restored)
        if vac2.is_moderator_deleted:
            vac2.is_moderator_deleted = False
            vac2.is_active = True
            vac2.save(update_fields=["is_moderator_deleted", "is_active"])

        if not rep2.photos.exists():
            ModeratorDeletionPhoto.objects.create(
                report=rep2,
                image=ContentFile(png, name="evidence_before.png"),
                order=0,
            )
            ModeratorDeletionPhoto.objects.create(
                report=rep2,
                image=ContentFile(png, name="evidence_after.png"),
                order=1,
            )

    # ------------------------------------------------------------------ #
    #  Calendar notes for moderators                                       #
    # ------------------------------------------------------------------ #

    def _create_calendar_notes(self, moderators, now):
        colors = ["#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#ef4444"]
        titles = [
            "Разобрать новые жалобы",
            "Созвон с командой модерации",
            "Проверить статус вакансий «В работе»",
            "Написать отчёт за неделю",
            "Обновить критерии модерации",
            "Плановая проверка старых жалоб",
        ]
        for idx, user in enumerate(moderators, start=1):
            for d in range(-4, 10, 3):
                note_date = timezone.localdate() + timedelta(days=d + idx)
                title = titles[(idx + d) % len(titles)]
                CalendarNote.objects.get_or_create(
                    user=user,
                    date=note_date,
                    title=title,
                    defaults={
                        "text": f"{title}: проверить очередь и зафиксировать результат.",
                        "color": colors[(idx + d) % len(colors)],
                        "note_time": None if (idx + d) % 3 == 0 else
                                     timezone.datetime(2026, 1, 1, (9 + idx) % 24, 0).time(),
                        "reminded": False,
                    },
                )

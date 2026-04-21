"""Celery tasks for the accounts app (interview reminders, etc.)."""
import logging
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _interview_reminder_text(interview, reminder_type, recipient_user):
    """Return the notification message body for an interview reminder."""
    scheduled = timezone.localtime(interview.scheduled_at)
    date_str = scheduled.strftime('%d.%m.%Y')
    time_str = scheduled.strftime('%H:%M')
    vacancy_title = interview.vacancy.title if interview.vacancy else '—'
    location = interview.location or 'не указано'

    when_label = {
        '1d':  'Завтра',
        '1h':  'Через 1 час',
        'now': 'Через 5 минут',
    }.get(reminder_type, '')

    # Indicate the other party depending on who receives the reminder
    if recipient_user.pk == interview.manager_id:
        other_name = interview.applicant.get_full_name() or interview.applicant.username
        role_line = f'Соискатель: {other_name}\n'
    else:
        role_line = ''

    return (
        f"📅 Напоминание о собеседовании\n\n"
        f"{when_label}: {date_str} в {time_str}\n"
        f"Вакансия: {vacancy_title}\n"
        f"{role_line}"
        f"Место/ссылка: {location}"
    )


def _send_interview_reminder(user, interview, reminder_type):
    """Send Telegram and/or email reminder to *user* about *interview*."""
    from django.core.mail import send_mail

    # Resolve consent flags + contact info from the correct role profile.
    # Use the interview relationship (manager / applicant) to determine which
    # profile to read — this avoids reading the wrong profile when a user has
    # both an Applicant and a Manager record (e.g. after a role switch).
    consent_email    = False
    consent_telegram = False
    tg_chat_id       = None
    email            = user.email

    if user.pk == interview.manager_id:
        # This user is the manager for this interview
        try:
            profile = user.manager
            consent_email    = profile.consent_email
            consent_telegram = profile.consent_telegram
            tg_chat_id       = profile.telegram_chat_id
        except Exception:
            pass
    else:
        # This user is the applicant for this interview
        try:
            profile = user.applicant
            consent_email    = profile.consent_email
            consent_telegram = profile.consent_telegram
            tg_chat_id       = profile.telegram_chat_id
        except Exception:
            pass

    text = _interview_reminder_text(interview, reminder_type, user)

    # ── Telegram ──────────────────────────────────────────────
    if consent_telegram and tg_chat_id:
        try:
            from accounts.telegram import send_hello
            send_hello(tg_chat_id, text=text)
        except Exception as exc:
            logger.warning('interview_reminder: telegram failed for user %s: %s', user.pk, exc)

    # ── Email ──────────────────────────────────────────────────
    if consent_email and email:
        when_label = {
            '1d':  'завтра',
            '1h':  'через 1 час',
            'now': 'сейчас',
        }.get(reminder_type, '')
        subject = f"Напоминание: собеседование {when_label} — JobFlex"
        from_email = (
            getattr(settings, 'EMAIL_HOST_USER', None)
            or getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@jobflex.ru')
        )
        try:
            send_mail(
                subject,
                text + '\n\n— JobFlex',
                from_email,
                [email],
                fail_silently=False,
            )
        except Exception as exc:
            logger.warning('interview_reminder: email failed for user %s: %s', user.pk, exc)


# ─── Periodic task ────────────────────────────────────────────────────────────

@shared_task(name='accounts.tasks.notify_interview_reminders_task')
def notify_interview_reminders_task():
    """Check all scheduled interviews and send reminders at 1 day, 1 hour, and 5 min before.

    Runs every 60 seconds via Celery Beat.  Each reminder is sent at most once
    (guarded by the reminded_1d / reminded_1h / reminded_now flags).
    """
    from accounts.models import Interview

    now = timezone.now()
    qs = (
        Interview.objects
        .filter(status='scheduled')
        .select_related(
            'manager', 'manager__applicant', 'manager__manager',
            'applicant', 'applicant__applicant', 'applicant__manager',
            'vacancy',
        )
    )

    sent_1d = sent_1h = sent_now = 0

    for iv in qs:
        secs = (iv.scheduled_at - now).total_seconds()

        # ── 1-day window: 23h50m – 24h10m (85800–87000 s) ──────
        if 85800 <= secs <= 87000 and not iv.reminded_1d:
            _send_interview_reminder(iv.manager,   iv, '1d')
            _send_interview_reminder(iv.applicant, iv, '1d')
            Interview.objects.filter(pk=iv.pk).update(reminded_1d=True)
            sent_1d += 1

        # ── 1-hour window: 50min – 70min (3000–4200 s) ──────────
        elif 3000 <= secs <= 4200 and not iv.reminded_1h:
            _send_interview_reminder(iv.manager,   iv, '1h')
            _send_interview_reminder(iv.applicant, iv, '1h')
            Interview.objects.filter(pk=iv.pk).update(reminded_1h=True)
            sent_1h += 1

        # ── 5-min window: 0 – 10min (0 – 600 s) — runs every 60s so cannot be missed ────
        elif 0 <= secs <= 600 and not iv.reminded_now:
            _send_interview_reminder(iv.manager,   iv, 'now')
            _send_interview_reminder(iv.applicant, iv, 'now')
            Interview.objects.filter(pk=iv.pk).update(reminded_now=True)
            sent_now += 1

    logger.info(
        'notify_interview_reminders: sent 1d=%d, 1h=%d, now=%d',
        sent_1d, sent_1h, sent_now,
    )
    return {'sent_1d': sent_1d, 'sent_1h': sent_1h, 'sent_now': sent_now}


@shared_task(name='accounts.tasks.send_interview_notification_task')
def send_interview_notification_task(interview_id, reminder_type):
    """Send Telegram + email notifications to manager and applicant at exact scheduled time.

    Scheduled via apply_async(eta=...) when an interview is created.
    Also updates the reminded_* flag so the periodic task does not double-send.
    """
    from accounts.models import Interview

    try:
        iv = Interview.objects.select_related('manager', 'applicant', 'vacancy').get(pk=interview_id)
    except Interview.DoesNotExist:
        return  # interview was deleted

    if iv.status != Interview.STATUS_SCHEDULED:
        return  # interview was cancelled, nothing to send

    # Guard against double-send from the periodic polling task
    flag_field = {'1d': 'reminded_1d', '1h': 'reminded_1h', 'now': 'reminded_now'}.get(reminder_type)
    if flag_field:
        if getattr(iv, flag_field):
            return  # already sent by periodic task
        Interview.objects.filter(pk=iv.pk).update(**{flag_field: True})

    _send_interview_reminder(iv.manager,   iv, reminder_type)
    _send_interview_reminder(iv.applicant, iv, reminder_type)
    logger.info('send_interview_notification_task: sent %s for interview %d', reminder_type, interview_id)


# ─── Calendar-note reminders ──────────────────────────────────────────────────

@shared_task(name='accounts.tasks.notify_calendar_note_reminders_task')
def notify_calendar_note_reminders_task():
    """Send email/Telegram reminders for calendar notes whose time is now.

    Runs every 60 seconds via Celery Beat.  Each note is reminded at most once
    (guarded by the CalendarNote.reminded flag).
    """
    from django.core.mail import send_mail
    from accounts.models import CalendarNote
    import datetime

    now_local = timezone.localtime(timezone.now())
    today = now_local.date()

    # Tight reminder window: from 60 seconds ago up to now.
    # This keeps delivery close to the exact note_time while tolerating minor
    # task scheduling jitter.
    now_dt = datetime.datetime.combine(today, now_local.time())
    window_start_dt = now_dt - datetime.timedelta(seconds=60)
    window_start = window_start_dt.time()
    window_end = now_dt.time()

    qs = (
        CalendarNote.objects
        .filter(
            date=today,
            reminded=False,
            note_time__isnull=False,
            note_time__gte=window_start,
            note_time__lte=window_end,
        )
        .select_related('user', 'user__applicant', 'user__manager')
    )

    sent = 0
    for note in qs:
        user = note.user

        # Resolve consent flags. Prefer manager profile when present because
        # manager users can also have an Applicant profile record.
        consent_email    = False
        consent_telegram = False
        tg_chat_id       = None

        try:
            prof = user.manager
            consent_email    = prof.consent_email
            consent_telegram = prof.consent_telegram
            tg_chat_id       = prof.telegram_chat_id
        except Exception:
            pass

        if not consent_email and not consent_telegram:
            try:
                prof = user.applicant
                consent_email    = prof.consent_email
                consent_telegram = prof.consent_telegram
                tg_chat_id       = prof.telegram_chat_id
            except Exception:
                pass

        text = (
            f"📝 Напоминание о заметке\n\n"
            f"Сегодня в {note.note_time.strftime('%H:%M')}\n"
            f"{note.text}"
        )

        # Telegram
        if consent_telegram and tg_chat_id:
            try:
                from accounts.telegram import send_hello
                send_hello(tg_chat_id, text=text)
            except Exception as exc:
                logger.warning('note_reminder: telegram failed for user %s: %s', user.pk, exc)

        # Email
        if consent_email and user.email:
            from_email = (
                getattr(settings, 'EMAIL_HOST_USER', None)
                or getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@jobflex.ru')
            )
            try:
                send_mail(
                    f"Напоминание: заметка в {note.note_time.strftime('%H:%M')} — JobFlex",
                    text + '\n\n— JobFlex',
                    from_email,
                    [user.email],
                    fail_silently=False,
                )
            except Exception as exc:
                logger.warning('note_reminder: email failed for user %s: %s', user.pk, exc)

        CalendarNote.objects.filter(pk=note.pk).update(reminded=True)
        sent += 1

    logger.info('notify_calendar_note_reminders: sent=%d', sent)
    return {'sent': sent}

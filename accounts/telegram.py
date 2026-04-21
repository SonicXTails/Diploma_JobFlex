from django.conf import settings
import threading
import json

try:
    import requests
except Exception:
    requests = None
    import urllib.request
    import urllib.parse


def _send_via_requests(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={'chat_id': chat_id, 'text': text})
    return resp.status_code, resp.text


def _send_via_urllib(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({'chat_id': chat_id, 'text': text}).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.getcode(), r.read().decode('utf-8')


def send_hello(telegram_handle, text=None):
    """Send a welcome message to `telegram_handle` (e.g. '@username' or chat id).

    This is best-effort: Telegram bots can only message users who already started
    a conversation with the bot. Failures are logged but do not raise.
    """
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    if not token:
        return False

    if not text:
        text = 'Привет! Спасибо за регистрацию. Это приветственное сообщение от JobFlex.'

    try:
        if requests:
            status, body = _send_via_requests(token, telegram_handle, text)
        else:
            status, body = _send_via_urllib(token, telegram_handle, text)
        # Basic success check
        if 200 <= int(status) < 300:
            return True
    except Exception as e:
        body = str(e)

    # log to console for now
    try:
        print('telegram_send_failed', {'to': telegram_handle, 'resp': body})
    except Exception:
        pass
    return False


def send_hello_async(telegram_handle, text=None):
    t = threading.Thread(target=send_hello, args=(telegram_handle, text), daemon=True)
    t.start()
    return True


# Cache for bot info
# None = not yet fetched; False = fetched but failed; str = username
_BOT_USERNAME = None


def get_bot_username():
    """Return bot username (without @), querying Telegram `getMe` API once and caching result.

    Returns None on failure. Failures are cached to avoid blocking every request.
    """
    global _BOT_USERNAME
    if _BOT_USERNAME is not None:  # False (failed) or str (success) — don't retry
        return _BOT_USERNAME or None

    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    if not token:
        _BOT_USERNAME = False
        return None

    try:
        if requests:
            url = f"https://api.telegram.org/bot{token}/getMe"
            r = requests.get(url, timeout=3)
            j = r.json()
            if j.get('ok') and isinstance(j.get('result'), dict):
                username = j['result'].get('username')
                if username:
                    _BOT_USERNAME = username
                    return username
        else:
            url = f"https://api.telegram.org/bot{token}/getMe"
            with urllib.request.urlopen(url, timeout=3) as r:
                b = r.read().decode('utf-8')
                j = json.loads(b)
                if j.get('ok') and isinstance(j.get('result'), dict):
                    username = j['result'].get('username')
                    if username:
                        _BOT_USERNAME = username
                        return username
    except Exception:
        pass

    _BOT_USERNAME = False  # cache failure — don't retry on next request
    return None


def resolve_chat_id_by_token(start_token, limit=100):
    """Scan recent Telegram updates looking for a /start message containing start_token.

    Returns the chat_id integer if found, otherwise None.
    """
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    if not token or not start_token:
        return None

    try:
        params = {'limit': limit, 'timeout': 0, 'allowed_updates': ['message']}
        if requests:
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            r = requests.get(url, params=params, timeout=10)
            updates = r.json().get('result', [])
        else:
            import urllib.parse as _up
            qs = _up.urlencode(params)
            url = f"https://api.telegram.org/bot{token}/getUpdates?{qs}"
            with urllib.request.urlopen(url, timeout=10) as r:
                updates = json.loads(r.read().decode('utf-8')).get('result', [])

        for upd in reversed(updates):
            msg = upd.get('message') or {}
            text = (msg.get('text') or '').strip()
            chat_id = (msg.get('chat') or {}).get('id')
            if chat_id and text.startswith('/start'):
                parts = text.split(None, 1)
                if len(parts) > 1 and parts[1].strip() == start_token:
                    return chat_id
    except Exception:
        pass
    return None


def get_bot_link(start_token=None):
    username = get_bot_username()
    if not username:
        return None
    url = f"https://t.me/{username}"
    if start_token:
        url += f"?start={start_token}"
    return url


# ── Chat message notifications ──────────────────────────────────────────────

def _notify_task(recipient_user, sender_name, text_preview, chat_pk):
    """Run in a background thread: send email and/or Telegram notification."""
    from django.conf import settings as _s
    from django.core.mail import send_mail as _send_mail

    site_url = getattr(_s, 'SITE_URL', 'http://localhost:8000').rstrip('/')
    chat_url = f"{site_url}/accounts/chats/{chat_pk}/"

    # Resolve the recipient's consent profile (Applicant or Manager)
    consent_email    = False
    consent_telegram = False
    tg_chat_id       = None
    email            = recipient_user.email

    try:
        profile = recipient_user.applicant
        consent_email    = profile.consent_email
        consent_telegram = profile.consent_telegram
        tg_chat_id       = profile.telegram_chat_id
    except Exception:
        pass

    if not consent_email and not consent_telegram:
        try:
            profile = recipient_user.manager
            consent_email    = profile.consent_email
            consent_telegram = profile.consent_telegram
            tg_chat_id       = profile.telegram_chat_id
        except Exception:
            pass

    preview = text_preview[:120] + ('…' if len(text_preview) > 120 else '')

    # ── Telegram ────────────────────────────────────────────────────────────
    if consent_telegram and tg_chat_id:
        tg_text = (
            f"💬 Новое сообщение от {sender_name}:\n\n"
            f"«{preview}»\n\n"
            f"Открыть чат: {chat_url}"
        )
        try:
            send_hello(tg_chat_id, text=tg_text)
        except Exception:
            pass

    # ── Email ────────────────────────────────────────────────────────────────
    if consent_email and email:
        subject = f"Новое сообщение от {sender_name} — JobFlex"
        body = (
            f"Здравствуйте, {recipient_user.get_full_name() or recipient_user.username}!\n\n"
            f"{sender_name} написал(а) вам в чате:\n\n"
            f"«{preview}»\n\n"
            f"Перейти в чат: {chat_url}\n\n"
            f"— JobFlex"
        )
        # Mail.ru (and most SMTP servers) require From == authenticated user
        from_email = getattr(_s, 'EMAIL_HOST_USER', None) or getattr(_s, 'DEFAULT_FROM_EMAIL', 'noreply@jobflex.ru')
        try:
            _send_mail(
                subject,
                body,
                from_email,
                [email],
                fail_silently=False,
            )
        except Exception as exc:
            print(f'[chat_notify] email failed to {email}: {exc}')


def notify_new_chat_message(recipient_user, sender_name, text_preview, chat_pk):
    """Fire-and-forget: notify recipient about a new chat message (email + Telegram)."""
    t = threading.Thread(
        target=_notify_task,
        args=(recipient_user, sender_name, text_preview, chat_pk),
        daemon=True,
    )
    t.start()
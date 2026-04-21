from django.core.management.base import BaseCommand
from django.conf import settings
import time

try:
    import requests
except Exception:
    requests = None

from accounts.models import Applicant, Manager
from accounts.telegram import send_hello_async


class Command(BaseCommand):
    help = 'Poll Telegram getUpdates and map /start tokens or usernames to applicant.chat_id'

    def _process_start(self, chat_id, token_arg, username):
        if token_arg:
            try:
                applicant = Applicant.objects.get(telegram_start_token=token_arg)
                applicant.telegram_chat_id = chat_id
                applicant.save(update_fields=['telegram_chat_id'])
                self.stdout.write(f'Mapped token {token_arg} -> chat_id {chat_id}')
                if applicant.consent_telegram:
                    send_hello_async(chat_id)
                return True
            except Applicant.DoesNotExist:
                pass
        if username:
            applicant = Applicant.objects.filter(telegram__iexact='@' + username).first()
            if applicant:
                applicant.telegram_chat_id = chat_id
                applicant.save(update_fields=['telegram_chat_id'])
                self.stdout.write(f'Mapped username @{username} -> chat_id {chat_id}')
                if applicant.consent_telegram:
                    send_hello_async(chat_id)
                return True

            manager = Manager.objects.filter(telegram__iexact='@' + username).first()
            if manager:
                manager.telegram_chat_id = chat_id
                manager.save(update_fields=['telegram_chat_id'])
                self.stdout.write(f'Mapped manager @{username} -> chat_id {chat_id}')
                if manager.consent_telegram:
                    send_hello_async(chat_id, text='Телеграм подключён! Теперь вы будете получать уведомления от JobFlex.')
                return True
        return False

    def handle(self, *args, **options):
        token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
        if not token:
            self.stderr.write('TELEGRAM_BOT_TOKEN is not set in settings')
            return
        if not requests:
            self.stderr.write('requests library is required. Install with pip install requests')
            return

        offset = None
        self.stdout.write('Starting Telegram polling (press Ctrl+C to stop)')
        try:
            while True:
                params = {'timeout': 30}
                if offset:
                    params['offset'] = offset
                url = f'https://api.telegram.org/bot{token}/getUpdates'
                try:
                    r = requests.get(url, params=params, timeout=40)
                    j = r.json()
                except Exception as e:
                    self.stderr.write(f'Error fetching updates: {e}')
                    time.sleep(5)
                    continue

                for upd in j.get('result', []):
                    update_id = upd.get('update_id')
                    offset = update_id + 1
                    msg = upd.get('message') or {}
                    text = msg.get('text', '')
                    chat = msg.get('chat') or {}
                    chat_id = chat.get('id')
                    username = chat.get('username')

                    if not text or not chat_id:
                        continue

                    if text.startswith('/start'):
                        parts = text.split(None, 1)
                        token_arg = parts[1].strip() if len(parts) > 1 else None
                        self._process_start(chat_id, token_arg, username)

                time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write('Polling stopped')

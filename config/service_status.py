from __future__ import annotations

import time
from pathlib import Path

from django.conf import settings


HEARTBEAT_FILE_NAME = 'celery_worker_heartbeat.touch'
DEFAULT_HEARTBEAT_TTL = 90


def get_heartbeat_path() -> Path:
    base_dir = Path(getattr(settings, 'BASE_DIR', Path.cwd()))
    return base_dir / 'logs' / HEARTBEAT_FILE_NAME


def mark_celery_alive() -> None:
    heartbeat_path = get_heartbeat_path()
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.touch()


def mark_celery_stopped() -> None:
    heartbeat_path = get_heartbeat_path()
    try:
        heartbeat_path.unlink()
    except FileNotFoundError:
        pass


def is_celery_online() -> bool:
    heartbeat_path = get_heartbeat_path()
    if not heartbeat_path.exists():
        return False
    ttl = int(getattr(settings, 'CELERY_STATUS_TTL_SECONDS', DEFAULT_HEARTBEAT_TTL))
    age_seconds = time.time() - heartbeat_path.stat().st_mtime
    return age_seconds <= ttl


def service_status_context(request):
    online = is_celery_online()
    return {
        'service_center_online': online,
        'service_center_status_text': 'online' if online else 'offline',
    }

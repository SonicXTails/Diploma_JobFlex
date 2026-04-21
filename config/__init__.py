try:
	from .celery import app as celery_app
	__all__ = ('celery_app',)
except Exception:
	# Celery is optional for local development. If it's not installed or
	# misconfigured, avoid raising on import so Django commands like
	# `runserver` still work. Install celery in the venv to enable tasks.
	celery_app = None
	__all__ = ('celery_app',)


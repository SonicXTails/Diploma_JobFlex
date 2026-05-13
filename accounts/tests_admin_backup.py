"""Admin database backup API and Celery backup task."""

import json
import tempfile
import time
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Administrator
from vacancies.tasks import backup_database_task


def _admin():
    u = User.objects.create_user(
        username='backup_admin',
        email='backup_admin@example.com',
        password='backup-admin-pw-12',
        is_superuser=True,
        is_staff=True,
    )
    Administrator.objects.create(user=u)
    return u


@override_settings(DB_BACKUP_MAX_COUNT=5)
class AdminBackupApiTests(TestCase):
    """BACKUP_DIR is isolated per test via tempfile."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.backup_root = Path(self._td.name)
        self.addCleanup(self._td.cleanup)
        self.admin = _admin()

    def _settings_cm(self):
        return self.settings(BACKUP_DIR=self.backup_root)

    def test_create_returns_json_and_file_exists(self):
        with self._settings_cm():
            self.client.force_login(self.admin)
            url = reverse('accounts:api_admin_backup_create')
            resp = self.client.post(url, data={}, content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data.get('ok'))
        name = data.get('filename')
        self.assertIsNotNone(name)
        self.assertTrue(name.startswith('db_backup_'))
        self.assertTrue((self.backup_root / name).is_file())

    def test_delete_json_removes_file(self):
        """JSON delete must use request.data only (no RawPostDataException)."""
        dummy = self.backup_root / 'db_backup_20990101_120000.sqlite3'
        dummy.write_bytes(b'sqlite placeholder')
        with self._settings_cm():
            self.client.force_login(self.admin)
            url = reverse('accounts:api_admin_backup_delete')
            resp = self.client.post(
                url,
                data=json.dumps({'filename': dummy.name}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json().get('ok'), True)
        self.assertFalse(dummy.exists())

    def test_delete_missing_file_404(self):
        with self._settings_cm():
            self.client.force_login(self.admin)
            url = reverse('accounts:api_admin_backup_delete')
            resp = self.client.post(
                url,
                data=json.dumps({'filename': 'db_backup_20990103_140000.sqlite3'}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 404)

    def test_delete_invalid_filename_400(self):
        with self._settings_cm():
            self.client.force_login(self.admin)
            url = reverse('accounts:api_admin_backup_delete')
            resp = self.client.post(
                url,
                data=json.dumps({'filename': '../../../etc/passwd'}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 400)

    def test_restore_missing_returns_404_parses_json(self):
        with self._settings_cm():
            self.client.force_login(self.admin)
            url = reverse('accounts:api_admin_backup_restore')
            resp = self.client.post(
                url,
                data=json.dumps({'filename': 'db_backup_20990104_150000.sqlite3'}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 404)

    def test_non_admin_forbidden(self):
        user = User.objects.create_user('nobackup', 'nobackup@example.com', 'pw-test-123')
        with self._settings_cm():
            self.client.force_login(user)
            url = reverse('accounts:api_admin_backup_delete')
            resp = self.client.post(
                url,
                data=json.dumps({'filename': 'db_backup_20990101_120000.sqlite3'}),
                content_type='application/json',
            )
        self.assertEqual(resp.status_code, 403)


@override_settings(DB_BACKUP_MAX_COUNT=5)
class BackupDatabaseTaskTests(TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.backup_root = Path(self._td.name)
        self.addCleanup(self._td.cleanup)

    def test_task_creates_backup_file(self):
        with self.settings(BACKUP_DIR=self.backup_root):
            path_str = backup_database_task.run()
        p = Path(path_str)
        self.assertTrue(p.is_file())
        self.assertEqual(p.parent.resolve(), self.backup_root.resolve())
        self.assertRegex(p.name, r'^db_backup_[0-9]{8}_[0-9]{6}\.sqlite3$')

    def test_task_rotation_respects_max_count(self):
        # Timestamps are second-resolution; avoid two files mapping to one name.
        with self.settings(BACKUP_DIR=self.backup_root, DB_BACKUP_MAX_COUNT=2):
            backup_database_task.run()
            time.sleep(1.1)
            backup_database_task.run()
            names = sorted(self.backup_root.glob('db_backup_*.sqlite3'))
            self.assertEqual(len(names), 2)
            time.sleep(1.1)
            backup_database_task.run()
            names_after = sorted(self.backup_root.glob('db_backup_*.sqlite3'))
            self.assertEqual(len(names_after), 2)

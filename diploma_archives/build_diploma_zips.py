"""
Собирает два ZIP в папку diploma_archives/:
  - Эксплуатационный_пакет_JobFlex.zip
  - Тексты_программ_JobFlex.zip

Запуск из корня репозитория:
  python diploma_archives/build_diploma_zips.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "diploma_archives"

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "staticfiles",
    "media",
    "backups",
    "logs",
    ".cursor",
    ".idea",
    ".pytest_cache",
    "htmlcov",
    "diploma_archives",
}

SKIP_FILE_NAMES = {
    ".env",
    ".env.render",
    "db.sqlite3",
    "locust_report.html",
    "celerybeat-schedule",
    "celerybeat-schedule-shm",
    "celerybeat-schedule-wal",
}

ENV_EXAMPLE = """# Скопируйте в файл .env в корне проекта (рядом с manage.py). Секреты не публикуйте.
# Минимум для первого запуска можно не задавать — см. README (SQLite, DEBUG).

DJANGO_SECRET_KEY=
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
SITE_URL=http://127.0.0.1:8000

# DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DBNAME

CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

HH_API_CLIENT_ID=
HH_API_CLIENT_SECRET=
HH_API_TOKEN=

DGIS_API_KEY=
DGIS_MAPGL_KEY=

TELEGRAM_BOT_TOKEN=
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
DEFAULT_FROM_EMAIL=
"""

README_OP = """# Эксплуатационный пакет — JobFlex

Используйте вместе с полным каталогом исходников (архив «Тексты программ» или клон репозитория).

## Состав архива

| Файл / папка | Назначение |
|--------------|------------|
| requirements.txt | Зависимости Python |
| requirements-dev.txt | Зависимости для тестов (опционально) |
| runtime.txt | Версия Python для деплоя |
| .env.example | Шаблон переменных окружения |
| env_render.example.txt | Пример для Render / внешней БД |
| manage.py | Точка входа Django |
| run_all.py | Локально: runserver + Celery + опрос Telegram |
| tools/ | Служебные скрипты (run_render_import) |
| README.md | Полная инструкция |

## Краткий запуск (Windows)

1. Python 3.11+, для полного стека — Redis (порт 6379).
2. `python -m venv .venv` → активировать → `pip install -r requirements.txt`
3. Распакуйте архив «Тексты программ» в ту же папку, где лежат manage.py и run_all.py (или наоборот).
4. Создайте `.env` по `.env.example`.
5. `python manage.py migrate`
6. `python manage.py runserver 0.0.0.0:8000` или `python run_all.py`

Подробности — в README.md внутри архива.
"""


def zip_dir_flat(zip_path: Path, source_dir: Path, arc_prefix: str = "") -> None:
    """Pack all files under source_dir into zip with optional prefix."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in source_dir.rglob("*"):
            if fp.is_dir():
                continue
            rel = fp.relative_to(source_dir)
            arc = f"{arc_prefix}{rel.as_posix()}" if arc_prefix else rel.as_posix()
            zf.write(fp, arc)


def build_operational(staging: Path) -> None:
    staging.mkdir(parents=True, exist_ok=True)
    pairs = [
        ("requirements.txt", "requirements.txt"),
        ("requirements-dev.txt", "requirements-dev.txt"),
        ("runtime.txt", "runtime.txt"),
        ("manage.py", "manage.py"),
        ("run_all.py", "run_all.py"),
        (".env.render.example", "env_render.example.txt"),
        ("README.md", "README.md"),
    ]
    for src_name, dst_name in pairs:
        src = ROOT / src_name
        if src.is_file():
            shutil.copy2(src, staging / dst_name)
    tools_dst = staging / "tools"
    tools_dst.mkdir(exist_ok=True)
    for t in ("run_render_import.ps1", "run_render_import.sh"):
        p = ROOT / "tools" / t
        if p.is_file():
            shutil.copy2(p, tools_dst / t)
    (staging / ".env.example").write_text(ENV_EXAMPLE, encoding="utf-8")
    (staging / "РУКОВОДСТВО_ОПЕРАТОРА.md").write_text(README_OP, encoding="utf-8")


def copy_source_tree(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in ROOT.iterdir():
        if item.name in SKIP_DIR_NAMES:
            continue
        if item.is_file() and item.name in SKIP_FILE_NAMES:
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(
                item,
                target,
                ignore=shutil.ignore_patterns(*sorted(SKIP_DIR_NAMES), "__pycache__", "*.pyc"),
                dirs_exist_ok=True,
            )
        else:
            shutil.copy2(item, target)
    # Remove nested junk that ignore_patterns may miss on deep trees
    for pycache in dest.rglob("__pycache__"):
        if pycache.is_dir():
            shutil.rmtree(pycache, ignore_errors=True)
    for p in dest.rglob("*.pyc"):
        p.unlink(missing_ok=True)


def main() -> int:
    if not (ROOT / "manage.py").is_file():
        print("Run this script from JobFlex repo root (next to manage.py).", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    # ASCII names so Windows console and USB paths work everywhere
    op_zip = OUT / "JobFlex_operational_package.zip"
    src_zip = OUT / "JobFlex_program_sources.zip"

    with tempfile.TemporaryDirectory() as td:
        op_stage = Path(td) / "op"
        build_operational(op_stage)
        if op_zip.exists():
            op_zip.unlink()
        zip_dir_flat(op_zip, op_stage)

    with tempfile.TemporaryDirectory() as td:
        src_stage = Path(td) / "src"
        copy_source_tree(src_stage)
        if src_zip.exists():
            src_zip.unlink()
        zip_dir_flat(src_zip, src_stage)

    print("Done (ASCII names, universal):")
    print(f"  {op_zip}")
    print(f"  {src_zip}")
    ru_op = OUT / "Эксплуатационный_пакет_JobFlex.zip"
    ru_src = OUT / "Тексты_программ_JobFlex.zip"
    shutil.copy2(op_zip, ru_op)
    shutil.copy2(src_zip, ru_src)
    print("Also created Russian-named copies in the same folder (see Explorer).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
# Импорт HH в Postgres на Render с машины разработчика (Shell на Render не нужен).
# 1) cp .env.render.example .env.render  и заполни переменные.
# 2) из корня репозитория:  bash tools/run_render_import.sh
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env.render ]]; then
  echo "Создай .env.render из .env.render.example" >&2
  exit 1
fi
export JOBFLEX_USE_RENDER_DB=1
exec python manage.py render_prod_smoke "$@"

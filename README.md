# JobFlex — агрегатор вакансий (Django)

Веб-приложение на **Django 4.2**: вакансии (в т.ч. импорт с hh.ru и резервный источник), роли пользователей, заявки, чаты, календарь и напоминания, REST API и документация (Swagger / ReDoc). Фоновые задачи выполняются через **Celery** и **Redis**.

---

## 1. Что понадобится

| Компонент | Зачем |
|-----------|--------|
| **Python** | Рекомендуется **3.11** или **3.12** (как на [Render](https://render.com): см. `runtime.txt`). Поддерживается **3.13** и **3.14** (драйвер БД: `psycopg[binary]` в `requirements.txt`). |
| **Git** | Клонирование репозитория |
| **Redis** | Брокер Celery (импорт вакансий, описания, напоминания и т.д.) |
| **Docker Desktop** (опционально) | Удобный способ запустить Redis на Windows/macOS/Linux |
| **PostgreSQL** (опционально) | Только если задаёте `DATABASE_URL`; иначе используется **SQLite** (`db.sqlite3` в корне проекта) |

---

## 2. Клонирование и переход в каталог

```powershell
git clone https://github.com/SonicXTails/Diploma_JobFlex.git
cd Diploma_JobFlex
```

Если репозиторий переименован или форк — подставьте свой URL.

---

## 3. Виртуальное окружение

**Windows (PowerShell):**

```powershell
python -m venv .venv
```

Активация:

```powershell
.\.venv\Scripts\Activate.ps1
```

Если появляется ошибка *«running scripts is disabled»*:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Либо используйте **cmd** и `.\.venv\Scripts\activate.bat`, либо вызывайте интерпретатор без активации: `.\.venv\Scripts\python.exe …`

**Linux / macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

## 4. Установка зависимостей

Обновите установщик пакетов и поставьте зависимости проекта:

```powershell
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

Для запуска тестов (опционально):

```powershell
pip install -r requirements-dev.txt
```

**PostgreSQL:** для локальной разработки драйвер не обязателен, если не задана переменная `DATABASE_URL` — Django создаст SQLite. В продакшене с Postgres используется пакет **`psycopg[binary]`** (Psycopg 3); отдельно ставить `psycopg2-binary` не нужно.

---

## 5. Переменные окружения (файл `.env`)

В корне проекта можно создать файл **`.env`** — он подхватывается автоматически (`python-dotenv`). Файл в репозиторий не коммитится (см. `.gitignore`).

Минимальный набор для первого запуска **не обязателен**: по умолчанию включён отладочный режим и SQLite.

Полезные переменные (см. также `config/settings.py`):

| Переменная | Назначение |
|------------|------------|
| `DJANGO_SECRET_KEY` | Секретный ключ Django (в продакшене обязателен свой) |
| `DJANGO_DEBUG` | `true` / `false` |
| `DJANGO_ALLOWED_HOSTS` | Список хостов через запятую |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Доверенные origin для CSRF (HTTPS), через запятую |
| `SITE_URL` | Базовый URL сайта (уведомления, User-Agent для API hh.ru); по умолчанию `http://localhost:8000` |
| `DATABASE_URL` | Если задан — используется **PostgreSQL** (формат URL, см. [dj-database-url](https://github.com/jazzband/dj-database-url)) |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | URL Redis; по умолчанию `redis://localhost:6379/0` |
| `HH_API_TOKEN`, `HH_API_CLIENT_ID`, `HH_API_CLIENT_SECRET` | Доступ к API hh.ru (при необходимости полного импорта) |
| `TELEGRAM_BOT_TOKEN` | Бот Telegram (если используете сценарии с ботом) |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` и т.д. | Отправка почты |

**Работа с продакшен-БД на Render** (осторожно): шаблон переменных — `.env.render.example`; загрузка `.env.render` включается только при **`JOBFLEX_USE_RENDER_DB=1`** (см. комментарии в `config/settings.py` и скрипты в `tools/`).

---

## 6. Redis

Celery ожидает Redis на **`localhost:6379`**, если вы не переопределили `CELERY_BROKER_URL`.

**Через Docker** (после запуска Docker Desktop):

```powershell
docker run -d --name redis -p 6379:6379 redis:7
```

Проверка: `docker ps` — контейнер `redis` в статусе *running*.

Если Docker недоступен — установите совместимый с Redis сервис (например Memurai Developer на Windows) или Redis в WSL2, чтобы порт **6379** слушался локально.

---

## 7. Миграции базы данных

Из корня репозитория (где лежит `manage.py`):

```powershell
python manage.py migrate
```

Создание учётной записи администратора Django:

```powershell
python manage.py createsuperuser
```

Админка: `http://127.0.0.1:8000/admin/`

---

## 8. Запуск сайта

### Вариант A — только веб-сервер (быстро посмотреть интерфейс)

```powershell
python manage.py runserver 0.0.0.0:8000
```

Сайт: **http://127.0.0.1:8000/**

Фоновые задачи Celery **выполняться не будут** (очередь без worker), пока не запущены Redis и worker.

### Вариант B — полный локальный стек (рекомендуется для проверки функционала)

1. Запущен **Redis** (см. раздел 6).  
2. В корне проекта:

```powershell
python run_all.py
```

Скрипт поднимает процессы: **Django** (`runserver`), **Celery worker**, **Celery beat**, опрос Telegram (`poll_telegram_updates`). Остановка: **Ctrl+C**.

### Вариант C — отдельные терминалы

В каждом окне активируйте `.venv` и перейдите в корень проекта:

1. `python manage.py runserver 0.0.0.0:8000`  
2. `python -m celery -A config worker --loglevel=info --pool=threads --concurrency=4`  
3. `python -m celery -A config beat --loglevel=info`  
4. При необходимости: `python manage.py poll_telegram_updates`

На Windows для worker важен пул **`threads`** (уже учтено в `run_all.py` и в настройках Celery).

---

## 9. Статические файлы

При `DEBUG=True` статика приложений отдаётся через Django. Для продакшена (например на Render) в билде выполняется:

```powershell
python manage.py collectstatic --noinput
```

Собранные файлы попадают в каталог `staticfiles/` (в `.gitignore`).

---

## 10. Тесты

```powershell
pip install -r requirements-dev.txt
pytest
```

---

## 11. Деплой (кратко)

Конфигурация для платформы **Render**: файл **`render.yaml`** (веб-сервис, PostgreSQL, переменные окружения). Подробные комментарии по импорту вакансий и опциональному Redis/Celery — внутри этого файла.

Локальные загрузки пользователей и отладочные дампы не коммитятся: см. **`media/`**, **`logs/`** в `.gitignore`.

---

## 12. Типичные проблемы

| Проблема | Решение |
|-----------|---------|
| `cannot be loaded because running scripts is disabled` | `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` или `activate.bat` / прямой путь к `.venv\Scripts\python.exe` |
| `Failed to build psycopg2` / `pg_config` | В актуальном `requirements.txt` используется **`psycopg[binary]`**; выполните `git pull` и `pip install -r requirements.txt` заново. При необходимости используйте Python **3.11–3.12**. |
| `Error 111 connecting to localhost:6379` | Запустите Redis (Docker или другой способ), проверьте порт. |
| `docker_engine` / pipe not found | Запустите **Docker Desktop** и дождитесь состояния *Running*. |
| Порт 8000 занят | `python manage.py runserver 0.0.0.0:8001` |

---

## 13. Структура репозитория (кратко)

| Путь | Назначение |
|------|------------|
| `config/` | Настройки Django, Celery, URL |
| `accounts/`, `vacancies/` | Приложения проекта |
| `manage.py` | Точка входа Django |
| `run_all.py` | Локальный запуск нескольких процессов |
| `requirements.txt` | Зависимости продакшена |
| `requirements-dev.txt` | Линтеры и тесты |
| `render.yaml` | Blueprint для Render |
| `tools/` | Вспомогательные скрипты (импорт на прод и т.д.) |

---

Вопросы по настройке окружения удобно сверять с комментариями в `render.yaml` и `config/settings.py`.
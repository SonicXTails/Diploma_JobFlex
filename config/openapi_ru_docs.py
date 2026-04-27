# Русские описания и примеры для ReDoc / Swagger (дополняют operation_summary).
import json


def _j(data) -> str:
    return "```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"


def _d(
    text: str,
    *,
    req_json=None,
    resp_json=None,
    note: str | None = None,
) -> str:
    parts = [text.strip()]
    if req_json is not None:
        parts.append("**Пример тела запроса (JSON):**\n\n" + _j(req_json))
    if resp_json is not None:
        parts.append("**Пример ответа:**\n\n" + _j(resp_json))
    if note:
        parts.append(note.strip())
    return "\n\n".join(parts)


RU_TAG_DESCRIPTIONS = [
    {
        "name": "accounts",
        "description": "Аккаунты: регистрация, вход, профиль, файлы, отклики, закладки, чаты, тема UI, Telegram/e-mail.",
    },
    {
        "name": "presets",
        "description": "Пользовательские пресеты фильтров поиска вакансий.",
    },
    {
        "name": "documents",
        "description": "Документы для верификации в профиле (паспорт, СНИЛС и др.).",
    },
    {
        "name": "admin",
        "description": "Резервное копирование БД и модерация обратной связи (только администратор).",
    },
    {
        "name": "calendar",
        "description": "Календарь: события, заметки, экспорт месяца, календарь менеджера.",
    },
    {
        "name": "interviews",
        "description": "Назначение, отмена и перенос собеседований.",
    },
    {
        "name": "vacancies",
        "description": "Вакансии: жалобы, переключение активности, описание, рейтинг работодателя.",
    },
    {
        "name": "moderation",
        "description": "Модерация: статусы жалоб, карточка вакансии, удаление, восстановление.",
    },
    {
        "name": "api",
        "description": "Публичные вспомогательные методы (описание вакансии и т.п.).",
    },
]

_ENTRIES: list[tuple[str, str, str]] = []

# —— accounts: auth / register ——
_ENTRIES += [
    (
        "/accounts/api/register/",
        "post",
        _d(
            "Регистрация соискателя. Допустимы JSON, form-urlencoded или multipart. "
            "Обязательны: фамилия, имя, username, телефон в формате РФ, пол (M/F), город, дата рождения (YYYY-MM-DD), гражданство, пароль.",
            req_json={
                "last_name": "Иванов",
                "first_name": "Иван",
                "patronymic": "Иванович",
                "username": "ivan",
                "email": "ivan@example.com",
                "phone": "79161234567",
                "gender": "M",
                "city": "Москва",
                "birth_date": "1995-05-01",
                "citizenship": "RU",
                "telegram": "@ivan",
                "consent_email": True,
                "consent_telegram": False,
                "password": "Secret123",
            },
            resp_json={"ok": True},
        ),
    ),
    (
        "/accounts/api/register-manager/",
        "post",
        _d(
            "Регистрация менеджера (работодателя). JSON с полями username, password, имя, фамилия и др.",
            req_json={
                "username": "manager1",
                "password": "Secret123",
                "last_name": "Петров",
                "first_name": "Пётр",
                "patronymic": "Петрович",
                "email": "hr@company.ru",
                "telegram": "@company_hr",
                "company": "ООО Ромашка",
                "phone": "74951234567",
            },
            resp_json={"ok": True},
        ),
    ),
    (
        "/accounts/api/login/",
        "post",
        _d(
            "Вход в систему. В теле JSON укажите `username` или `email`, и `password`. "
            "Устанавливается сессионная cookie; в Swagger/ReDoc используйте Authorize → Session.",
            req_json={"username": "ivan", "password": "Secret123"},
            resp_json={"ok": True, "redirect_to": "/"},
        ),
    ),
    (
        "/accounts/api/logout/",
        "post",
        _d(
            "Выход: сессия сбрасывается.",
            resp_json={"ok": True},
        ),
    ),
    (
        "/accounts/api/ui/theme/",
        "get",
        _d(
            "Текущая тема интерфейса для авторизованного пользователя (`light` / `dark`) или `null` для гостя.",
            resp_json={"ok": True, "theme": "dark"},
        ),
    ),
    (
        "/accounts/api/ui/theme/",
        "post",
        _d(
            "Сохранить тему. Только для авторизованных. Тело JSON: `theme` = `light` или `dark`.",
            req_json={"theme": "dark"},
            resp_json={"ok": True, "theme": "dark"},
        ),
    ),
]

# —— profile / data ——
_ENTRIES += [
    (
        "/accounts/api/profile-data/",
        "get",
        _d(
            "Полные данные профиля (соискатель и/или менеджер). Требуется вход; для администратора вернётся ошибка `admin_has_no_profile`.",
            resp_json={"ok": True, "first_name": "Иван", "last_name": "Иванов", "email": "ivan@example.com"},
        ),
    ),
    (
        "/accounts/api/profile/update/",
        "patch",
        _d(
            "Частичное обновление профиля JSON-объектом (имя, контакты, город и т.д. — см. реализацию на сервере).",
            req_json={"first_name": "Иван", "city": "Санкт-Петербург"},
            resp_json={"ok": True},
        ),
    ),
    (
        "/accounts/api/profile/education/",
        "post",
        _d("Добавить запись об образовании.", req_json={"level": "ВО", "institution": "МГУ", "graduation_year": 2020}),
    ),
    (
        "/accounts/api/profile/education/{id}/",
        "patch",
        _d("Обновить запись об образовании по `id`.", req_json={"institution": "СПбГУ"}),
    ),
    (
        "/accounts/api/profile/education/{id}/",
        "delete",
        _d("Удалить запись об образовании."),
    ),
    (
        "/accounts/api/profile/extra-education/",
        "post",
        _d(
            "Добавить дополнительное образование (в т.ч. `document_serial`).",
            req_json={"title": "Курс Python", "organization": "Школа X", "year": 2024, "document_serial": "AB-123456"},
        ),
    ),
    (
        "/accounts/api/profile/extra-education/{id}/",
        "patch",
        _d("Обновить доп. образование.", req_json={"document_serial": "CD-999"}),
    ),
    (
        "/accounts/api/profile/extra-education/{id}/",
        "delete",
        _d("Удалить доп. образование."),
    ),
    (
        "/accounts/api/profile/work/",
        "post",
        _d(
            "Добавить опыт работы.",
            req_json={"company": "ООО Тест", "position": "Разработчик", "start_month": 1, "start_year": 2020},
        ),
    ),
    (
        "/accounts/api/profile/work/{id}/",
        "patch",
        _d("Обновить опыт работы.", req_json={"position": "Senior"}),
    ),
    (
        "/accounts/api/profile/work/{id}/",
        "delete",
        _d("Удалить запись об опыте работы."),
    ),
    (
        "/accounts/api/profile/skills/",
        "put",
        _d(
            "Полная замена списка навыков.",
            req_json={"skills": ["Python", "Django", "SQL"]},
        ),
    ),
]

# —— documents ——
_MP_DOC = (
    "**Формат:** `multipart/form-data`. Передавайте поля как в HTML-форме; для файлов — поле `files` (несколько файлов)."
)
_ENTRIES += [
    (
        "/accounts/api/profile/documents/",
        "get",
        _d("Список документов текущего пользователя (маскированные номера, ссылки на файлы)."),
    ),
    (
        "/accounts/api/profile/documents/",
        "post",
        _d(
            "Добавить документ: тип, серия/номер, дата выдачи, файлы (JPG/PNG/WEBP/PDF, до 10 МБ каждый).",
            note=_MP_DOC
            + "\n\n**Поля формы (пример имён):** `doc_type`, `serial`, `number`, `issued_date`, `issued_by`, `division_code`, `files`.",
        ),
    ),
    (
        "/accounts/api/profile/documents/{id}/delete/",
        "post",
        _d("Удалить документ с идентификатором `id` (только свой).", resp_json={"ok": True}),
    ),
]

# —— uploads ——
_ENTRIES += [
    (
        "/accounts/api/upload-avatar/",
        "post",
        _d(
            "Загрузка аватара. `multipart/form-data`, поле **`avatar`** — файл изображения.",
            note=_MP_DOC,
        ),
    ),
    (
        "/accounts/api/upload-company-logo/",
        "post",
        _d(
            "Логотип компании (только менеджер). Поле **`logo`**.",
            note=_MP_DOC,
        ),
    ),
    (
        "/accounts/api/upload-resume/",
        "post",
        _d(
            "Загрузка резюме Word. Поле **`resume`**, расширения `.doc` / `.docx`.",
            note=_MP_DOC,
        ),
    ),
    (
        "/accounts/api/delete-resume/",
        "post",
        _d("Удалить загруженный файл резюме соискателя.", resp_json={"ok": True}),
    ),
]

# —— apply / bookmark / analytics ——
_ENTRIES += [
    (
        "/accounts/api/apply/",
        "post",
        _d(
            "Отклик на вакансию.",
            req_json={"vacancy_id": 123, "cover_letter": "Готов обсудить проект"},
            resp_json={"ok": True},
        ),
    ),
    (
        "/accounts/api/applications/{id}/status/",
        "post",
        _d(
            "Сменить статус отклика (менеджер).",
            req_json={"status": "accepted"},
            resp_json={"ok": True},
        ),
    ),
    (
        "/accounts/api/bookmark/{id}/",
        "post",
        _d(
            "Переключить закладку на вакансии; `id` — первичный ключ вакансии в БД.",
            resp_json={"ok": True, "bookmarked": True},
        ),
    ),
    (
        "/accounts/api/analytics/",
        "get",
        _d("Персональная аналитика соискателя: закладки, просмотры, агрегаты для графиков."),
    ),
    (
        "/accounts/api/resume/analyze/",
        "get",
        _d("Анализ заполненности резюме (подсказки для пользователя)."),
    ),
]

# —— feedback / telegram / email ——
_ENTRIES += [
    (
        "/accounts/api/feedback/",
        "get",
        _d("Статус лимита отправки предложений/критики (раз в неделю для обычных ролей)."),
    ),
    (
        "/accounts/api/feedback/",
        "post",
        _d(
            "Отправить предложение или критику по сайту.",
            req_json={"kind": "suggestion", "text": "Добавьте тёмную тему везде"},
            resp_json={"ok": True},
        ),
    ),
    (
        "/accounts/api/send-telegram-welcome/",
        "post",
        _d("Инициировать приветствие в Telegram (см. логику согласий).", req_json={"telegram": "@user"}),
    ),
    (
        "/accounts/api/set-consent/",
        "post",
        _d("Согласие на уведомления Telegram.", req_json={"consent_telegram": True}),
    ),
    (
        "/accounts/api/test-message/",
        "post",
        _d("Тестовое сообщение в Telegram для текущего пользователя."),
    ),
    (
        "/accounts/api/unlink-telegram/",
        "post",
        _d("Отвязать Telegram.", resp_json={"ok": True}),
    ),
    (
        "/accounts/api/set-email-consent/",
        "post",
        _d("Согласие на рассылку по e-mail.", req_json={"consent_email": True}),
    ),
    (
        "/accounts/api/test-email/",
        "post",
        _d("Отправить тестовое письмо."),
    ),
    (
        "/accounts/api/unlink-email/",
        "post",
        _d("Отключить уведомления по почте."),
    ),
]

# —— presets / metro / role / delete ——
_ENTRIES += [
    (
        "/accounts/api/presets/",
        "get",
        _d("Список пресетов фильтров."),
    ),
    (
        "/accounts/api/presets/",
        "post",
        _d(
            "Создать пресет.",
            req_json={"name": "Моя подборка", "filters": {"query": "Python"}},
            resp_json={"ok": True, "id": 1},
        ),
    ),
    (
        "/accounts/api/presets/{id}/",
        "patch",
        _d("Обновить пресет.", req_json={"name": "Новое имя"}),
    ),
    (
        "/accounts/api/presets/{id}/",
        "delete",
        _d("Удалить пресет."),
    ),
    (
        "/accounts/api/metro-data/",
        "get",
        _d("Справочник станций метро для форм."),
    ),
    (
        "/accounts/api/switch-role/",
        "post",
        _d(
            "Переключить активную роль (если у пользователя есть и соискатель, и менеджер).",
            req_json={"role": "applicant"},
            resp_json={"ok": True},
        ),
    ),
    (
        "/accounts/delete/",
        "post",
        _d("Удаление своего аккаунта (подтверждение на стороне клиента)."),
    ),
    (
        "/accounts/telegram-webhook/",
        "post",
        _d(
            "Вебхук Telegram Bot API. Вызывается только серверами Telegram; для ручного теста нужен валидный update JSON.",
            note="**Пример:** стандартный объект `Update` из Bot API.",
        ),
    ),
]

# —— chats ——
_ENTRIES += [
    (
        "/accounts/api/chats/start/",
        "post",
        _d(
            "Начать чат с соискателем (менеджер).",
            req_json={"applicant_user_id": 5},
            resp_json={"ok": True, "chat_id": 1},
        ),
    ),
    (
        "/accounts/api/chats/{id}/send/",
        "post",
        _d(
            "Отправить сообщение в чат `id`.",
            req_json={"text": "Здравствуйте!"},
            resp_json={"ok": True},
        ),
    ),
    (
        "/accounts/api/chats/{id}/messages/",
        "get",
        _d("Получить новые сообщения (long-poll / инкремент — см. query-параметры в коде)."),
    ),
    (
        "/accounts/api/chats/{id}/delete/",
        "delete",
        _d("Удалить чат для текущего пользователя."),
    ),
]

# —— admin ——
_ENTRIES += [
    (
        "/accounts/api/admin/feedback/{feedback_id}/action/",
        "post",
        _d(
            "Действие над сообщением обратной связи: `action` = `archive` | `reject` | `resolve` | `restore` (form или query).",
            req_json={"action": "resolve"},
            resp_json={"ok": True},
        ),
    ),
    (
        "/accounts/api/admin/backup/create/",
        "post",
        _d(
            "Создать файл резервной копии SQLite в каталоге бэкапов.",
            resp_json={"ok": True, "filename": "backup_20260101.sqlite3", "size_bytes": 12345},
        ),
    ),
    (
        "/accounts/api/admin/backup/restore/",
        "post",
        _d(
            "Восстановить БД из имени файла бэкапа (только безопасное имя файла).",
            req_json={"filename": "backup_20260101.sqlite3"},
            resp_json={"ok": True},
        ),
    ),
    (
        "/accounts/api/admin/backup/delete/",
        "post",
        _d(
            "Удалить файл бэкапа по имени.",
            req_json={"filename": "backup_old.sqlite3"},
            resp_json={"ok": True},
        ),
    ),
]

# —— calendar ——
_CAL_NOTE = (
    "**Заметки календаря (JSON-тело):** создание — `POST` с полями `date` (YYYY-MM-DD), `title`, `text`, `color`, `time`; "
    "обновление — `PATCH` с `id` и изменяемыми полями; удаление — `DELETE` с `id`."
)
_ENTRIES += [
    (
        "/accounts/api/calendar/events/",
        "get",
        _d(
            "События на дату. Query: `date=YYYY-MM-DD`. Набор событий зависит от роли (соискатель / менеджер / админ).",
        ),
    ),
    (
        "/accounts/api/calendar/note/",
        "post",
        _d("Создать заметку.", note=_CAL_NOTE, req_json={"date": "2026-04-27", "title": "Созвон", "text": "Обсудить оффер"}),
    ),
    (
        "/accounts/api/calendar/note/",
        "patch",
        _d("Обновить заметку.", note=_CAL_NOTE, req_json={"id": 1, "title": "Новый заголовок"}),
    ),
    (
        "/accounts/api/calendar/note/",
        "delete",
        _d("Удалить заметку.", note=_CAL_NOTE, req_json={"id": 1}),
    ),
    (
        "/accounts/api/calendar/month/",
        "get",
        _d("Все заметки и интервью за месяц. Query: `year`, `month`."),
    ),
    (
        "/accounts/api/calendar/notes-index/",
        "get",
        _d("Плоский список заметок для поиска по календарю."),
    ),
    (
        "/accounts/api/manager/calendar/events/",
        "get",
        _d("События календаря менеджера на дату (`date=YYYY-MM-DD`): отклики, интервью, заметки."),
    ),
]

# —— interviews ——
_ENTRIES += [
    (
        "/accounts/api/interviews/schedule/",
        "post",
        _d(
            "Назначить собеседование.",
            req_json={
                "applicant_user_id": 3,
                "vacancy_id": 10,
                "date": "2026-05-01",
                "time": "14:00",
                "location": "Офис, ул. Примерная, 1",
                "notes": "Возьмите паспорт",
            },
            resp_json={"ok": True, "id": 1},
        ),
    ),
    (
        "/accounts/api/interviews/cancel/",
        "delete",
        _d(
            "Отменить собеседование. Тело JSON: `id` интервью.",
            req_json={"id": 1},
            resp_json={"ok": True},
        ),
    ),
    (
        "/accounts/api/interviews/reschedule/",
        "patch",
        _d(
            "Перенос собеседования (менеджер).",
            req_json={"id": 1, "date": "2026-05-02", "time": "15:30"},
            resp_json={"ok": True},
        ),
    ),
]

# —— vacancies app (prefix /api/ or /{id}/) ——
_ENTRIES += [
    (
        "/api/employer-rating/{hh_id}/",
        "get",
        _d("Рейтинг работодателя по идентификатору hh.ru (`hh_id`)."),
    ),
    (
        "/api/vacancy-description/{id}/",
        "get",
        _d("Текст описания вакансии (ленивая подгрузка для карточки)."),
    ),
    (
        "/{id}/report/",
        "post",
        _d(
            "Жалоба на локальную вакансию. `id` — первичный ключ вакансии. Одна жалоба от пользователя на вакансию.",
            req_json={"reason_code": "spam", "reason_text": "Подозрительные условия"},
            resp_json={"ok": True, "already_reported": False, "id": 1},
        ),
    ),
    (
        "/{id}/toggle-active/",
        "patch",
        _d(
            "Переключить признак активности своей вакансии (менеджер-владелец).",
            resp_json={"ok": True, "is_active": False},
        ),
    ),
    (
        "/api/reports/{id}/self-status/",
        "post",
        _d(
            "Модератор: обновить личный статус обработки жалобы (`self_status`, заметка и т.д.).",
            req_json={"self_status": "in_work", "moderator_note": "Проверяю"},
        ),
    ),
    (
        "/api/reports/{id}/self-status/",
        "patch",
        _d("То же, что POST — частичное обновление полей жалобы модератором.", req_json={"self_status": "waiting"}),
    ),
    (
        "/api/reports/vacancy/{vacancy_id}/state/",
        "post",
        _d(
            "Модератор: статус модерации карточки вакансии.",
            req_json={"status": "in_review", "note": "Нужна проверка контактов"},
        ),
    ),
    (
        "/api/reports/vacancy/{vacancy_id}/state/",
        "patch",
        _d("Частичное обновление статуса модерации вакансии.", req_json={"status": "approved"}),
    ),
    (
        "/api/moderator/vacancy/{vacancy_id}/delete/",
        "post",
        _d(
            "Мягкое удаление вакансии модератором. Обычно `multipart`: текст причины и фото-доказательства.",
            note=_MP_DOC + "\n\nПоле **`reason`** обязательно; файлы — по логике представления `api_moderator_delete_vacancy`.",
        ),
    ),
    (
        "/api/admin/moderator-report/{report_id}/restore/",
        "post",
        _d(
            "Администратор: восстановить вакансию после удаления модератором (`report_id` — отчёт об удалении).",
            resp_json={"ok": True},
        ),
    ),
]

RU_OPERATION_DESCRIPTIONS: dict[tuple[str, str], str] = {}
for path, method, doc in _ENTRIES:
    key = (path, method)
    if key in RU_OPERATION_DESCRIPTIONS:
        raise ValueError(f"Duplicate OpenAPI doc key: {key}")
    RU_OPERATION_DESCRIPTIONS[key] = (
        doc
        + "\n\n---\n**Общее:** для POST/PATCH/DELETE с сессией в браузере может потребоваться заголовок `X-CSRFToken` "
        "(в Swagger он подставляется после входа при использовании схемы Session)."
    )

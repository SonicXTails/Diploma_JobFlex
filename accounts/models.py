from django.db import models
from django.contrib.auth.models import User


class Applicant(models.Model):
    GENDER_CHOICES = [('M', 'Мужской'), ('F', 'Женский')]
    CITIZENSHIP_CHOICES = [
        ('RU', 'Россия'), ('BY', 'Беларусь'), ('KZ', 'Казахстан'),
        ('KG', 'Киргизия'), ('AM', 'Армения'), ('TJ', 'Таджикистан'),
        ('UZ', 'Узбекистан'), ('UA', 'Украина'), ('MD', 'Молдова'),
        ('AZ', 'Азербайджан'), ('TM', 'Туркменистан'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='applicant', verbose_name='Пользователь')
    patronymic = models.CharField('Отчество', max_length=150, blank=True)
    telegram = models.CharField('Телеграм', max_length=100)
    telegram_chat_id = models.BigIntegerField('ID чата Telegram', null=True, blank=True)
    telegram_start_token = models.CharField('Стартовый токен Telegram', max_length=64, null=True, blank=True, unique=True)
    consent_email = models.BooleanField('Согласие на e-mail', default=False)
    consent_telegram = models.BooleanField('Согласие на Telegram', default=False)
    phone = models.CharField('Телефон', max_length=30, blank=True)
    gender = models.CharField('Пол', max_length=1, choices=GENDER_CHOICES, blank=True)
    city = models.CharField('Город', max_length=150, blank=True)
    birth_date = models.DateField('Дата рождения', null=True, blank=True)
    citizenship = models.CharField('Гражданство', max_length=2, choices=CITIZENSHIP_CHOICES, blank=True)
    skills = models.JSONField('Навыки', default=list, blank=True)
    # Location preference: nearest metro station -OR- free-text address
    LOCATION_TYPE_CHOICES = [('metro', 'Ст. метро'), ('address', 'Адрес'), ('', 'Не указано')]
    location_type        = models.CharField('Тип местоположения', max_length=10, blank=True, default='')
    metro_city_id        = models.CharField('ID города метро (HH)', max_length=10, blank=True)
    metro_station_id     = models.CharField('ID станции метро (HH)', max_length=20, blank=True)
    metro_station_name   = models.CharField('Название станции', max_length=150, blank=True)
    metro_line_name      = models.CharField('Название линии', max_length=150, blank=True)
    metro_line_color     = models.CharField('Цвет линии HEX', max_length=7, blank=True)
    metro_stations       = models.JSONField('Список станций метро', default=list, blank=True)
    address              = models.CharField('Адрес', max_length=500, blank=True)
    # Salary expectations
    salary_expectation_from = models.IntegerField('Зарплата от (ожидаемая)', null=True, blank=True)
    salary_expectation_to   = models.IntegerField('Зарплата до (ожидаемая)', null=True, blank=True)
    avatar = models.ImageField('Аватар', upload_to='avatars/%Y/', null=True, blank=True)
    # Resume extras
    about_me         = models.TextField('О себе', blank=True)
    desired_position = models.CharField('Желаемая должность', max_length=255, blank=True)
    github_url       = models.URLField('GitHub', max_length=300, blank=True)
    portfolio_url    = models.URLField('Портфолио / сайт', max_length=300, blank=True)
    # Role history
    was_manager = models.BooleanField('Был менеджером', default=False)
    # Preserved company logo path when this applicant temporarily switches back from manager role
    manager_company_logo = models.CharField('Путь к логотипу компании', max_length=500, blank=True)
    # Uploaded Word resume file
    resume_file = models.FileField('Файл резюме (Word)', upload_to='resumes/%Y/', null=True, blank=True)

    def __str__(self):
        return f"{self.user.get_full_name()} <{self.user.email}>"

    class Meta:
        verbose_name = 'Соискатель'
        verbose_name_plural = 'Соискатели'


class Education(models.Model):
    LEVEL_CHOICES = [
        ('secondary',          'Среднее'),
        ('vocational',         'Среднее специальное'),
        ('incomplete_higher',  'Неоконченное высшее'),
        ('higher',             'Высшее'),
        ('bachelor',           'Бакалавр'),
        ('master',             'Магистр'),
        ('candidate',          'Кандидат наук'),
        ('doctor',             'Доктор наук'),
    ]

    applicant      = models.ForeignKey(Applicant, on_delete=models.CASCADE, related_name='educations')
    level          = models.CharField('Уровень образования', max_length=30, choices=LEVEL_CHOICES)
    institution    = models.CharField('Учебное заведение', max_length=255)
    graduation_year = models.IntegerField('Год выпуска/окончания', null=True, blank=True)
    faculty        = models.CharField('Факультет', max_length=255, blank=True)
    specialization = models.CharField('Специализация', max_length=255, blank=True)
    order          = models.PositiveSmallIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Образование'
        verbose_name_plural = 'Образование'
        ordering = ['order']

    def __str__(self):
        return f"{self.get_level_display()} — {self.institution}"


class ExtraEducation(models.Model):
    applicant   = models.ForeignKey(Applicant, on_delete=models.CASCADE, related_name='extra_educations')
    name        = models.CharField('Название', max_length=255)
    document_serial = models.CharField('Серийный номер документа', max_length=120, blank=True)
    description = models.TextField('Описание', blank=True)
    order       = models.PositiveSmallIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Доп. образование'
        verbose_name_plural = 'Доп. образование'
        ordering = ['order']

    def __str__(self):
        return self.name


class WorkExperience(models.Model):
    MONTH_CHOICES = [
        (1, 'Январь'), (2, 'Февраль'), (3, 'Март'), (4, 'Апрель'),
        (5, 'Май'), (6, 'Июнь'), (7, 'Июль'), (8, 'Август'),
        (9, 'Сентябрь'), (10, 'Октябрь'), (11, 'Ноябрь'), (12, 'Декабрь'),
    ]

    applicant        = models.ForeignKey(Applicant, on_delete=models.CASCADE, related_name='work_experiences')
    company          = models.CharField('Компания', max_length=255)
    position         = models.CharField('Должность', max_length=255)
    start_month      = models.IntegerField('Месяц начала', null=True, blank=True, choices=MONTH_CHOICES)
    start_year       = models.IntegerField('Год начала', null=True, blank=True)
    end_month        = models.IntegerField('Месяц окончания', null=True, blank=True, choices=MONTH_CHOICES)
    end_year         = models.IntegerField('Год окончания', null=True, blank=True)
    is_current       = models.BooleanField('Работаю сейчас', default=False)
    responsibilities = models.TextField('Обязанности и достижения', blank=True)
    order            = models.PositiveSmallIntegerField('Порядок', default=0)

    class Meta:
        verbose_name = 'Опыт работы'
        verbose_name_plural = 'Опыт работы'
        ordering = ['order']

    def __str__(self):
        return f"{self.position} — {self.company}"


class Manager(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='manager', verbose_name='Пользователь')
    patronymic = models.CharField('Отчество', max_length=150, blank=True)
    company = models.CharField('Компания', max_length=255, blank=True)
    phone = models.CharField('Телефон', max_length=30, blank=True)
    telegram = models.CharField('Телеграм', max_length=100, blank=True)
    telegram_chat_id = models.BigIntegerField('ID чата Telegram', null=True, blank=True)
    consent_email    = models.BooleanField('Согласие на e-mail', default=False)
    consent_telegram = models.BooleanField('Согласие на Telegram', default=False)
    avatar       = models.ImageField('Аватар', upload_to='avatars/%Y/', null=True, blank=True)
    company_logo = models.ImageField('Логотип компании', upload_to='company_logos/%Y/', null=True, blank=True)

    class Meta:
        verbose_name = 'Менеджер'
        verbose_name_plural = 'Менеджеры'

    def __str__(self):
        return f"{self.user.get_full_name()} <{self.user.email}>"


class Administrator(models.Model):
    """
    Профиль администратора системы.
    Пользователь считается администратором только если:
      • он является superuser (user.is_superuser == True)
      • у него есть этот профиль (Administrator)
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='admin_profile',
        verbose_name='Пользователь',
    )
    created_at = models.DateTimeField('Дата назначения', auto_now_add=True)
    notes = models.TextField('Заметки', blank=True)

    class Meta:
        verbose_name = 'Администратор'
        verbose_name_plural = 'Администраторы'

    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.user.is_superuser:
            raise ValidationError(
                'Администратором может быть только суперпользователь (is_superuser=True).'
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Admin: {self.user.get_full_name() or self.user.username}"


class Moderator(models.Model):
    """
    Профиль модератора системы.
    Модератор не является superuser по умолчанию и имеет отдельный кабинет.
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='moderator_profile',
        verbose_name='Пользователь',
    )
    patronymic = models.CharField('Отчество', max_length=150, blank=True)
    phone = models.CharField('Телефон', max_length=30, blank=True)
    telegram = models.CharField('Telegram', max_length=100, blank=True)
    notes = models.TextField('Заметки', blank=True)
    created_at = models.DateTimeField('Дата назначения', auto_now_add=True)

    class Meta:
        verbose_name = 'Модератор'
        verbose_name_plural = 'Модераторы'

    def __str__(self):
        return f"Moderator: {self.user.get_full_name() or self.user.username}"


class Chat(models.Model):
    """A direct chat thread between one manager and one applicant."""
    manager   = models.ForeignKey(User, on_delete=models.CASCADE, related_name='manager_chats')
    applicant = models.ForeignKey(User, on_delete=models.CASCADE, related_name='applicant_chats')
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_by_manager   = models.BooleanField('Удалён менеджером',   default=False)
    deleted_by_applicant = models.BooleanField('Удалён соискателем', default=False)

    class Meta:
        unique_together = [('manager', 'applicant')]
        ordering = ['-created_at']
        verbose_name = 'Чат'
        verbose_name_plural = 'Чаты'

    def __str__(self):
        return f"Чат {self.manager.username} ↔ {self.applicant.username}"

    def other_user(self, me):
        return self.applicant if me == self.manager else self.manager

    def unread_count(self, me):
        return self.messages.filter(is_read=False).exclude(sender=me).count()


class Message(models.Model):
    chat      = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='messages')
    sender    = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    text      = models.TextField('Текст', blank=True)
    file      = models.FileField('Файл', upload_to='chat_files/%Y/%m/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read   = models.BooleanField('Прочитано', default=False)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Сообщение'
        verbose_name_plural = 'Сообщения'

    @property
    def file_basename(self):
        """Return just the filename without upload path prefix."""
        if not self.file:
            return ''
        import os
        return os.path.basename(self.file.name)

    @property
    def file_is_image(self):
        import os
        if not self.file:
            return False
        ext = os.path.splitext(self.file.name)[1].lower()
        return ext in ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg')


class Application(models.Model):
    """A job application: one applicant → one vacancy."""
    STATUS_PENDING  = 'pending'
    STATUS_VIEWED   = 'viewed'
    STATUS_ACCEPTED = 'accepted'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        ('pending',  'Ожидает'),
        ('viewed',   'Просмотрено'),
        ('accepted', 'Приглашение'),
        ('rejected', 'Отклонено'),
    ]

    vacancy      = models.ForeignKey('vacancies.Vacancy', on_delete=models.CASCADE,
                                     related_name='applications')
    applicant    = models.ForeignKey(User, on_delete=models.CASCADE,
                                     related_name='applications')
    cover_letter = models.TextField('Сопроводительное письмо', blank=True)
    status       = models.CharField('Статус', max_length=16, choices=STATUS_CHOICES, default='pending')
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('vacancy', 'applicant')]
        ordering = ['-created_at']
        verbose_name = 'Отклик'
        verbose_name_plural = 'Отклики'

    def __str__(self):
        return f"{self.applicant.get_full_name()} → {self.vacancy.title}"

    def __str__(self):
        return f"{self.sender.username}: {self.text[:40]}"


class FilterPreset(models.Model):
    """A saved set of vacancy search filters belonging to one user."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='filter_presets')
    name = models.CharField('Название', max_length=100)
    # All filter params stored as a plain dict, mirrors GET params used by VacancyListView.
    # Multi-value params (experience, schedule, etc.) are stored as lists.
    filters = models.JSONField('Фильтры', default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Пресет фильтров'
        verbose_name_plural = 'Пресеты фильтров'

    def __str__(self):
        return f"{self.user.username}: {self.name}"


class UserUiPreference(models.Model):
    """Persistent UI preferences (theme, etc.) for a user."""
    THEME_CHOICES = [('light', 'Light'), ('dark', 'Dark')]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='ui_preference')
    theme = models.CharField('Тема сайта', max_length=10, choices=THEME_CHOICES, default='light')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Настройка интерфейса'
        verbose_name_plural = 'Настройки интерфейса'

    def __str__(self):
        return f"{self.user.username}: {self.theme}"


class CalendarNote(models.Model):
    """A personal note added by a user to a specific calendar day."""
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='calendar_notes')
    date       = models.DateField('Дата')
    title      = models.CharField('Название', max_length=200, blank=True, default='')
    text       = models.TextField('Текст заметки', blank=True, default='')
    color      = models.CharField('Цвет', max_length=20, blank=True, default='#c2a35a')
    note_time  = models.TimeField('Время', null=True, blank=True)
    reminded   = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Заметка календаря'
        verbose_name_plural = 'Заметки календаря'

    def __str__(self):
        return f"{self.user.username} [{self.date}]: {self.text[:40]}"


class Interview(models.Model):
    """A scheduled interview between a manager and an applicant."""
    STATUS_SCHEDULED = 'scheduled'
    STATUS_CANCELLED = 'cancelled'
    STATUS_DONE      = 'done'
    STATUS_CHOICES = [
        ('scheduled', 'Запланировано'),
        ('cancelled', 'Отменено'),
        ('done',      'Завершено'),
    ]

    manager      = models.ForeignKey(User, on_delete=models.CASCADE, related_name='interviews_as_manager')
    applicant    = models.ForeignKey(User, on_delete=models.CASCADE, related_name='interviews_as_applicant')
    vacancy      = models.ForeignKey('vacancies.Vacancy', on_delete=models.CASCADE,
                                     related_name='interviews', null=True, blank=True)
    scheduled_at = models.DateTimeField('Дата и время')
    location     = models.CharField('Место / ссылка', max_length=500, blank=True)
    notes        = models.TextField('Заметки', blank=True)
    status       = models.CharField('Статус', max_length=16, choices=STATUS_CHOICES, default='scheduled')
    created_at   = models.DateTimeField(auto_now_add=True)

    # Reminder flags — set to True once the reminder has been sent
    reminded_1d  = models.BooleanField(default=False)
    reminded_1h  = models.BooleanField(default=False)
    reminded_now = models.BooleanField(default=False)

    class Meta:
        ordering = ['scheduled_at']
        verbose_name = 'Собеседование'
        verbose_name_plural = 'Собеседования'

    def __str__(self):
        return f"{self.manager.get_full_name()} → {self.applicant.get_full_name()} [{self.scheduled_at:%d.%m.%Y %H:%M}]"


class ApiActionLog(models.Model):
    """Audit log for selected non-frequent API actions."""
    ACTOR_CHOICES = [
        ('system', 'Система'),
        ('admin', 'Администратор'),
        ('moderator', 'Модератор'),
        ('manager', 'Менеджер'),
        ('applicant', 'Соискатель'),
        ('user', 'Пользователь'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name='api_action_logs',
        null=True,
        blank=True,
    )
    actor_role = models.CharField('Роль', max_length=20, choices=ACTOR_CHOICES, default='system')
    method = models.CharField('HTTP-метод', max_length=10)
    path = models.CharField('Путь', max_length=255)
    endpoint = models.CharField('Эндпоинт', max_length=120, blank=True)
    action = models.CharField('Действие', max_length=120)
    success = models.BooleanField('Успешно', default=True)
    status_code = models.PositiveSmallIntegerField('Код ответа', null=True, blank=True)
    before_data = models.JSONField('До изменения', default=dict, blank=True)
    after_data = models.JSONField('После изменения', default=dict, blank=True)
    meta = models.JSONField('Метаданные', default=dict, blank=True)
    created_at = models.DateTimeField('Создано', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Лог API-действия'
        verbose_name_plural = 'Логи API-действий'

    def __str__(self):
        return f"{self.created_at:%d.%m.%Y %H:%M:%S} {self.method} {self.action} ({self.actor_role})"


class UserFeedback(models.Model):
    """Suggestion or criticism sent by a non-admin/non-moderator user."""
    KIND_SUGGESTION = 'suggestion'
    KIND_CRITICISM = 'criticism'
    KIND_CHOICES = [
        (KIND_SUGGESTION, 'Предложение'),
        (KIND_CRITICISM, 'Критика'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='feedback_items',
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_SUGGESTION)
    message = models.TextField('Сообщение')
    STATUS_ACTIVE = 'active'
    STATUS_ARCHIVED = 'archived'
    STATUS_RESOLVED = 'resolved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'В ленте'),
        (STATUS_ARCHIVED, 'В архиве'),
        (STATUS_RESOLVED, 'Реализовано'),
        (STATUS_REJECTED, 'Отклонено'),
    ]
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='processed_feedback_items',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Предложение/критика пользователя'
        verbose_name_plural = 'Предложения и критика пользователей'

    def __str__(self):
        return f"{self.user.username}: {self.get_kind_display()} ({self.created_at:%d.%m.%Y})"


class UserDocument(models.Model):
    """Personal identity/tax/social document attached in user profile."""
    DOC_PASSPORT_RF = 'passport_rf'
    DOC_SNILS = 'snils'
    DOC_INN = 'inn'
    DOC_FOREIGN_PASSPORT = 'foreign_passport'
    DOC_DRIVER_LICENSE = 'driver_license'
    DOC_MILITARY_ID = 'military_id'
    DOC_TYPE_CHOICES = [
        (DOC_PASSPORT_RF, 'Паспорт РФ'),
        (DOC_SNILS, 'СНИЛС'),
        (DOC_INN, 'ИНН'),
        (DOC_FOREIGN_PASSPORT, 'Загранпаспорт'),
        (DOC_DRIVER_LICENSE, 'Водительское удостоверение'),
        (DOC_MILITARY_ID, 'Военный билет'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='documents')
    doc_type = models.CharField('Тип документа', max_length=32, choices=DOC_TYPE_CHOICES, db_index=True)
    serial = models.CharField('Серия', max_length=32, blank=True)
    number = models.CharField('Номер', max_length=32)
    issued_date = models.DateField('Дата выдачи', null=True, blank=True)
    issued_by = models.CharField('Кем выдан', max_length=255, blank=True)
    division_code = models.CharField('Код подразделения', max_length=16, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Документ пользователя'
        verbose_name_plural = 'Документы пользователей'

    def __str__(self):
        base = self.get_doc_type_display()
        if self.serial:
            return f"{self.user.username}: {base} {self.serial} {self.number}"
        return f"{self.user.username}: {base} {self.number}"


class UserDocumentFile(models.Model):
    document = models.ForeignKey(UserDocument, on_delete=models.CASCADE, related_name='files')
    file = models.FileField('Файл документа', upload_to='user_documents/%Y/%m/')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Файл документа пользователя'
        verbose_name_plural = 'Файлы документов пользователей'

    def __str__(self):
        return f"Файл документа #{self.document_id}"

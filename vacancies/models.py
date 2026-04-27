from django.db import models


class VacancyQuerySet(models.QuerySet):
	def visible_for_ru(self):
		return self.filter(country="Россия").exclude(is_moderator_deleted=True)


class Vacancy(models.Model):
	class WorkFormat(models.TextChoices):
		REMOTE = "remote", "Удалённо"
		HYBRID = "hybrid", "Гибрид"
		ONSITE = "onsite", "На месте"

	external_id = models.CharField(max_length=64)
	# `source` field removed — use single HH source for this project
	title = models.CharField(max_length=255)
	company = models.CharField(max_length=255, blank=True)

	# normalized employer relation (nullable for legacy rows)
	employer = models.ForeignKey(
				'Employer',
				null=True,
				blank=True,
				on_delete=models.SET_NULL,
				related_name='vacancies'
			)
	country = models.CharField(max_length=128)
	region = models.CharField(max_length=128, blank=True)
	experience_id = models.CharField(max_length=32, blank=True)
	experience_name = models.CharField(max_length=128, blank=True)
	# Normalized salary fields parsed from `raw_json['salary']`
	salary_from = models.IntegerField(null=True, blank=True)
	salary_to = models.IntegerField(null=True, blank=True)
	salary_currency = models.CharField(max_length=16, blank=True)
	# Flattened key skills for efficient text search
	key_skills_text = models.TextField(blank=True)
	# Full-text description fields fetched from HH detail endpoint.
	# Stored separately so the list view never needs to read them.
	description = models.TextField(blank=True)
	branded_description = models.TextField(blank=True)
	work_format = models.CharField(
		max_length=16,
		choices=WorkFormat.choices,
		default=WorkFormat.ONSITE,
	)
	is_remote = models.BooleanField(default=False)
	is_hybrid = models.BooleanField(default=False)
	is_onsite = models.BooleanField(default=True)

	# Schedule / employment / label fields parsed from raw_json
	schedule_id = models.CharField(max_length=32, blank=True, db_index=True)
	schedule_name = models.CharField(max_length=128, blank=True)
	employment_id = models.CharField(max_length=32, blank=True, db_index=True)
	employment_name = models.CharField(max_length=128, blank=True)
	employment_form_id = models.CharField(max_length=32, blank=True, db_index=True)
	employment_form_name = models.CharField(max_length=128, blank=True)
	is_internship = models.BooleanField(default=False, db_index=True)
	accept_temporary = models.BooleanField(default=False, db_index=True)
	accept_incomplete_resumes = models.BooleanField(default=False)
	accept_kids = models.BooleanField(default=False)

	url = models.URLField(max_length=500, blank=True)
	published_at = models.DateTimeField()
	raw_json = models.JSONField(default=dict)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	# Site-created vacancies (employer fills the form on this site)
	created_by = models.ForeignKey(
		'auth.User',
		null=True, blank=True,
		on_delete=models.SET_NULL,
		related_name='created_vacancies',
	)
	is_active = models.BooleanField(default=True, db_index=True)
	# Soft-deletion by a moderator: the vacancy is hidden from everyone, but can
	# be restored by an administrator via the moderator reports panel.
	is_moderator_deleted = models.BooleanField(default=False, db_index=True)

	# Extended employer-form fields
	employee_type     = models.CharField('Тип сотрудника', max_length=16, blank=True)  # permanent / temporary
	contract_labor    = models.BooleanField('Трудовой договор', default=False)
	contract_gpc      = models.BooleanField('Договор ГПХ', default=False)
	work_schedule     = models.CharField('График', max_length=32, blank=True)      # 5/2, 6/1, По выходным и т.д.
	hours_per_day     = models.CharField('Часов в день', max_length=8, blank=True)
	has_night_shifts  = models.BooleanField('Ночные смены', default=False)
	salary_gross      = models.BooleanField('До вычета налогов', default=True)
	salary_period     = models.CharField('Период зарплаты', max_length=16, blank=True)   # month / project
	payment_frequency = models.CharField('Частота выплат', max_length=16, blank=True)
	work_address      = models.CharField('Адрес работы', max_length=500, blank=True)
	hide_address      = models.BooleanField('Скрыть адрес', default=False)
	address_comment   = models.CharField('Комментарий к адресу', max_length=255, blank=True)
	# Site-created vacancy location & contact
	lat                     = models.FloatField('Широта', null=True, blank=True)
	lon                     = models.FloatField('Долгота', null=True, blank=True)
	contact_phone           = models.CharField('Контактный телефон', max_length=30, blank=True)
	metro_station_name      = models.CharField('Станция метро', max_length=128, blank=True)
	metro_line_color        = models.CharField('Цвет линии метро', max_length=16, blank=True)
	metro_line_name         = models.CharField('Линия метро', max_length=128, blank=True)
	metro_city_id           = models.CharField('ID города метро', max_length=10, blank=True)
	benefits_text           = models.TextField('Льготы и преимущества', blank=True)
	requirements_text       = models.TextField('Требования', blank=True)
	working_conditions_text = models.TextField('Условия работы', blank=True)

	objects = VacancyQuerySet.as_manager()

	class Meta:
		unique_together = ("external_id",)
		ordering = ("-published_at",)

	def __str__(self):
		return self.title

	@property
	def employer_logo_url(self):
		"""Return a URL for the employer logo.
		Priority: linked Employer.logo_url → created_by manager's company_logo → raw_json payload.
		"""
		if self.employer:
			logo = getattr(self.employer, 'logo_url', None)
			if logo:
				return logo
			logo = getattr(self.employer, 'employer_logo_url', None)
			if logo:
				return logo
		# site-created vacancy: check manager's uploaded company_logo
		if self.created_by_id:
			try:
				from accounts.models import Manager
				mgr = Manager.objects.filter(user_id=self.created_by_id).first()
				if mgr and mgr.company_logo:
					return mgr.company_logo.url
				# fall back to manager's personal avatar so the employer card
				# always has a recognisable image instead of a letter placeholder
				if mgr and mgr.avatar:
					return mgr.avatar.url
				# also check applicant record (avatar is stored there as primary)
				from accounts.models import Applicant
				appl = Applicant.objects.filter(user_id=self.created_by_id).first()
				if appl and appl.avatar:
					return appl.avatar.url
			except Exception:
				pass
		# fallback to legacy raw_json stored on Vacancy
		emp = self.raw_json.get('employer') if isinstance(self.raw_json, dict) else None
		if not isinstance(emp, dict):
			return None
		logos = emp.get('logo_urls') or emp.get('logo')
		if isinstance(logos, dict):
			return logos.get('original') or logos.get('240') or logos.get('90') or None
		if isinstance(logos, str):
			return logos
		return None

	@property
	def work_formats_display(self):
		labels = []
		if self.is_remote:
			labels.append(self.WorkFormat.REMOTE.label)
		if self.is_hybrid:
			labels.append(self.WorkFormat.HYBRID.label)
		if self.is_onsite:
			labels.append(self.WorkFormat.ONSITE.label)
		return ", ".join(labels) if labels else self.get_work_format_display()

	@property
	def work_formats_list(self):
		"""Return work formats as a list of labels for templates."""
		display = self.work_formats_display or ""
		return [s.strip() for s in display.split(",") if s.strip()]

	@property
	def is_hh(self):
		"""True when this vacancy originates from hh.ru (not created on this site)."""
		return 'hh.ru' in (self.url or '')


class Employer(models.Model):
	"""Normalized employer entity storing IDs, logos and ratings from multiple sources."""
	hh_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
	name = models.CharField(max_length=255)
	logo_url = models.URLField(blank=True)
	# rating fields (store HH employer rating when available)
	hh_rating = models.FloatField(blank=True, null=True)
	rating_raw = models.CharField(max_length=128, blank=True)
	rating_updated_at = models.DateTimeField(blank=True, null=True)

	# DreamJob rating fields (scraped or via API)
	dreamjob_rating = models.FloatField(blank=True, null=True)
	dreamjob_rating_raw = models.CharField(max_length=128, blank=True)
	dreamjob_rating_updated_at = models.DateTimeField(blank=True, null=True)
	raw = models.JSONField(default=dict, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ("name",)

	def __str__(self):
		return self.name

	@property
	def employer_logo_url(self):
		"""Return employer logo using explicit `logo_url` if present,
		otherwise try to extract from stored `raw` payload (HH format).
		"""
		# explicit stored URL has priority
		if self.logo_url:
			return self.logo_url
		# fall back to raw payload saved on Employer
		emp = self.raw if isinstance(self.raw, dict) else None
		if not isinstance(emp, dict):
			return None
		# HH often exposes logos under 'logo_urls' or 'logo'
		logos = emp.get('logo_urls') or emp.get('logo')
		if isinstance(logos, dict):
			return logos.get('original') or logos.get('240') or logos.get('90') or None
		if isinstance(logos, str):
			return logos
		return None


class HhArea(models.Model):
	area_id = models.CharField(max_length=32, unique=True)
	name = models.CharField(max_length=255)
	parent_id = models.CharField(max_length=32, blank=True)
	raw_json = models.JSONField(default=dict)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ("name",)

	def __str__(self):
		return self.name


class HhDictionaryItem(models.Model):
	dictionary = models.CharField(max_length=64)
	item_id = models.CharField(max_length=64)
	name = models.CharField(max_length=255)
	parent_id = models.CharField(max_length=64, blank=True)
	raw_json = models.JSONField(default=dict)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		unique_together = ("dictionary", "item_id")
		ordering = ("dictionary", "name")

	def __str__(self):
		return f"{self.dictionary}: {self.name}"


class Review(models.Model):
	"""Simple persistent review model for testing UI.

	This model is intentionally minimal: it attaches to a Vacancy and stores
	an author name and free-text content with a timestamp.
	"""
	vacancy = models.ForeignKey('Vacancy', on_delete=models.CASCADE, related_name='reviews')
	author = models.CharField(max_length=128, blank=True)
	text = models.TextField()
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ('-created_at',)

	def __str__(self):
		return f"Review @{self.vacancy.external_id} by {self.author or 'anon'}"


class Bookmark(models.Model):
	"""Applicant bookmarks / saved vacancies."""
	user    = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='bookmarks')
	vacancy = models.ForeignKey('Vacancy',   on_delete=models.CASCADE, related_name='bookmarked_by')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		unique_together = ('user', 'vacancy')
		ordering = ('-created_at',)
		verbose_name = 'Закладка'
		verbose_name_plural = 'Закладки'

	def __str__(self):
		return f"{self.user_id} → {self.vacancy_id}"


class VacancyView(models.Model):
	"""Track when a logged-in user views a vacancy detail page."""
	user       = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='vacancy_views')
	vacancy    = models.ForeignKey('Vacancy',   on_delete=models.CASCADE, related_name='views')
	viewed_at  = models.DateTimeField(auto_now=True)   # updated on each revisit

	class Meta:
		unique_together = ('user', 'vacancy')
		ordering = ('-viewed_at',)
		verbose_name = 'Просмотр вакансии'
		verbose_name_plural = 'Просмотры вакансий'

	def __str__(self):
		return f"{self.user_id} viewed {self.vacancy_id}"


class VacancyReport(models.Model):
	"""A user complaint about a site-created vacancy."""
	REASON_SCAM = 'scam'
	REASON_SPAM = 'spam'
	REASON_MISLEADING = 'misleading'
	REASON_SUSPICIOUS = 'suspicious_conditions'
	REASON_OTHER = 'other'
	REASON_CHOICES = [
		(REASON_SCAM, 'Подозрение на мошенничество'),
		(REASON_SPAM, 'Спам или реклама'),
		(REASON_MISLEADING, 'Некорректное описание вакансии'),
		(REASON_SUSPICIOUS, 'Подозрительные условия работы'),
		(REASON_OTHER, 'Другое'),
	]

	SELF_STATUS_NEW = 'new'
	SELF_STATUS_IN_WORK = 'in_work'
	SELF_STATUS_DONE = 'done'
	SELF_STATUS_CHOICES = [
		(SELF_STATUS_NEW, 'Новая'),
		(SELF_STATUS_IN_WORK, 'В работе'),
		(SELF_STATUS_DONE, 'Обработано'),
	]

	vacancy = models.ForeignKey('Vacancy', on_delete=models.CASCADE, related_name='reports', verbose_name='Вакансия')
	user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='vacancy_reports', verbose_name='Пользователь')
	reason_code = models.CharField('Причина', max_length=64, choices=REASON_CHOICES)
	reason_text = models.TextField('Комментарий', blank=True)
	self_status = models.CharField('Статус', max_length=16, choices=SELF_STATUS_CHOICES, default=SELF_STATUS_NEW)
	moderator_note = models.TextField('Заметка модератора', blank=True)
	reviewed_by = models.ForeignKey(
		'auth.User',
		null=True,
		blank=True,
		on_delete=models.SET_NULL,
		related_name='reviewed_vacancy_reports',
	)
	reviewed_at = models.DateTimeField('Проверено', null=True, blank=True)
	created_at = models.DateTimeField('Создано', auto_now_add=True)
	updated_at = models.DateTimeField('Обновлено', auto_now=True)

	class Meta:
		ordering = ('-created_at',)
		constraints = [
			models.UniqueConstraint(fields=['user', 'vacancy'], name='uniq_user_vacancy_report'),
		]
		verbose_name = 'Жалоба на вакансию'
		verbose_name_plural = 'Жалобы на вакансии'

	def __str__(self):
		return f"Report #{self.pk}: user={self.user_id} vacancy={self.vacancy_id}"


class VacancyModerationState(models.Model):
	"""Moderator's personal review state for a vacancy (card-level, not per report)."""
	STATUS_NEW = 'new'
	STATUS_IN_WORK = 'in_work'
	STATUS_WAITING = 'waiting'
	STATUS_CHOICES = [
		(STATUS_NEW, 'Новая'),
		(STATUS_IN_WORK, 'В работе'),
		(STATUS_WAITING, 'Ожидание'),
	]

	vacancy = models.ForeignKey('Vacancy', on_delete=models.CASCADE, related_name='moderation_states')
	moderator = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='vacancy_moderation_states')
	status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_NEW)
	note = models.TextField(blank=True)
	updated_at = models.DateTimeField(auto_now=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ('-updated_at',)
		constraints = [
			models.UniqueConstraint(fields=['vacancy', 'moderator'], name='uniq_vacancy_moderator_state'),
		]
		verbose_name = 'Состояние модерации вакансии'
		verbose_name_plural = 'Состояния модерации вакансий'

	def __str__(self):
		return f"VacancyState #{self.pk}: vacancy={self.vacancy_id} moderator={self.moderator_id}"


def _moderator_deletion_photo_path(instance, filename):
	return f"moderator_reports/{instance.report_id}/{filename}"


class ModeratorDeletionReport(models.Model):
	"""A record of a vacancy soft-deletion performed by a moderator.

	Snapshot fields preserve essential vacancy information so the report stays
	readable (and the PDF stays accurate) even if the underlying Vacancy row
	is later hard-deleted elsewhere.
	"""
	vacancy = models.ForeignKey(
		'Vacancy',
		on_delete=models.SET_NULL,
		null=True, blank=True,
		related_name='moderator_deletions',
	)
	moderator = models.ForeignKey(
		'auth.User',
		on_delete=models.SET_NULL,
		null=True, blank=True,
		related_name='moderator_deletion_reports',
	)
	manager = models.ForeignKey(
		'auth.User',
		on_delete=models.SET_NULL,
		null=True, blank=True,
		related_name='deleted_vacancy_reports',
		help_text='Менеджер, создавший удалённую вакансию',
	)
	reason = models.TextField('Причина удаления')

	# Snapshot fields captured at the moment of deletion.
	vacancy_title = models.CharField(max_length=255, blank=True)
	vacancy_company = models.CharField(max_length=255, blank=True)
	vacancy_description = models.TextField(blank=True)
	vacancy_external_id = models.CharField(max_length=64, blank=True)
	manager_full_name = models.CharField(max_length=255, blank=True)
	manager_email = models.CharField(max_length=255, blank=True)
	moderator_full_name = models.CharField(max_length=255, blank=True)
	moderator_email = models.CharField(max_length=255, blank=True)
	reports_count = models.PositiveIntegerField(default=0)
	dominant_reason_code = models.CharField(max_length=64, blank=True)
	dominant_reason_label = models.CharField(max_length=128, blank=True)

	# Restoration bookkeeping.
	is_restored = models.BooleanField(default=False, db_index=True)
	restored_by = models.ForeignKey(
		'auth.User',
		on_delete=models.SET_NULL,
		null=True, blank=True,
		related_name='restored_vacancy_reports',
	)
	restored_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ('-created_at',)
		verbose_name = 'Отчёт об удалении вакансии'
		verbose_name_plural = 'Отчёты об удалении вакансий'

	def __str__(self):
		return f"DeletionReport #{self.pk}: '{self.vacancy_title}' by {self.moderator_full_name}"


class ModeratorDeletionPhoto(models.Model):
	"""Photographic evidence attached to a moderator deletion report."""
	report = models.ForeignKey(
		ModeratorDeletionReport,
		on_delete=models.CASCADE,
		related_name='photos',
	)
	image = models.ImageField(upload_to=_moderator_deletion_photo_path)
	order = models.PositiveSmallIntegerField(default=0)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ('order', 'id')
		verbose_name = 'Фото-доказательство модератора'
		verbose_name_plural = 'Фото-доказательства модератора'

	def __str__(self):
		return f"Photo #{self.pk} for report {self.report_id}"
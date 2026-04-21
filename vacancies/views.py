import uuid
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Case, When, IntegerField
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.generic import ListView, DetailView

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

from vacancies.models import HhDictionaryItem, Vacancy, Employer
from .rating import compute_vacancy_rating
from accounts.models import FilterPreset



class VacancyListView(ListView):
	model = Vacancy
	template_name = "vacancies/vacancy_list.html"
	context_object_name = "vacancies"
	paginate_by = 20

	def dispatch(self, request, *args, **kwargs):
		# Admins go to their own panel
		if request.user.is_authenticated and request.user.is_superuser and hasattr(request.user, 'admin_profile'):
			from django.shortcuts import redirect
			return redirect('accounts:admin_panel')
		# Managers see their vacancies
		if request.user.is_authenticated and hasattr(request.user, 'manager'):
			from django.shortcuts import redirect
			return redirect('my-vacancies')
		return super().dispatch(request, *args, **kwargs)

	def setup(self, request, *args, **kwargs):
		super().setup(request, *args, **kwargs)
		self._filters = self._parse_filters()

	def _parse_filters(self):
		GET = self.request.GET
		formats_allowed = {c[0] for c in Vacancy.WorkFormat.choices}
		return {
			'q':                          GET.get('q', '').strip(),
			'q_scope':                    GET.get('q_scope', 'title'),
			'exclude_words':              GET.get('exclude_words', '').strip(),
			'region':                     GET.get('region', '').strip(),
			'selected_experiences':       GET.getlist('experience'),
			'employer':                   GET.get('employer', '').strip(),
			'skills':                     GET.get('skills', '').strip(),
			'only_with_salary':           GET.get('only_with_salary') == '1',
			'salary_min':                 GET.get('salary_min', '').strip(),
			'salary_max':                 GET.get('salary_max', '').strip(),
			'sort':                       GET.get('sort', ''),
			'selected_formats':           [v for v in GET.getlist('format') if v in formats_allowed],
			'selected_schedules':         GET.getlist('schedule'),
			'selected_employments':       GET.getlist('employment'),
			'selected_employment_forms':  GET.getlist('employment_form'),
			'selected_labels':            GET.getlist('label'),
			'published_since':            GET.get('published_since', ''),
			'per_page':                   GET.get('per_page', '20'),
			'metro':                      GET.get('metro', '').strip(),
			'metro_city_id':              GET.get('metro_city_id', '').strip(),
			'with_address':               GET.get('with_address') == '1',
			'accept_kids':                GET.get('accept_kids') == '1',
			'selected_payment_frequencies': GET.getlist('payment_frequency'),
			'selected_employee_types':    GET.getlist('employee_type'),
			'selected_contract_types':    GET.getlist('contract'),
			'selected_salary_periods':    GET.getlist('salary_period'),
			'selected_work_schedules':    GET.getlist('work_schedule'),
			'selected_shift_patterns':    GET.getlist('shift_pattern'),
			'selected_hours_per_day':     GET.getlist('hours_per_day'),
			'only_night_shifts':          GET.get('night_shifts') == '1',
			'with_contact_phone':         GET.get('with_contact_phone') == '1',
			'source':                     GET.get('source', '').strip(),
			'details_query':              GET.get('details_query', '').strip(),
		}

	def get_queryset(self):
		queryset = Vacancy.objects.visible_for_ru().filter(is_active=True)
		f = self._filters
		query = f['q']
		q_scope = f['q_scope']
		exclude_words = f['exclude_words']
		region = f['region']
		selected_experiences = f['selected_experiences']
		employer = f['employer']
		skills = f['skills']
		only_with_salary = f['only_with_salary']
		salary_min = f['salary_min']
		salary_max = f['salary_max']
		sort = f['sort']
		selected_formats = f['selected_formats']
		selected_schedules = f['selected_schedules']
		selected_employments = f['selected_employments']
		selected_employment_forms = f['selected_employment_forms']
		selected_labels = f['selected_labels']
		published_since = f['published_since']
		metro = f['metro']
		metro_city_id = f['metro_city_id']
		with_address = f['with_address']
		accept_kids = f['accept_kids']
		selected_payment_frequencies = f['selected_payment_frequencies']
		selected_employee_types = f['selected_employee_types']
		selected_contract_types = f['selected_contract_types']
		selected_salary_periods = f['selected_salary_periods']
		selected_work_schedules = f['selected_work_schedules']
		selected_shift_patterns = f['selected_shift_patterns']
		selected_hours_per_day = f['selected_hours_per_day']
		only_night_shifts = f['only_night_shifts']
		with_contact_phone = f['with_contact_phone']
		source = f['source']
		details_query = f['details_query']

		if query:
			if q_scope == "company":
				queryset = queryset.filter(company__icontains=query)
			elif q_scope == "description":
				queryset = queryset.filter(description__icontains=query)
			elif q_scope == "all":
				queryset = queryset.filter(
					Q(title__icontains=query) | Q(company__icontains=query) | Q(description__icontains=query)
				)
			else:
				queryset = queryset.filter(title__icontains=query)
		if exclude_words:
			for term in [t.strip() for t in exclude_words.split() if t.strip()]:
				queryset = queryset.exclude(Q(title__icontains=term) | Q(description__icontains=term))
		if region:
			queryset = queryset.filter(region__icontains=region)
		if employer:
			queryset = queryset.filter(company__icontains=employer)
		if selected_experiences:
			queryset = queryset.filter(experience_id__in=selected_experiences)
		if only_with_salary:
			queryset = queryset.filter(Q(salary_from__isnull=False) | Q(salary_to__isnull=False))
		if salary_min:
			try:
				val = int(salary_min)
				queryset = queryset.filter(salary_from__gte=val)
			except ValueError:
				pass
		if salary_max:
			try:
				val = int(salary_max)
				queryset = queryset.filter(salary_to__lte=val)
			except ValueError:
				pass
		if skills:
			for term in [t.strip() for t in skills.split(",") if t.strip()]:
				queryset = queryset.filter(
					Q(title__icontains=term)
					| Q(company__icontains=term)
					| Q(key_skills_text__icontains=term)
				)
		if selected_formats:
			format_filter = Q()
			if "remote" in selected_formats:
				format_filter |= Q(is_remote=True)
			if "hybrid" in selected_formats:
				format_filter |= Q(is_hybrid=True)
			if "onsite" in selected_formats:
				format_filter |= Q(is_onsite=True)
			queryset = queryset.filter(format_filter)
		if selected_schedules:
			queryset = queryset.filter(schedule_id__in=selected_schedules)
		if selected_employments:
			queryset = queryset.filter(employment_id__in=selected_employments)
		if selected_employment_forms:
			queryset = queryset.filter(employment_form_id__in=selected_employment_forms)
		if "internship" in selected_labels:
			queryset = queryset.filter(is_internship=True)
		if "temporary" in selected_labels:
			queryset = queryset.filter(accept_temporary=True)
		if "incomplete" in selected_labels:
			queryset = queryset.filter(accept_incomplete_resumes=True)
		if published_since:
			now = timezone.now()
			if published_since == "day":
				queryset = queryset.filter(published_at__gte=now - timedelta(days=1))
			elif published_since == "3days":
				queryset = queryset.filter(published_at__gte=now - timedelta(days=3))
			elif published_since == "week":
				queryset = queryset.filter(published_at__gte=now - timedelta(days=7))
			elif published_since == "month":
				queryset = queryset.filter(published_at__gte=now - timedelta(days=30))
		if metro:
			queryset = queryset.filter(metro_station_name__icontains=metro)
		if selected_payment_frequencies:
			queryset = queryset.filter(payment_frequency__in=selected_payment_frequencies)
		if selected_employee_types:
			queryset = queryset.filter(employee_type__in=selected_employee_types)
		if selected_contract_types:
			contract_q = Q()
			if "labor" in selected_contract_types:
				contract_q |= Q(contract_labor=True)
			if "gpc" in selected_contract_types:
				contract_q |= Q(contract_gpc=True)
			queryset = queryset.filter(contract_q)
		if selected_salary_periods:
			queryset = queryset.filter(salary_period__in=selected_salary_periods)
		if selected_work_schedules:
			queryset = queryset.filter(
				Q(work_schedule__in=selected_work_schedules)
				| Q(schedule_name__in=selected_work_schedules)
			)
		if selected_shift_patterns:
			pattern_q = Q()
			for pattern in selected_shift_patterns:
				clean = (pattern or "").strip()
				if not clean:
					continue
				pattern_q |= Q(work_schedule__icontains=clean)
				pattern_q |= Q(schedule_name__icontains=clean)
				pattern_q |= Q(description__icontains=clean)
				pattern_q |= Q(working_conditions_text__icontains=clean)
				pattern_q |= Q(requirements_text__icontains=clean)
			if pattern_q:
				queryset = queryset.filter(pattern_q)
		if selected_hours_per_day:
			hours_q = Q(hours_per_day__in=selected_hours_per_day)
			for value in selected_hours_per_day:
				value = (value or "").strip()
				if not value:
					continue
				hours_q |= Q(hours_per_day__icontains=value)
				hours_q |= Q(description__icontains=f"{value} час")
				hours_q |= Q(working_conditions_text__icontains=f"{value} час")
				hours_q |= Q(requirements_text__icontains=f"{value} час")
			queryset = queryset.filter(hours_q)
		if only_night_shifts:
			queryset = queryset.filter(has_night_shifts=True)
		if with_contact_phone:
			queryset = queryset.exclude(contact_phone="")
		if source == "hh":
			queryset = queryset.filter(url__icontains="hh.ru")
		elif source == "local":
			queryset = queryset.exclude(url__icontains="hh.ru")
		if details_query:
			queryset = queryset.filter(
				Q(requirements_text__icontains=details_query)
				| Q(working_conditions_text__icontains=details_query)
				| Q(benefits_text__icontains=details_query)
				| Q(description__icontains=details_query)
			)
		if with_address:
			queryset = queryset.exclude(work_address="")
		if accept_kids:
			queryset = queryset.filter(accept_kids=True)
		if sort == "salary":
			queryset = queryset.annotate(
				has_salary=Case(
					When(Q(salary_from__isnull=False) | Q(salary_to__isnull=False), then=1),
					default=0,
					output_field=IntegerField(),
				)
			).order_by("-has_salary", "-published_at")
		elif sort == "salary_asc":
			queryset = queryset.filter(
				Q(salary_from__isnull=False) | Q(salary_to__isnull=False)
			).order_by("salary_from", "salary_to", "-published_at")
		else:
			queryset = queryset.order_by("-published_at")
		return queryset.select_related('employer')

	def get_paginate_by(self, queryset):
		try:
			per_page = int(self.request.GET.get("per_page", ""))
			if per_page in (20, 50, 100):
				return per_page
		except (ValueError, TypeError):
			pass
		return self.paginate_by

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		f = self._filters
		query = f['q']
		q_scope = f['q_scope']
		exclude_words = f['exclude_words']
		region = f['region']
		selected_experiences = f['selected_experiences']
		employer = f['employer']
		skills = f['skills']
		only_with_salary = f['only_with_salary']
		salary_min = f['salary_min']
		salary_max = f['salary_max']
		sort = f['sort']
		selected_formats = f['selected_formats']
		selected_schedules = f['selected_schedules']
		selected_employments = f['selected_employments']
		selected_employment_forms = f['selected_employment_forms']
		selected_labels = f['selected_labels']
		published_since = f['published_since']
		per_page = f['per_page']
		metro = f['metro']
		metro_city_id = f['metro_city_id']
		with_address = f['with_address']
		accept_kids = f['accept_kids']
		selected_payment_frequencies = f['selected_payment_frequencies']
		selected_employee_types = f['selected_employee_types']
		selected_contract_types = f['selected_contract_types']
		selected_salary_periods = f['selected_salary_periods']
		selected_work_schedules = f['selected_work_schedules']
		selected_shift_patterns = f['selected_shift_patterns']
		selected_hours_per_day = f['selected_hours_per_day']
		only_night_shifts = f['only_night_shifts']
		with_contact_phone = f['with_contact_phone']
		source = f['source']
		details_query = f['details_query']

		params = []
		if query:
			params.append(("q", query))
		if q_scope and q_scope != "title":
			params.append(("q_scope", q_scope))
		if exclude_words:
			params.append(("exclude_words", exclude_words))
		if region:
			params.append(("region", region))
		if employer:
			params.append(("employer", employer))
		if skills:
			params.append(("skills", skills))
		if only_with_salary:
			params.append(("only_with_salary", "1"))
		if salary_min:
			params.append(("salary_min", salary_min))
		if salary_max:
			params.append(("salary_max", salary_max))
		if sort:
			params.append(("sort", sort))
		if published_since:
			params.append(("published_since", published_since))
		if per_page and per_page not in ("", "20"):
			params.append(("per_page", per_page))
		for exp in selected_experiences:
			params.append(("experience", exp))
		for fmt in selected_formats:
			params.append(("format", fmt))
		for sch in selected_schedules:
			params.append(("schedule", sch))
		for emp in selected_employments:
			params.append(("employment", emp))
		for ef in selected_employment_forms:
			params.append(("employment_form", ef))
		for lbl in selected_labels:
			params.append(("label", lbl))
		if metro:
			params.append(("metro", metro))
		if metro_city_id:
			params.append(("metro_city_id", metro_city_id))
		if with_address:
			params.append(("with_address", "1"))
		if accept_kids:
			params.append(("accept_kids", "1"))
		for pf in selected_payment_frequencies:
			params.append(("payment_frequency", pf))
		for et in selected_employee_types:
			params.append(("employee_type", et))
		for ct in selected_contract_types:
			params.append(("contract", ct))
		for sp in selected_salary_periods:
			params.append(("salary_period", sp))
		for ws in selected_work_schedules:
			params.append(("work_schedule", ws))
		for sp in selected_shift_patterns:
			params.append(("shift_pattern", sp))
		for hpd in selected_hours_per_day:
			params.append(("hours_per_day", hpd))
		if only_night_shifts:
			params.append(("night_shifts", "1"))
		if with_contact_phone:
			params.append(("with_contact_phone", "1"))
		if source:
			params.append(("source", source))
		if details_query:
			params.append(("details_query", details_query))

		has_advanced = bool(
			(q_scope and q_scope != "title")
			or exclude_words
			or selected_experiences
			or selected_employments
			or selected_employment_forms
			or selected_schedules
			or selected_formats
			or skills
			or employer
			or only_with_salary
			or salary_min
			or salary_max
			or metro
			or metro_city_id
			or with_address
			or accept_kids
			or selected_payment_frequencies
			or selected_labels
			or selected_employee_types
			or selected_contract_types
			or selected_salary_periods
			or selected_work_schedules
			or selected_shift_patterns
			or selected_hours_per_day
			or only_night_shifts
			or with_contact_phone
			or source
			or details_query
		)

		context.update(f)
		context["has_advanced_filters"] = has_advanced
		try:
			context["region_options"] = self._region_options()
		except Exception:
			context["region_options"] = []
		try:
			context["experience_options"] = self._experience_options()
		except Exception:
			context["experience_options"] = []
		try:
			context["schedule_options"] = self._schedule_options()
		except Exception:
			context["schedule_options"] = []
		try:
			context["employment_options"] = self._employment_options()
		except Exception:
			context["employment_options"] = []
		try:
			context["employment_form_options"] = self._employment_form_options()
		except Exception:
			context["employment_form_options"] = []
		try:
			context["employee_type_options"] = self._employee_type_options()
		except Exception:
			context["employee_type_options"] = []
		try:
			context["salary_period_options"] = self._salary_period_options()
		except Exception:
			context["salary_period_options"] = []
		try:
			context["work_schedule_options"] = self._work_schedule_options()
		except Exception:
			context["work_schedule_options"] = []
		context["shift_pattern_options"] = self._shift_pattern_options()
		try:
			context["hours_per_day_options"] = self._hours_per_day_options()
		except Exception:
			context["hours_per_day_options"] = []
		try:
			context["payment_frequency_options"] = self._payment_frequency_options()
		except Exception:
			context["payment_frequency_options"] = []
		context["filters_query"] = urlencode(params)

		if self.request.user.is_authenticated:
			context["user_presets"] = list(
				FilterPreset.objects.filter(user=self.request.user).values("id", "name", "filters")
			)
		else:
			context["user_presets"] = []

		return context

	def _region_options(self):
		return list(
			Vacancy.objects.exclude(region="")
			.values_list("region", flat=True)
			.distinct()
			.order_by("region")
		)

	def _dict_options(self, dictionary, id_field, name_field, exclude_ids=()):
		dict_rows = list(
			HhDictionaryItem.objects.filter(dictionary=dictionary)
			.exclude(item_id="")
			.exclude(item_id__in=exclude_ids)
			.values_list("item_id", "name")
			.distinct().order_by("name")
		)
		vac_rows = list(
			Vacancy.objects.exclude(**{id_field: ""})
			.exclude(**{name_field: ""})
			.values_list(id_field, name_field)
			.distinct().order_by(name_field)
		)
		return self._merge_id_name_options(dict_rows, vac_rows)

	def _experience_options(self):
		return self._dict_options("experience", "experience_id", "experience_name")

	def _schedule_options(self):
		return self._dict_options("schedule", "schedule_id", "schedule_name")

	def _employment_options(self):
		return self._dict_options("employment", "employment_id", "employment_name", exclude_ids=("probation",))

	def _employment_form_options(self):
		return self._dict_options("employment_form", "employment_form_id", "employment_form_name")

	def _merge_id_name_options(self, *iterables):
		merged = {}
		for rows in iterables:
			for item_id, name in rows:
				item_id = (item_id or "").strip()
				name = (name or "").strip()
				if item_id and name and item_id not in merged:
					merged[item_id] = name
		return sorted(merged.items(), key=lambda row: row[1].lower())

	def _field_value_options(self, field_name):
		return list(
			Vacancy.objects.exclude(**{field_name: ""})
			.values_list(field_name, flat=True)
			.distinct()
			.order_by(field_name)
		)

	def _employee_type_options(self):
		mapping = {
			"permanent": "Постоянная работа",
			"temporary": "Временная работа",
		}
		result = []
		for value in self._field_value_options("employee_type"):
			label = mapping.get(value, value.replace("_", " ").strip().capitalize())
			result.append((value, label))
		return result

	def _salary_period_options(self):
		mapping = {
			"month": "За месяц",
			"project": "За проект",
		}
		values = self._field_value_options("salary_period")
		if not values:
			values = ["month", "project"]
		result = []
		for value in values:
			label = mapping.get(value, value.replace("_", " ").strip().capitalize())
			result.append((value, label))
		return result

	def _work_schedule_options(self):
		work_schedule_values = self._field_value_options("work_schedule")
		schedule_name_values = list(
			Vacancy.objects.exclude(schedule_name="")
			.values_list("schedule_name", flat=True)
			.distinct()
			.order_by("schedule_name")
		)
		merged = []
		seen = set()
		for value in work_schedule_values + schedule_name_values:
			clean = (value or "").strip()
			if clean and clean not in seen:
				seen.add(clean)
				merged.append((clean, self._normalize_option_label(clean)))
		return merged

	def _normalize_option_label(self, value):
		clean = (value or "").strip()
		if not clean:
			return clean
		letters = [ch for ch in clean if ch.isalpha()]
		if letters:
			upper_ratio = sum(1 for ch in letters if ch.isupper()) / len(letters)
			if upper_ratio >= 0.7:
				return clean.lower().capitalize()
		return clean

	def _hours_per_day_options(self):
		defaults = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]
		values = set(defaults)
		values.update(self._field_value_options("hours_per_day"))

		result = []
		for value in sorted(values, key=lambda v: int(v) if str(v).isdigit() else 999):
			clean = (value or "").strip()
			if not clean:
				continue
			if clean.isdigit():
				n = int(clean)
				if n % 10 == 1 and n != 11:
					label = f"{n} час"
				elif n % 10 in (2, 3, 4) and n not in (12, 13, 14):
					label = f"{n} часа"
				else:
					label = f"{n} часов"
			else:
				label = clean
			result.append((clean, label))
		return result

	def _shift_pattern_options(self):
		return [
			("1/1", "1/1"),
			("2/2", "2/2"),
			("2/3", "2/3"),
			("3/3", "3/3"),
			("5/2", "5/2"),
			("6/1", "6/1"),
			("7/7", "7/7"),
			("15/15", "15/15"),
		]

	def _payment_frequency_options(self):
		mapping = {
			"daily": "Ежедневно",
			"weekly": "Раз в неделю",
			"biweekly": "Два раза в месяц",
			"monthly": "Раз в месяц",
			"project": "За проект",
		}
		values = self._field_value_options("payment_frequency")
		if not values:
			values = ["daily", "weekly", "biweekly", "monthly", "project"]
		result = []
		for value in values:
			label = mapping.get(value, value.replace("_", " ").strip().capitalize())
			result.append((value, label))
		return result


class VacancyDetailView(DetailView):
	model = Vacancy
	template_name = "vacancies/vacancy_detail.html"
	context_object_name = "vacancy"

	def get_object(self, queryset=None):
		external_id = self.kwargs.get('pk')
		return get_object_or_404(
			Vacancy.objects.select_related('employer'),
			external_id=external_id,
		)

	@staticmethod
	def _resolve_metro_coords(station_id):
		"""Look up (lat, lon) for a metro station from the cached HH JSON."""
		import json as _json, os as _os
		metro_path = _os.path.join(settings.BASE_DIR, 'tools', 'metro_hh.json')
		try:
			with open(metro_path, encoding='utf-8') as f:
				cities = _json.load(f)
		except (FileNotFoundError, ValueError):
			return '', ''
		sid = str(station_id)
		for city in cities:
			for line in city.get('lines', []):
				for st in line.get('stations', []):
					if str(st.get('id')) == sid:
						return str(st.get('lat', '')), str(st.get('lng', ''))
		return '', ''

	def get_context_data(self, **kwargs):
		ctx = super().get_context_data(**kwargs)
		vac = self.object

		# Pre-compute logo URL once (property can hit DB multiple times)
		ctx['employer_logo_url'] = vac.employer_logo_url

		# ── Inline description fetch (sync, short timeout) ──────────────
		if not vac.description and not vac.branded_description:
			hh_id = (vac.raw_json or {}).get('id') or vac.external_id
			if hh_id:
				try:
					import json as _json
					from urllib.request import Request, urlopen
					_url = f'https://api.hh.ru/vacancies/{hh_id}'
					_req = Request(_url, headers={'User-Agent': 'job-aggregator-diploma/1.0'})
					with urlopen(_req, timeout=3) as _resp:
						_data = _json.loads(_resp.read().decode('utf-8'))
					vac.description = _data.get('description', '') or ''
					vac.branded_description = _data.get('branded_description', '') or ''
					vac.key_skills_text = ', '.join(
						s.get('name', '') for s in (_data.get('key_skills') or []) if isinstance(s, dict)
					)
					vac.raw_json = {**(vac.raw_json or {}), **_data}
					vac.save(update_fields=['description', 'branded_description',
					                        'key_skills_text', 'raw_json'])
				except Exception:
					# Timeout or network error — fall back to Celery async
					try:
						from .tasks import fetch_vacancy_description
						fetch_vacancy_description.apply_async(args=[vac.id], priority=9)
					except Exception:
						pass

		# ── Server-side rating (skip AJAX when DB already has it) ────────
		from .rating import _positive
		emp = getattr(vac, 'employer', None)
		hh_val = _positive(getattr(emp, 'hh_rating', None)) if emp else None
		dj_val = _positive(getattr(emp, 'dreamjob_rating', None)) if emp else None

		# If no cached rating, try a quick synchronous scrape (≤2 s)
		if emp and not hh_val and not dj_val:
			try:
				from .management.commands.fetch_employer_details import (
					extract_rating_from_html, fetch_employer_page, _parse_rating,
				)
				from .dreamjob import (
					fetch_dreamjob_page,
					extract_rating_from_html as dj_extract,
				)
				from django.utils import timezone as _tz
				import socket as _socket
				_old_timeout = _socket.getdefaulttimeout()
				_socket.setdefaulttimeout(2)
				try:
					# HH employer page
					if not hh_val and emp.hh_id:
						try:
							_candidate, _dj_id = extract_rating_from_html(
								fetch_employer_page(f'https://hh.ru/employer/{emp.hh_id}'))
							_parsed = _parse_rating(_candidate)
							if _parsed:
								hh_val = _parsed
								emp.hh_rating = hh_val
								emp.rating_updated_at = _tz.now()
								emp.save(update_fields=['hh_rating', 'rating_updated_at'])
							# Try DreamJob via dj_id found on HH page
							if not dj_val and _dj_id:
								try:
									_dj_cand = dj_extract(fetch_dreamjob_page(
										f'https://dreamjob.ru/employers/{_dj_id}'))
									_dj_parsed = _parse_rating(_dj_cand)
									if _dj_parsed:
										dj_val = _dj_parsed
										emp.dreamjob_rating = dj_val
										emp.dreamjob_rating_updated_at = _tz.now()
										emp.save(update_fields=['dreamjob_rating', 'dreamjob_rating_updated_at'])
								except Exception:
									pass
						except Exception:
							pass
				finally:
					_socket.setdefaulttimeout(_old_timeout)
			except Exception:
				pass
			# If sync scrape failed, still dispatch Celery as background fallback
			if not hh_val and not dj_val and emp:
				try:
					from .tasks import fetch_employer_rating
					fetch_employer_rating.delay(emp.pk)
				except Exception:
					pass

		if hh_val and dj_val:
			ctx['prefetched_rating'] = f'{round((hh_val + dj_val) / 2, 2):.1f}'
		elif hh_val:
			ctx['prefetched_rating'] = f'{hh_val:.1f}'
		elif dj_val:
			ctx['prefetched_rating'] = f'{dj_val:.1f}'
		else:
			ctx['prefetched_rating'] = ''

		# ── Build branded_srcdoc (inline iframe content, saves HTTP trip) ─
		if vac.branded_description:
			_bd = vac.branded_description
			ctx['branded_srcdoc'] = (
				'<!doctype html><html><head><meta charset="utf-8">'
				'<meta name="viewport" content="width=device-width,initial-scale=1">'
				'<style>html,body{margin:0;padding:0;overflow:hidden;background:#faf8f5}'
				'body{font-family:Arial,sans-serif}img{max-width:100%;height:auto;display:block}'
				'video{max-width:100%}</style>'
				'<script>var _p=window.parent&&window.parent.postMessage?window.parent.postMessage.bind(window.parent):null;'
				f'function _nh(){{if(!_p)return;var h=document.body.scrollHeight;try{{_p({{type:"branded-height",pk:{vac.pk},height:h}},"*")}}catch(e){{}}}}</script>'
				'</head><body>'
				f'{_bd}'
				'<script>_nh();window.addEventListener("load",function(){_nh();setTimeout(_nh,300);setTimeout(_nh,800);setTimeout(_nh,2000)});'
				'if(typeof ResizeObserver!=="undefined"){new ResizeObserver(function(){_nh()}).observe(document.body)}</script>'
				'</body></html>'
			)

		# --- geo data ---
		lat = lon = None
		geocode_query = None
		raw_json = vac.raw_json if isinstance(vac.raw_json, dict) else {}

		# 1) Try to get coordinates directly from raw_json.address
		addr = raw_json.get('address') or {}
		if isinstance(addr, dict):
			try:
				_lat = addr.get('lat')
				_lng = addr.get('lng')
				if _lat and _lng:
					lat = float(_lat)
					lon = float(_lng)
			except (TypeError, ValueError):
				pass

		# 2) Build geocode query as fallback for client-side geocoding
		# build a user-facing display address (prefer address.raw/value/display)
		display_address = ''
		# prefer a complete raw string when available
		if isinstance(addr, dict) and addr.get('raw'):
			display_address = str(addr.get('raw')).strip()
		# otherwise assemble from structured parts: city, street, building, house/block, metro
		if not display_address and isinstance(addr, dict):
			parts = []
			city = addr.get('city') or (raw_json.get('area') and (raw_json.get('area').get('name') if isinstance(raw_json.get('area'), dict) else raw_json.get('area')))
			if city:
				parts.append(str(city).strip())
			street = addr.get('street')
			if street and str(street).strip():
				parts.append(str(street).strip())
			# include building/house/block if present
			for key in ('building','house','block'):
				val = addr.get(key)
				if val and str(val).strip():
					parts.append(str(val).strip())
			# include up to 3 nearby metro station names
			metro = addr.get('metro')
			if isinstance(metro, dict) and metro.get('station_name'):
				parts.append(str(metro.get('station_name')).strip())
			mstations = addr.get('metro_stations') or []
			if isinstance(mstations, list):
				count = 0
				for st in mstations:
					if isinstance(st, dict) and st.get('station_name'):
						parts.append(str(st.get('station_name')).strip())
						count += 1
						if count >= 3:
							break
			# fallback to vacancy.region if still empty
			if not parts and vac.region:
				parts.append(vac.region)
			# join unique parts preserving order
			seen = set()
			out = []
			for p in parts:
				if p and p not in seen:
					out.append(p)
					seen.add(p)
			if out:
				display_address = ', '.join(out)

		# if still empty, fall back to area+region
		if not display_address:
			area = raw_json.get('area')
			parts = []
			if isinstance(area, dict) and area.get('name'):
				parts.append(area.get('name'))
			elif isinstance(area, str) and area:
				parts.append(area)
			if vac.region and vac.region not in parts:
				parts.append(vac.region)
			if parts:
				display_address = ', '.join(parts)

		# prefer display_address for client-side geocoding
		if display_address:
			geocode_query = display_address

		# For site-created vacancies raw_json is empty — fall back to model fields
		if not lat and vac.lat:
			lat = vac.lat
		if not lon and vac.lon:
			lon = vac.lon
		# work_address is the explicit street address entered by the manager —
		# always prefer it over the region-only fallback derived from raw_json
		if vac.work_address:
			display_address = vac.work_address
			geocode_query = display_address

		# ── Server-side geocode via 2GIS (skip client-side fetch) ────────
		if not lat and geocode_query:
			try:
				import json as _json
				from urllib.request import Request, urlopen
				from urllib.parse import quote as _quote
				_geo_url = (
					'https://catalog.api.2gis.com/3.0/items/geocode?q='
					+ _quote(geocode_query)
					+ '&fields=items.point&key=' + settings.DGIS_API_KEY
				)
				_req = Request(_geo_url, headers={'User-Agent': 'job-aggregator-diploma/1.0'})
				with urlopen(_req, timeout=2) as _resp:
					_gdata = _json.loads(_resp.read().decode('utf-8'))
				_items = (_gdata.get('result') or {}).get('items') or []
				if _items and _items[0].get('point'):
					lat = float(_items[0]['point']['lat'])
					lon = float(_items[0]['point']['lon'])
			except Exception:
				pass  # Fall back to client-side geocoding

		ctx['map_lat'] = f'{lat:.6f}' if lat is not None else None
		ctx['map_lon'] = f'{lon:.6f}' if lon is not None else None
		ctx['geocode_query'] = geocode_query or ''
		ctx['display_address'] = display_address
		ctx['dgis_api_key'] = settings.DGIS_API_KEY

		# ── User location for pre-filling the route panel ───────────────
		user = self.request.user
		user_location_str = ''
		user_metro_lat = ''
		user_metro_lon = ''
		if user.is_authenticated and hasattr(user, 'applicant'):
			try:
				applicant = user.applicant
				if applicant.location_type == 'metro' and applicant.metro_station_name:
					city = applicant.city or ''
					name = applicant.metro_station_name
					user_location_str = ('ст. метро ' + name + ', ' + city).strip(', ') if city else 'ст. метро ' + name
					station_id = applicant.metro_station_id or ''
					if station_id:
						user_metro_lat, user_metro_lon = self._resolve_metro_coords(station_id)
				elif applicant.location_type == 'address' and applicant.address:
					user_location_str = applicant.address
			except Exception:
				pass
		ctx['user_location_str'] = user_location_str
		ctx['user_metro_lat'] = user_metro_lat
		ctx['user_metro_lon'] = user_metro_lon

		# ── Application status for logged-in users ──────────────────────
		is_applicant = user.is_authenticated and hasattr(user, 'applicant')
		ctx['is_applicant'] = is_applicant
		ctx['user_application'] = None
		if is_applicant:
			from accounts.models import Application
			ctx['user_application'] = Application.objects.filter(
				vacancy=vac, applicant=user
			).first()
		ctx['user_is_creator'] = user.is_authenticated and vac.created_by_id == user.pk
		if user.is_authenticated and hasattr(user, 'manager'):
			ctx['application_count'] = vac.applications.count()
			ctx['is_owner'] = vac.created_by_id == user.pk
		else:
			ctx['application_count'] = 0
			ctx['is_owner'] = False

		# Track view and bookmark state for logged-in users
		if user.is_authenticated:
			from vacancies.models import VacancyView, Bookmark
			vv, created = VacancyView.objects.get_or_create(user=user, vacancy=vac)
			if not created:
				vv.save(update_fields=['viewed_at'])  # auto_now refreshes timestamp
			ctx['is_bookmarked'] = Bookmark.objects.filter(user=user, vacancy=vac).exists()
		else:
			ctx['is_bookmarked'] = False

		return ctx


@swagger_auto_schema(method='get', operation_summary="Рейтинг работодателя", tags=['vacancies'])
@api_view(['GET'])
@permission_classes([AllowAny])
def employer_rating_api(request, hh_id):
	"""Lazy-load employer rating by hh_id.

	Returns cached DB values instantly.  If no rating is cached yet,
	dispatches a Celery task for background scraping and returns
	{rating: null, pending: true} so the client can poll again shortly.
	"""
	from .rating import _positive

	try:
		emp = Employer.objects.get(hh_id=str(hh_id))
	except Employer.DoesNotExist:
		return JsonResponse({'rating': None, 'source': None})

	hh_val = _positive(emp.hh_rating)
	dj_val = _positive(emp.dreamjob_rating)

	if hh_val and dj_val:
		avg = round((hh_val + dj_val) / 2, 2)
		resp = JsonResponse({'rating': f'{avg:.1f}', 'source': 'hh+dreamjob',
		                     'hh': f'{hh_val:.1f}', 'dj': f'{dj_val:.1f}'})
		resp['Cache-Control'] = 'public, max-age=3600'
		return resp
	if hh_val:
		resp = JsonResponse({'rating': f'{hh_val:.1f}', 'source': 'hh'})
		resp['Cache-Control'] = 'public, max-age=3600'
		return resp
	if dj_val:
		resp = JsonResponse({'rating': f'{dj_val:.1f}', 'source': 'dreamjob'})
		resp['Cache-Control'] = 'public, max-age=3600'
		return resp

	# No cached rating — dispatch background scraping, tell client to retry
	from django.core.cache import cache
	cache_key = f'rating_inflight_{emp.pk}'
	if not cache.get(cache_key):
		cache.set(cache_key, 1, timeout=300)
		from .tasks import fetch_employer_rating
		fetch_employer_rating.delay(emp.pk)

	return JsonResponse({'rating': None, 'source': None, 'pending': True})

from django.http import HttpResponse
from django.views.decorators.clickjacking import xframe_options_exempt


@xframe_options_exempt
def vacancy_branded_frame_view(request, pk):
	"""Serves branded_description as a self-contained HTML page for iframe embedding.

	Using an iframe is the only way to fully isolate the employer's <style> blocks
	from the parent page, preventing hh.ru template rules from leaking globally.
	"""
	try:
		v = Vacancy.objects.only('branded_description', 'description').get(pk=pk)
	except Vacancy.DoesNotExist:
		return HttpResponse(status=404)

	content = v.branded_description or (v.description if v.description != '__unavailable__' else '') or ''

	# The iframe posts its scrollHeight to the parent so it can be resized.
	html = f'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  html, body {{ margin: 0; padding: 0; overflow: hidden; background: #faf8f5; }}
  body {{ font-family: Arial, sans-serif; background: #faf8f5; }}
  img {{ max-width: 100%; height: auto; display: block; }}
  video {{ max-width: 100%; }}
</style>
<script>
  /* Save postMessage reference BEFORE employer scripts can override it */
  var _pmRef = window.parent && window.parent.postMessage
               ? window.parent.postMessage.bind(window.parent)
               : null;
  function notifyHeight() {{
    if (!_pmRef) return;
    document.body.style.overflow = 'hidden';
    var h = document.body.scrollHeight || document.documentElement.scrollHeight;
    try {{ _pmRef({{ type: "branded-height", pk: {pk}, height: h }}, "*"); }} catch(e) {{}}
  }}
</script>
</head>
<body>
{content}
<script>
  // Fire immediately and on full load
  notifyHeight();
  window.addEventListener("load", function() {{
    notifyHeight();
    setTimeout(notifyHeight, 300);
    setTimeout(notifyHeight, 800);
    setTimeout(notifyHeight, 2000);
  }});
  // ResizeObserver catches layout shifts from lazy images, deferred scripts, etc.
  if (typeof ResizeObserver !== 'undefined') {{
    var ro = new ResizeObserver(function() {{ notifyHeight(); }});
    ro.observe(document.body);
  }}
  // MutationObserver fallback
  if (typeof MutationObserver !== 'undefined') {{
    var mo = new MutationObserver(function() {{ notifyHeight(); }});
    mo.observe(document.body, {{ childList: true, subtree: true, attributes: true }});
  }}
</script>
</body>
</html>'''
	return HttpResponse(html, content_type='text/html; charset=utf-8')


@swagger_auto_schema(method='get', operation_summary="Получить описание вакансии", tags=['api'])
@api_view(['GET'])
@permission_classes([AllowAny])
def vacancy_description_api(request, pk):
	try:
		v = Vacancy.objects.only('id', 'description', 'branded_description').get(pk=pk)
	except Vacancy.DoesNotExist:
		return JsonResponse({'error': 'not found'}, status=404)

	if not v.description and not v.branded_description:
		# Fire Celery task as fallback (view already tried sync fetch)
		try:
			from .tasks import fetch_vacancy_description
			fetch_vacancy_description.apply_async(args=[v.id], priority=9)
		except Exception:
			pass  # Celery may not be running
		return JsonResponse({'pending': True, 'description': '', 'branded': ''})

	if v.description == '__unavailable__':
		# HH returned 403/404 — vacancy is archived or restricted
		return JsonResponse({'pending': False, 'unavailable': True,
		                     'description': '', 'branded': ''})

	return JsonResponse({
		'pending': False,
		'description': v.description,
		'branded': v.branded_description,
	})


# ───────────────────────── Employer vacancy management ─────────────────────────

EXPERIENCE_CHOICES = [
	('noExperience', 'Нет опыта'),
	('between1And3', '1–3 года'),
	('between3And6', '3–6 лет'),
	('moreThan6', 'От 6 лет'),
]

PAYMENT_FREQ_CHOICES = [
	('daily',       'Ежедневно'),
	('weekly',      'Раз в неделю'),
	('biweekly',    'Два раза в месяц'),
	('monthly',     'Раз в месяц'),
	('project',     'За проект'),
]

SCHEDULE_CHOICES = [
	('fullDay',    'Полный день'),
	('shift',      'Сменный'),
	('flexible',   'Гибкий'),
	('remote',     'Удалённая работа'),
	('flyInFlyOut','Вахтовый'),
]

EMPLOYMENT_CHOICES = [
	('full',       'Полная занятость'),
	('part',       'Частичная занятость'),
	('shift',      'Вахта'),
	('project',    'Проектная / временная'),
	('volunteer',  'Волонтёрство'),
	('probation',  'Стажировка'),
]

CURRENCY_CHOICES = [
	('RUR', '₽ Рубль'),
	('USD', '$ Доллар'),
	('EUR', '€ Евро'),
]


def _safe_coord(val):
	try:
		f = float(val or 0)
		return f if f != 0.0 else None
	except (ValueError, TypeError):
		return None


def _parse_vacancy_post(post):
	"""Extract and validate vacancy fields from POST. Returns (data_dict, errors_dict)."""
	errors = {}
	title   = post.get('title', '').strip()
	company = post.get('company', '').strip()
	region  = post.get('region', '').strip()
	if not title:   errors['title']   = 'Введите название вакансии'
	if not company: errors['company'] = 'Введите название компании'
	if not region:  errors['region']  = 'Укажите город или регион'

	salary_from = salary_to = None
	sf_raw = post.get('salary_from', '').strip()
	st_raw = post.get('salary_to',   '').strip()
	if sf_raw:
		try:    salary_from = int(sf_raw)
		except ValueError: errors['salary_from'] = 'Некорректное число'
	if st_raw:
		try:    salary_to = int(st_raw)
		except ValueError: errors['salary_to'] = 'Некорректное число'
	if salary_from is not None and salary_to is not None and salary_from > salary_to:
		errors['salary_to'] = 'Максимальная зарплата должна быть не меньше минимальной'

	experience_id   = post.get('experience_id', '').strip()
	schedule_id     = post.get('schedule_id', '').strip()
	employment_id   = post.get('employment_id', '').strip()
	salary_currency = post.get('salary_currency', 'RUR').strip()

	# Validate choice fields — reject values not in known sets
	_valid_exp = {c[0] for c in EXPERIENCE_CHOICES}
	_valid_sch = {c[0] for c in SCHEDULE_CHOICES}
	_valid_emp = {c[0] for c in EMPLOYMENT_CHOICES}
	_valid_cur = {c[0] for c in CURRENCY_CHOICES}
	_valid_per = {c[0] for c in PAYMENT_FREQ_CHOICES}
	_valid_sp  = {'month', 'hour', 'project', ''}
	if experience_id and experience_id not in _valid_exp:
		experience_id = ''
	if schedule_id and schedule_id not in _valid_sch:
		schedule_id = ''
	if employment_id and employment_id not in _valid_emp:
		employment_id = ''
	if salary_currency not in _valid_cur:
		salary_currency = 'RUR'

	is_remote = 'is_remote' in post
	is_hybrid = 'is_hybrid' in post
	is_onsite = 'is_onsite' in post
	if not is_remote and not is_hybrid and not is_onsite:
		is_onsite = True  # default

	if is_hybrid:
		work_format = Vacancy.WorkFormat.HYBRID
	elif is_remote and not is_onsite:
		work_format = Vacancy.WorkFormat.REMOTE
	else:
		work_format = Vacancy.WorkFormat.ONSITE

	data = dict(
		title=title, company=company, region=region,
		description=post.get('description', '').strip(),
		key_skills_text=post.get('key_skills', '').strip(),
		experience_id=experience_id,
		experience_name=dict(EXPERIENCE_CHOICES).get(experience_id, ''),
		schedule_id=schedule_id,
		schedule_name=dict(SCHEDULE_CHOICES).get(schedule_id, ''),
		employment_id=employment_id,
		employment_name=dict(EMPLOYMENT_CHOICES).get(employment_id, ''),
		salary_from=salary_from,
		salary_to=salary_to,
		salary_currency=salary_currency,
		work_format=work_format,
		is_remote=is_remote,
		is_hybrid=is_hybrid,
		is_onsite=is_onsite,
		accept_incomplete_resumes='accept_incomplete_resumes' in post,
		accept_temporary='accept_temporary' in post,
		is_internship='is_internship' in post,
		# Extended employer-form fields
		employee_type=post.get('employee_type', '').strip(),
		contract_labor='contract_labor' in post,
		contract_gpc='contract_gpc' in post,
		work_schedule=post.get('work_schedule', '').strip(),
		hours_per_day=post.get('hours_per_day', '').strip(),
		has_night_shifts='has_night_shifts' in post,
		salary_gross=post.get('salary_gross', 'true') == 'true',
		salary_period=post.get('salary_period', 'month').strip() if post.get('salary_period', 'month').strip() in _valid_sp else 'month',
		payment_frequency=post.get('payment_frequency', '').strip() if post.get('payment_frequency', '').strip() in _valid_per | {''} else '',
		work_address=post.get('address', post.get('work_address', '')).strip(),
		hide_address='hide_address' in post,
		address_comment=post.get('address_comment', '').strip(),
		# Location & contact
		lat=_safe_coord(post.get('lat')),
		lon=_safe_coord(post.get('lon')),
		contact_phone=post.get('contact_phone', '').strip(),
	)
	# Validate contact_phone if provided
	_cp = data.get('contact_phone', '')
	if _cp:
		import re as _re
		_cp_d = _re.sub(r'\D', '', _cp)
		if _cp_d.startswith('8'): _cp_d = '7' + _cp_d[1:]
		if not _re.match(r'^7[0-9]{10}$', _cp_d):
			errors['contact_phone'] = 'Введите номер в формате +7 (XXX) XXX-XX-XX'
	data.update(dict(
		metro_station_name=post.get('metro_station_name', '').strip(),
		metro_line_color=post.get('metro_line_color', '').strip(),
		metro_line_name=post.get('metro_line_name', '').strip(),
		benefits_text=post.get('benefits_text', '').strip(),
		requirements_text=post.get('requirements_text', '').strip(),
		working_conditions_text=post.get('working_conditions_text', '').strip(),
		metro_city_id=post.get('metro_city_id', '').strip(),
	))
	return data, errors


def _form_ctx(extra=None):
	"""Base context for the create/edit form."""
	from django.conf import settings as _s
	ctx = dict(
		experience_choices=EXPERIENCE_CHOICES,
		schedule_choices=SCHEDULE_CHOICES,
		employment_choices=EMPLOYMENT_CHOICES,
		currency_choices=CURRENCY_CHOICES,
		payment_freq_choices=PAYMENT_FREQ_CHOICES,
		dgis_api_key=getattr(_s, 'DGIS_API_KEY', ''),
	)
	if extra:
		ctx.update(extra)
	return ctx


@login_required
def vacancy_create(request):
	if not hasattr(request.user, 'manager'):
		return redirect('vacancy-list')

	errors = {}
	form_data = {'salary_currency': 'RUR', 'company': request.user.manager.company}

	if request.method == 'POST':
		form_data = request.POST
		data, errors = _parse_vacancy_post(request.POST)
		if not errors:
			ext_id = f"site-{uuid.uuid4().hex}"
			vac = Vacancy.objects.create(
				external_id=ext_id,
				country='Россия',
				published_at=timezone.now(),
				created_by=request.user,
				url='',
				**data,
			)
			vac.url = request.build_absolute_uri(f'/{vac.external_id}/')
			vac.save(update_fields=['url'])
			return redirect('vacancy-detail', pk=vac.external_id)

	return render(request, 'vacancies/vacancy_create.html', _form_ctx({
		'form_data': form_data,
		'errors': errors,
		'editing': False,
		'manager': request.user.manager,
	}))


@login_required
def vacancy_edit(request, pk):
	vac = get_object_or_404(Vacancy, pk=pk)
	if not hasattr(request.user, 'manager') or vac.created_by != request.user:
		return redirect('vacancy-detail', pk=vac.external_id)

	errors = {}
	# Pre-fill from existing vacancy
	form_data = dict(
		title=vac.title, company=vac.company, region=vac.region,
		description=vac.description, key_skills=vac.key_skills_text,
		experience_id=vac.experience_id,
		schedule_id=vac.schedule_id,
		employment_id=vac.employment_id,
		salary_from=vac.salary_from or '', salary_to=vac.salary_to or '',
		salary_currency=vac.salary_currency or 'RUR',
		is_remote='on' if vac.is_remote else '',
		is_hybrid='on' if vac.is_hybrid else '',
		is_onsite='on' if vac.is_onsite else '',
		accept_incomplete_resumes='on' if vac.accept_incomplete_resumes else '',
		accept_temporary='on' if vac.accept_temporary else '',
		is_internship='on' if vac.is_internship else '',
		employee_type=vac.employee_type,
		contract_labor='on' if vac.contract_labor else '',
		contract_gpc='on' if vac.contract_gpc else '',
		work_schedule=vac.work_schedule,
		hours_per_day=vac.hours_per_day,
		has_night_shifts='on' if vac.has_night_shifts else '',
		salary_gross='true' if vac.salary_gross else 'false',
		salary_period=vac.salary_period or 'month',
		payment_frequency=vac.payment_frequency,
		work_address=vac.work_address,
		hide_address='on' if vac.hide_address else '',
		address_comment=vac.address_comment,
		# Form fields for new sections (template uses name="address", not work_address)
		address=vac.work_address,
		lat=vac.lat or '',
		lon=vac.lon or '',
		contact_phone=vac.contact_phone,
		metro_station_name=vac.metro_station_name,
		metro_city_id=vac.metro_city_id,
		metro_line_color=vac.metro_line_color or '#e42313',
		metro_line_name=vac.metro_line_name,
		benefits_text=vac.benefits_text,
		requirements_text=vac.requirements_text,
		working_conditions_text=vac.working_conditions_text,
	)

	if request.method == 'POST':
		form_data = request.POST
		data, errors = _parse_vacancy_post(request.POST)
		# Preserve hide_address: no toggle exists in the form UI
		data['hide_address'] = vac.hide_address
		if not errors:
			for k, v in data.items():
				setattr(vac, k, v)
			vac.save()
			return redirect('vacancy-detail', pk=vac.external_id)

	return render(request, 'vacancies/vacancy_create.html', _form_ctx({
		'form_data': form_data,
		'errors': errors,
		'editing': True,
		'vacancy': vac,
		'manager': request.user.manager,
	}))


@login_required
def vacancy_delete(request, pk):
	vac = get_object_or_404(Vacancy, pk=pk)
	if hasattr(request.user, 'manager') and vac.created_by == request.user:
		if request.method == 'POST':
			vac.delete()
			return redirect('my-vacancies')
	return redirect('vacancy-detail', pk=vac.external_id)


@swagger_auto_schema(method='patch', operation_summary="Архивировать / восстановить вакансию", tags=['vacancies'])
@api_view(['PATCH'])
@login_required
def api_vacancy_toggle_active(request, pk):
    """Toggle the is_active flag for a manager's own vacancy."""
    vac = get_object_or_404(Vacancy, pk=pk)
    if not hasattr(request.user, 'manager') or vac.created_by != request.user:
        return JsonResponse({'error': 'forbidden'}, status=403)
    vac.is_active = not vac.is_active
    vac.save(update_fields=['is_active'])
    return JsonResponse({'ok': True, 'is_active': vac.is_active})


@login_required
def my_vacancies(request):
	if not hasattr(request.user, 'manager'):
		return redirect('vacancy-list')
	vacancies = Vacancy.objects.filter(created_by=request.user).order_by('-created_at')
	return render(request, 'vacancies/my_vacancies.html', {
		'vacancies': vacancies,
		'manager': request.user.manager,
	})


def custom_404(request, exception=None):
    return render(request, '404.html', status=404)


def custom_403(request, exception=None):
	return render(request, '403.html', status=403)
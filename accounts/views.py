import csv
import json
import os
import re
import uuid
from datetime import date
from django.db.models import Q
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.urls import reverse
from urllib.parse import urlencode
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.core.mail import send_mail
from django.conf import settings as django_settings

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.permissions import IsAuthenticated
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.http.request import RawPostDataException

from .models import Applicant, Manager, Administrator, Education, ExtraEducation, WorkExperience, Chat, Message, Application, FilterPreset, CalendarNote, Interview, UserUiPreference, ApiActionLog
from .telegram import send_hello_async, get_bot_username, resolve_chat_id_by_token, notify_new_chat_message


# ──────────────────────────── Admin helpers ────────────────────────────────

def is_admin_user(user):
    """Returns True only if the user is a superuser AND has an Administrator profile."""
    return (
        user.is_authenticated
        and user.is_superuser
        and hasattr(user, 'admin_profile')
    )


def admin_required(view_func):
    """Decorator: allows access only to verified administrators."""
    from functools import wraps
    from django.http import HttpResponseForbidden

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path(), login_url='/accounts/login/')
        if not is_admin_user(request.user):
            return HttpResponseForbidden(
                '<h2>403 — Доступ запрещён</h2>'
                '<p>Эта страница доступна только администраторам системы.</p>'
            )
        return view_func(request, *args, **kwargs)
    return wrapper


def _resolve_actor_role(user):
    """Map authenticated user to a stable actor role for API audit logs."""
    if not user or not getattr(user, 'is_authenticated', False):
        return 'system'
    if is_admin_user(user):
        return 'admin'
    if hasattr(user, 'manager'):
        return 'manager'
    if hasattr(user, 'applicant'):
        return 'applicant'
    return 'user'


def _json_safe(data):
    """Ensure value is JSON-serializable for JSONField storage."""
    if data is None:
        return {}
    try:
        return json.loads(json.dumps(data, default=str, ensure_ascii=False))
    except Exception:
        return {'raw': str(data)}


def _log_api_action(request, action, before=None, after=None, *, success=True, status_code=None, meta=None, endpoint=None):
    """Write one API action log row. Logging failures must not break endpoint flow."""
    try:
        ApiActionLog.objects.create(
            user=request.user if getattr(request.user, 'is_authenticated', False) else None,
            actor_role=_resolve_actor_role(getattr(request, 'user', None)),
            method=(getattr(request, 'method', '') or '').upper()[:10],
            path=(getattr(request, 'path', '') or '')[:255],
            endpoint=(endpoint or '')[:120],
            action=(action or 'api_action')[:120],
            success=bool(success),
            status_code=status_code,
            before_data=_json_safe(before),
            after_data=_json_safe(after),
            meta=_json_safe(meta),
        )
    except Exception:
        pass


def _humanize_payload(data):
    """Render compact human-readable payload text for before/after columns."""
    if not data:
        return '—'
    if isinstance(data, dict):
        chunks = []
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                value_txt = json.dumps(value, ensure_ascii=False)
            else:
                value_txt = str(value)
            chunks.append(f'{key}: {value_txt}')
        return '\n'.join(chunks) if chunks else '—'
    if isinstance(data, list):
        return ', '.join(str(v) for v in data) if data else '—'
    return str(data)


# ──────────────────────────── Page views (HTML) ────────────────────────────

@ensure_csrf_cookie
def register_page(request):
    bot_username = get_bot_username()
    return render(request, 'accounts/register.html', {
        'telegram_bot_username': bot_username,
        'today': date.today().isoformat(),
    })


@ensure_csrf_cookie
def manager_register_page(request):
    return render(request, 'accounts/register_manager.html')


def message_rules(request):
    return render(request, 'accounts/message_rules.html')


def terms(request):
    return render(request, 'accounts/terms.html')


@ensure_csrf_cookie
def login_page(request):
    return render(request, 'accounts/login.html')


@login_required
@ensure_csrf_cookie
def profile_page(request):
    if is_admin_user(request.user):
        return redirect('accounts:admin_panel')
    return render(request, 'accounts/profile.html')


@login_required
def logout_view(request):
    auth_logout(request)
    return redirect('/')


# ──────────────────────────── API views (JSON) ─────────────────────────────

@swagger_auto_schema(method='post', operation_summary="Регистрация нового пользователя", tags=['accounts'])
@api_view(['POST'])
@permission_classes([AllowAny])
def api_register(request):
    def _register_fail(code, *, status=400, extra=None):
        payload = {'error': code}
        if extra:
            payload.update(extra)
        _log_api_action(
            request,
            action='register_applicant',
            before={'username': username, 'email': email, 'telegram': telegram},
            after=payload,
            success=False,
            status_code=status,
            endpoint='api_register',
        )
        return JsonResponse({'error': code}, status=status)

    data = None
    # Prefer DRF-parsed data (handles JSON and form-data)
    try:
        data = getattr(request, 'data', None)
    except Exception:
        data = None

    # If no parsed data, try to read raw JSON body safely
    if not data:
        try:
            raw = None
            try:
                raw = request.body
            except RawPostDataException:
                raw = None
            if raw:
                try:
                    data = json.loads(raw.decode('utf-8'))
                except Exception:
                    data = None
        except Exception:
            data = None

    # Finally, fallback to form-encoded POST
    if not data:
        try:
            if hasattr(request, 'POST') and request.POST:
                data = dict(request.POST)
                for k, v in list(data.items()):
                    if isinstance(v, list) and len(v) == 1:
                        data[k] = v[0]
            else:
                data = {}
        except Exception:
            data = {}

    last_name = (data.get('last_name') or '').strip()
    first_name = (data.get('first_name') or '').strip()
    patronymic = (data.get('patronymic') or '').strip()
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()
    telegram = (data.get('telegram') or '').strip()
    phone = (data.get('phone') or '').strip()
    gender = (data.get('gender') or '').strip().upper()
    city = (data.get('city') or '').strip()
    birth_date_raw = (data.get('birth_date') or '').strip()
    citizenship = (data.get('citizenship') or '').strip().upper()
    consent_email = bool(data.get('consent_email'))
    consent_telegram = bool(data.get('consent_telegram'))
    password = data.get('password')

    if not last_name or not first_name or not username or not email or not telegram \
            or not phone or not gender or not city or not birth_date_raw \
            or not citizenship or not password:
        return _register_fail('missing_fields')

    if not telegram.startswith('@'):
        return _register_fail('invalid_telegram_format')

    # Phone: must be Russian format — 11 digits starting with 7 or 8
    phone_digits = re.sub(r'\D', '', phone)
    if phone_digits.startswith('8'):
        phone_digits = '7' + phone_digits[1:]
    if not re.match(r'^7[0-9]{10}$', phone_digits):
        return _register_fail('invalid_phone')

    # Gender
    if gender not in ('M', 'F'):
        return _register_fail('invalid_gender')

    # City
    if len(city) < 2 or len(city) > 100:
        return _register_fail('invalid_city')

    # Birth date
    try:
        birth_date = date.fromisoformat(birth_date_raw)  # expects YYYY-MM-DD
    except ValueError:
        return _register_fail('invalid_birth_date')
    today = date.today()
    age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    if age < 14:
        return _register_fail('too_young')
    if age > 100:
        return _register_fail('invalid_birth_date')

    # Citizenship
    VALID_CITIZENSHIPS = {'RU', 'BY', 'KZ', 'KG', 'AM', 'TJ', 'UZ', 'UA', 'MD', 'AZ', 'TM'}
    if citizenship not in VALID_CITIZENSHIPS:
        return _register_fail('invalid_citizenship')

    if Applicant.objects.filter(telegram__iexact=telegram).exists() or \
       Manager.objects.filter(telegram__iexact=telegram).exists():
        return _register_fail('telegram_exists')

    # username uniqueness and format check
    if not username:
        return _register_fail('missing_fields')
    if len(username) < 3 or len(username) > 30:
        return _register_fail('invalid_username')
    if not re.match(r'^[A-Za-z0-9_.-]+$', username):
        return _register_fail('invalid_username_format')
    if User.objects.filter(username__iexact=username).exists():
        return _register_fail('username_exists')

    if User.objects.filter(email=email).exists():
        return _register_fail('email_exists')

    user = User.objects.create_user(username=username, email=email, password=password,
                                    first_name=first_name, last_name=last_name)
    token = uuid.uuid4().hex

    applicant = Applicant.objects.create(
        user=user, patronymic=patronymic, telegram=telegram,
        consent_email=consent_email, consent_telegram=consent_telegram,
        telegram_start_token=token,
        phone=phone, gender=gender, city=city,
        birth_date=birth_date, citizenship=citizenship,
        skills=data.get('skills') if isinstance(data.get('skills'), list) else [],
    )

    # Education (optional list of dicts)
    edu_list = data.get('education') or []
    if isinstance(edu_list, list):
        VALID_EDU_LEVELS = {c[0] for c in Education.LEVEL_CHOICES}
        for i, entry in enumerate(edu_list):
            if not isinstance(entry, dict):
                continue
            level = (entry.get('level') or '').strip()
            institution = (entry.get('institution') or '').strip()
            if not level or level not in VALID_EDU_LEVELS or not institution:
                continue
            try:
                grad_year = int(entry['graduation_year']) if entry.get('graduation_year') else None
            except (ValueError, TypeError):
                grad_year = None
            Education.objects.create(
                applicant=applicant,
                level=level,
                institution=institution,
                graduation_year=grad_year,
                faculty=(entry.get('faculty') or '').strip(),
                specialization=(entry.get('specialization') or '').strip(),
                order=i,
            )

    # Work experience (optional list of dicts)
    work_list = data.get('work_experience') or []
    if isinstance(work_list, list):
        for i, entry in enumerate(work_list):
            if not isinstance(entry, dict):
                continue
            company = (entry.get('company') or '').strip()
            position = (entry.get('position') or '').strip()
            if not company or not position:
                continue
            def _safe_int(val):
                try:
                    return int(val) if val else None
                except (ValueError, TypeError):
                    return None
            WorkExperience.objects.create(
                applicant=applicant,
                company=company,
                position=position,
                start_month=_safe_int(entry.get('start_month')),
                start_year=_safe_int(entry.get('start_year')),
                end_month=_safe_int(entry.get('end_month')),
                end_year=_safe_int(entry.get('end_year')), # Can be null
                is_current=bool(entry.get('is_current')),
                responsibilities=(entry.get('responsibilities') or '').strip(),
                order=i,
            )

    _log_api_action(
        request,
        action='register_applicant',
        before={'username': username, 'email': email, 'telegram': telegram},
        after={'created_user_id': user.pk, 'created_applicant_id': applicant.pk},
        success=True,
        status_code=200,
        endpoint='api_register',
    )
    return JsonResponse({'ok': True, 'start_token': token})


@swagger_auto_schema(method='post', operation_summary="Регистрация менеджера", tags=['accounts'])
@api_view(['POST'])
@permission_classes([AllowAny])
def api_register_manager(request):

    def _register_manager_fail(code, *, status=400):
        _log_api_action(
            request,
            action='register_manager',
            before={'username': username, 'email': email, 'telegram': telegram},
            after={'error': code},
            success=False,
            status_code=status,
            endpoint='api_register_manager',
        )
        return JsonResponse({'error': code}, status=status)

    try:
        data = getattr(request, 'data', None) or {}
    except Exception:
        data = {}

    last_name  = (data.get('last_name')  or '').strip()
    first_name = (data.get('first_name') or '').strip()
    patronymic = (data.get('patronymic') or '').strip()
    username   = (data.get('username')   or '').strip()
    email      = (data.get('email')      or '').strip().lower()
    telegram   = (data.get('telegram')   or '').strip()
    company    = (data.get('company')    or '').strip()
    phone      = (data.get('phone')      or '').strip()
    password   = data.get('password')

    if not last_name or not first_name or not username or not email or not telegram or not password:
        return _register_manager_fail('missing_fields')

    if not telegram.startswith('@'):
        return _register_manager_fail('invalid_telegram_format')

    # Check telegram uniqueness across both Applicant and Manager
    if Applicant.objects.filter(telegram__iexact=telegram).exists() or \
       Manager.objects.filter(telegram__iexact=telegram).exists():
        return _register_manager_fail('telegram_exists')

    if len(username) < 3 or len(username) > 30:
        return _register_manager_fail('invalid_username')
    if not re.match(r'^[A-Za-z0-9_.\-]+$', username):
        return _register_manager_fail('invalid_username_format')
    if User.objects.filter(username__iexact=username).exists():
        return _register_manager_fail('username_exists')
    if User.objects.filter(email=email).exists():
        return _register_manager_fail('email_exists')

    user = User.objects.create_user(
        username=username, email=email, password=password,
        first_name=first_name, last_name=last_name,
    )
    manager = Manager.objects.create(user=user, patronymic=patronymic, telegram=telegram,
                                     company=company, phone=phone)

    _log_api_action(
        request,
        action='register_manager',
        before={'username': username, 'email': email, 'telegram': telegram},
        after={'created_user_id': user.pk, 'created_manager_id': manager.pk},
        success=True,
        status_code=200,
        endpoint='api_register_manager',
    )

    return JsonResponse({'ok': True})


@swagger_auto_schema(method='post', operation_summary="Отправить приветственное сообщение в Telegram", tags=['accounts'])
@api_view(['POST'])
@permission_classes([AllowAny])
def api_send_telegram_welcome(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'error': 'invalid_json'}, status=400)

    telegram = (data.get('telegram') or '').strip()
    consent_telegram = bool(data.get('consent_telegram'))

    if not telegram:
        return JsonResponse({'error': 'missing_telegram'}, status=400)
    if not telegram.startswith('@'):
        return JsonResponse({'error': 'invalid_telegram_format'}, status=400)
    if not consent_telegram:
        return JsonResponse({'error': 'no_consent'}, status=400)

    applicant = Applicant.objects.filter(telegram__iexact=telegram).first()
    if not applicant:
        return JsonResponse({'error': 'unknown_telegram'}, status=400)

    if not applicant.telegram_chat_id:
        return JsonResponse({'error': 'chat_id_missing',
                             'message': 'Пожалуйста, откройте чат с ботом и нажмите /start.'}, status=400)

    try:
        send_hello_async(applicant.telegram_chat_id)
    except Exception:
        pass

    return JsonResponse({'ok': True})


@swagger_auto_schema(method='post', operation_summary="Вебхук Telegram", tags=['accounts'])
@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@csrf_exempt
def telegram_webhook(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponse('ok')

    message = data.get('message') or {}
    text = message.get('text', '')
    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    username = chat.get('username')

    if text and text.startswith('/start') and chat_id:
        parts = text.split(None, 1)
        token = None
        if len(parts) > 1:
            token = parts[1].strip()

        if token:
            try:
                applicant = Applicant.objects.get(telegram_start_token=token)
                applicant.telegram_chat_id = chat_id
                applicant.save(update_fields=['telegram_chat_id'])
                if applicant.consent_telegram:
                    send_hello_async(chat_id)
                return HttpResponse('ok')
            except Applicant.DoesNotExist:
                pass

        if username:
            applicant = Applicant.objects.filter(telegram__iexact='@' + username).first()
            if applicant:
                applicant.telegram_chat_id = chat_id
                applicant.save(update_fields=['telegram_chat_id'])
                if applicant.consent_telegram:
                    send_hello_async(chat_id)
                return HttpResponse('ok')

            # Also try to match a manager by Telegram username
            manager = Manager.objects.filter(telegram__iexact='@' + username).first()
            if manager:
                manager.telegram_chat_id = chat_id
                manager.save(update_fields=['telegram_chat_id'])
                if manager.consent_telegram:
                    send_hello_async(chat_id, text='Телеграм подключён! Теперь вы будете получать уведомления от JobFlex.')
                return HttpResponse('ok')

    return HttpResponse('ok')


@swagger_auto_schema(method='post', operation_summary="Вход в систему", tags=['accounts'])
@api_view(['POST'])
@permission_classes([AllowAny])
def api_login(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'error': 'invalid_json'}, status=400)

    identifier = (data.get('username') or data.get('email') or '').strip()
    password = data.get('password') or ''

    if not identifier or not password:
        return JsonResponse({'error': 'missing_fields'}, status=400)

    # Try authenticate by username first
    user = authenticate(request, username=identifier, password=password)
    # If failed and identifier looks like email, try resolving email->username
    if user is None and '@' in identifier:
        try:
            u = User.objects.filter(email__iexact=identifier).first()
            if u:
                user = authenticate(request, username=u.username, password=password)
        except Exception:
            user = None

    if user is None:
        return JsonResponse({'error': 'invalid_credentials'}, status=400)

    auth_login(request, user)
    redirect_to = '/accounts/admin-panel/' if is_admin_user(user) else '/'
    return JsonResponse({'ok': True, 'redirect_to': redirect_to})


@swagger_auto_schema(method='post', operation_summary="Выход из системы", tags=['accounts'])
@api_view(['POST'])
@permission_classes([AllowAny])
def api_logout(request):
    try:
        auth_logout(request)
    except Exception:
        pass
    return JsonResponse({'ok': True})


@swagger_auto_schema(method='get', operation_summary="Получить тему интерфейса", tags=['accounts'])
@swagger_auto_schema(method='post', operation_summary="Сохранить тему интерфейса", tags=['accounts'])
@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def api_user_theme(request):
    """Get/save persistent UI theme for the authenticated user."""
    if request.method == 'GET':
        if not request.user.is_authenticated:
            return JsonResponse({'ok': True, 'theme': None})
        pref = UserUiPreference.objects.filter(user=request.user).first()
        return JsonResponse({'ok': True, 'theme': pref.theme if pref else None})

    # POST
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'not_authenticated'}, status=401)

    try:
        data = request.data if hasattr(request, 'data') else {}
        if not data:
            data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'error': 'invalid_json'}, status=400)

    theme = str((data or {}).get('theme') or '').strip().lower()
    if theme not in ('light', 'dark'):
        return JsonResponse({'error': 'invalid_theme'}, status=400)

    UserUiPreference.objects.update_or_create(
        user=request.user,
        defaults={'theme': theme},
    )
    return JsonResponse({'ok': True, 'theme': theme})


@swagger_auto_schema(method='get', operation_summary="Данные профиля текущего пользователя", tags=['accounts'])
@api_view(['GET'])
@permission_classes([AllowAny])
@login_required
def api_profile_data(request):
    user = request.user
    # Administrators have their own separate profile page
    if is_admin_user(user):
        return JsonResponse({'error': 'admin_has_no_profile'}, status=403)
    applicant = Applicant.objects.filter(user=user).first()
    manager   = Manager.objects.filter(user=user).first()
    data = {
        'first_name': user.first_name,
        'last_name':  user.last_name,
        'email':      user.email,
        'username':   user.username,
        'role':       'manager' if manager else 'applicant',
    }
    bot_start_url = None
    if applicant:
        bot_username = get_bot_username()
        if bot_username and applicant.telegram_start_token:
            bot_start_url = f'https://t.me/{bot_username}?start={applicant.telegram_start_token}'
        data.update({
            'telegram':         applicant.telegram,
            'patronymic':       getattr(applicant, 'patronymic', ''),
            'consent_telegram': applicant.consent_telegram,
            'consent_email':    applicant.consent_email,
            'tg_linked':        bool(applicant.telegram_chat_id),
            'phone':            applicant.phone,
            'gender':           applicant.gender,
            'city':             applicant.city,
            'birth_date':       applicant.birth_date.isoformat() if applicant.birth_date else '',
            'citizenship':      applicant.citizenship,
            'skills':           applicant.skills or [],
            'location_type':      applicant.location_type,
            'metro_city_id':      applicant.metro_city_id,
            'metro_station_id':   applicant.metro_station_id,
            'metro_station_name': applicant.metro_station_name,
            'metro_line_name':    applicant.metro_line_name,
            'metro_line_color':   applicant.metro_line_color,
            'metro_stations':     applicant.metro_stations or [],
            'address':            applicant.address,
            'avatar_url':         applicant.avatar.url if applicant.avatar else '',
            'resume_file_url':    applicant.resume_file.url if applicant.resume_file else '',
            'resume_file_name':   __import__('os').path.basename(applicant.resume_file.name) if applicant.resume_file else '',
            'education': [
                {
                    'id':             e.pk,
                    'level':          e.level,
                    'level_display':  e.get_level_display(),
                    'institution':    e.institution,
                    'graduation_year': e.graduation_year,
                    'faculty':        e.faculty,
                    'specialization': e.specialization,
                }
                for e in applicant.educations.all()
            ],
            'extra_education': [
                {'id': x.pk, 'name': x.name, 'description': x.description}
                for x in applicant.extra_educations.all()
            ],
            'work_experience': [
                {
                    'id':               w.pk,
                    'company':          w.company,
                    'position':         w.position,
                    'start_month':      w.start_month,
                    'start_year':       w.start_year,
                    'end_month':        w.end_month,
                    'end_year':         w.end_year,
                    'is_current':       w.is_current,
                    'responsibilities': w.responsibilities,
                }
                for w in applicant.work_experiences.all()
            ],
        })
    if manager:
        data.update({
            'patronymic':       manager.patronymic,
            'telegram':         manager.telegram,
            'company':          manager.company,
            'phone':            manager.phone,
            'company_logo_url': manager.company_logo.url if manager.company_logo else '',
            'consent_telegram': manager.consent_telegram,
            'consent_email':    manager.consent_email,
            'tg_linked':        bool(manager.telegram_chat_id),
        })
        if not bot_start_url:
            bot_username = get_bot_username()
            if bot_username and manager.telegram:
                bot_start_url = f'https://t.me/{bot_username}'
        # Avatar: prefer applicant.avatar (persists through role switches); fall back to manager.avatar
        if not data.get('avatar_url'):
            data['avatar_url'] = manager.avatar.url if manager.avatar else ''
    return JsonResponse({'ok': True, 'user': data, 'bot_start_url': bot_start_url})


@swagger_auto_schema(method='get', operation_summary="Данные о станциях метро", tags=['accounts'])
@api_view(['GET'])
@permission_classes([AllowAny])
def api_metro_data(request):
    """Return full metro station data from the locally cached HH JSON."""
    metro_path = os.path.join(os.path.dirname(__file__), '..', 'tools', 'metro_hh.json')
    metro_path = os.path.normpath(metro_path)
    try:
        with open(metro_path, encoding='utf-8') as f:
            data = json.load(f)
        return JsonResponse({'ok': True, 'cities': data})
    except FileNotFoundError:
        return JsonResponse({'ok': False, 'cities': []})

@swagger_auto_schema(method='patch', operation_summary="Обновить профиль", tags=['accounts'])
@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def api_profile_update(request):
    from datetime import date as _date

    user = request.user
    data = (request.data or {})

    # ── User-level fields ────────────────────────────────────────
    user_changed = []
    for field in ('first_name', 'last_name', 'email', 'username'):
        if field not in data:
            continue
        val = str(data[field]).strip()
        if field == 'username':
            if len(val) < 3 or len(val) > 30:
                return JsonResponse({'error': 'invalid_username'}, status=400)
            if not re.match(r'^[A-Za-z0-9_.\-]+$', val):
                return JsonResponse({'error': 'invalid_username_format'}, status=400)
            if User.objects.filter(username__iexact=val).exclude(pk=user.pk).exists():
                return JsonResponse({'error': 'username_exists'}, status=400)
        elif field == 'email':
            val = val.lower()
            if User.objects.filter(email=val).exclude(pk=user.pk).exists():
                return JsonResponse({'error': 'email_exists'}, status=400)
        setattr(user, field, val)
        user_changed.append(field)
    if user_changed:
        user.save(update_fields=user_changed)

    # ── Applicant fields ─────────────────────────────────────────
    applicant = Applicant.objects.filter(user=user).first()
    manager = Manager.objects.filter(user=user).first()
    if applicant and not manager:
        # Validate phone format if provided
        if 'phone' in data and data['phone']:
            import re as _re2
            _pd = _re2.sub(r'\D', '', str(data['phone']))
            if _pd.startswith('8'): _pd = '7' + _pd[1:]
            if not _re2.match(r'^7[0-9]{10}$', _pd):
                return JsonResponse({'error': 'invalid_phone'}, status=400)
        a_changed = []
        for f in ('patronymic', 'telegram', 'phone', 'gender', 'city', 'citizenship',
                  'desired_position', 'github_url', 'portfolio_url'):
            if f in data:
                setattr(applicant, f, str(data[f]).strip())
                a_changed.append(f)
        if 'about_me' in data:
            applicant.about_me = str(data['about_me']).strip()
            a_changed.append('about_me')
        if 'birth_date' in data and data['birth_date']:
            try:
                applicant.birth_date = _date.fromisoformat(str(data['birth_date']))
                a_changed.append('birth_date')
            except ValueError:
                return JsonResponse({'error': 'invalid_birth_date'}, status=400)
        # Location fields
        for f in ('location_type', 'metro_city_id', 'metro_station_id',
                  'metro_station_name', 'metro_line_name', 'metro_line_color', 'address'):
            if f in data:
                setattr(applicant, f, str(data[f]).strip())
                a_changed.append(f)
        if 'metro_stations' in data:
            stations = data['metro_stations']
            applicant.metro_stations = stations if isinstance(stations, list) else []
            # Keep legacy single-station fields in sync with first entry
            if applicant.metro_stations:
                first = applicant.metro_stations[0]
                applicant.metro_station_id   = first.get('stationId', '')
                applicant.metro_station_name = first.get('stationName', '')
                applicant.metro_line_name    = first.get('lineName', '')
                applicant.metro_line_color   = first.get('lineColor', '')
                applicant.metro_city_id      = first.get('cityId', '')
                for f in ('metro_station_id', 'metro_station_name', 'metro_line_name',
                          'metro_line_color', 'metro_city_id'):
                    if f not in a_changed:
                        a_changed.append(f)
            else:
                applicant.metro_station_id   = ''
                applicant.metro_station_name = ''
                applicant.metro_line_name    = ''
                applicant.metro_line_color   = ''
                for f in ('metro_station_id', 'metro_station_name', 'metro_line_name', 'metro_line_color'):
                    if f not in a_changed:
                        a_changed.append(f)
            a_changed.append('metro_stations')
        if a_changed:
            applicant.save(update_fields=a_changed)

        # Salary expectations (stored separately; allow clearing with null)
        salary_changed = []
        for f in ('salary_expectation_from', 'salary_expectation_to'):
            if f in data:
                raw = data[f]
                if raw is None or str(raw).strip() == '':
                    setattr(applicant, f, None)
                else:
                    try:
                        setattr(applicant, f, int(str(raw).strip()))
                    except (ValueError, TypeError):
                        return JsonResponse({'error': 'invalid_salary'}, status=400)
                salary_changed.append(f)
        if salary_changed:
            applicant.save(update_fields=salary_changed)

    # ── Manager fields ───────────────────────────────────────────
    if manager:
        # Uniqueness checks
        if 'telegram' in data:
            tg_val = str(data.get('telegram', '')).strip()
            if tg_val and Manager.objects.filter(telegram=tg_val).exclude(user=user).exists():
                return JsonResponse({'error': 'telegram_exists'}, status=400)
        if 'phone' in data:
            ph_val = str(data.get('phone', '')).strip()
            if ph_val and Manager.objects.filter(phone=ph_val).exclude(user=user).exists():
                return JsonResponse({'error': 'phone_exists'}, status=400)
        m_changed = []
        for f in ('patronymic', 'telegram', 'phone', 'company'):
            if f in data:
                setattr(manager, f, str(data.get(f, '')).strip())
                m_changed.append(f)
        if m_changed:
            manager.save(update_fields=m_changed)

    return JsonResponse({'ok': True})


# ─────────────────────────────────────────────────────────────
#  Application (отклик) views
# ─────────────────────────────────────────────────────────────

@swagger_auto_schema(method='post', operation_summary="Откликнуться на вакансию", tags=['accounts'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_apply(request):
    """Applicant submits an application for a vacancy."""
    if not hasattr(request.user, 'applicant'):
        return JsonResponse({'error': 'not_applicant'}, status=403)
    data = request.data or {}
    vacancy_id   = data.get('vacancy_id')
    cover_letter = (data.get('cover_letter') or '').strip()
    if not vacancy_id:
        return JsonResponse({'error': 'vacancy_id required'}, status=400)
    from vacancies.models import Vacancy
    from django.shortcuts import get_object_or_404
    vacancy = get_object_or_404(Vacancy, pk=vacancy_id)
    if vacancy.is_hh:
        return JsonResponse({'error': 'hh_vacancy'}, status=400)
    if not vacancy.is_active:
        return JsonResponse({'error': 'vacancy_archived'}, status=400)
    # Block applying to own vacancy (both employer and any user who created it)
    if vacancy.created_by_id == request.user.pk:
        return JsonResponse({'error': 'own_vacancy'}, status=403)
    app, created = Application.objects.get_or_create(
        vacancy=vacancy, applicant=request.user,
        defaults={'cover_letter': cover_letter},
    )
    if not created and cover_letter:
        # allow updating cover letter if still pending
        if app.status == 'pending':
            app.cover_letter = cover_letter
            app.save(update_fields=['cover_letter'])

    # Notify the vacancy manager about the new application (fire-and-forget)
    if created and vacancy.created_by_id:
        try:
            mgr_user = vacancy.created_by
            mgr      = getattr(mgr_user, 'manager', None)
            if mgr:
                applicant_name = request.user.get_full_name() or request.user.username
                msg = (
                    f"📬 Новый отклик на «{vacancy.title}»\n"
                    f"Соискатель: {applicant_name}"
                )
                if mgr.consent_telegram and mgr.telegram_chat_id:
                    send_hello_async(mgr.telegram_chat_id, msg)
                if mgr.consent_email and mgr_user.email:
                    send_mail(
                        subject=f"Новый отклик на «{vacancy.title}»",
                        message=msg,
                        from_email=django_settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[mgr_user.email],
                        fail_silently=True,
                    )
        except Exception:
            pass  # notifications are best-effort

    return JsonResponse({'ok': True, 'created': created, 'status': app.status})


@swagger_auto_schema(method='post', operation_summary="Изменить статус отклика", tags=['accounts'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_application_status(request, pk):
    """Manager updates the status of an application."""
    from django.shortcuts import get_object_or_404
    if not hasattr(request.user, 'manager'):
        _log_api_action(
            request,
            action='application_status_change',
            before={'application_id': pk},
            after={'error': 'not_manager'},
            success=False,
            status_code=403,
            endpoint='api_application_status',
        )
        return JsonResponse({'error': 'not_manager'}, status=403)
    app = get_object_or_404(Application, pk=pk)
    new_status = (request.data or {}).get('status', '')
    valid = {s for s, _ in Application.STATUS_CHOICES}
    if new_status not in valid:
        _log_api_action(
            request,
            action='application_status_change',
            before={'application_id': app.pk, 'status': app.status},
            after={'error': 'invalid_status', 'requested_status': new_status},
            success=False,
            status_code=400,
            endpoint='api_application_status',
        )
        return JsonResponse({'error': 'invalid_status'}, status=400)
    old_status = app.status
    app.status = new_status
    app.save(update_fields=['status'])
    _log_api_action(
        request,
        action='application_status_change',
        before={'application_id': app.pk, 'status': old_status},
        after={
            'application_id': app.pk,
            'status': app.status,
            'vacancy_id': app.vacancy_id,
            'applicant_id': app.applicant_id,
        },
        success=True,
        status_code=200,
        endpoint='api_application_status',
    )
    return JsonResponse({'ok': True, 'status': app.status})


# ─── Avatar / logo upload ────────────────────────────────────────────────────

UPLOAD_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
UPLOAD_ALLOWED_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}


def _check_upload(f):
    """Return error string or None."""
    if not f:
        return 'no_file'
    if f.size > UPLOAD_MAX_BYTES:
        return 'file_too_large'
    if f.content_type not in UPLOAD_ALLOWED_TYPES:
        return 'invalid_type'
    return None


@login_required
def api_upload_avatar(request):
    """Upload / replace user avatar.
    Saves the same file to BOTH applicant and manager records so the photo
    is shared between roles and survives role switches.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    f = request.FILES.get('avatar')
    err = _check_upload(f)
    if err:
        return JsonResponse({'error': err}, status=400)

    applicant = Applicant.objects.filter(user=request.user).first()
    manager   = Manager.objects.filter(user=request.user).first()

    if not applicant and not manager:
        return JsonResponse({'error': 'profile_not_found'}, status=404)

    saved_url = None

    # Applicant is the primary storage (record never gets deleted on role switch)
    if applicant:
        if applicant.avatar:
            applicant.avatar.delete(save=False)
        applicant.avatar = f
        applicant.save(update_fields=['avatar'])
        saved_url = applicant.avatar.url

    # Sync the same file path to manager record (no extra disk copy needed)
    if manager:
        if manager.avatar:
            manager.avatar.delete(save=False)
        if applicant and applicant.avatar:
            manager.avatar = applicant.avatar.name  # string assignment, points to same file
            manager.save(update_fields=['avatar'])
        else:
            # manager-only user: save file normally
            f.seek(0)
            manager.avatar = f
            manager.save(update_fields=['avatar'])
        if saved_url is None:
            saved_url = manager.avatar.url

    return JsonResponse({'ok': True, 'url': saved_url})


@login_required
def api_upload_company_logo(request):
    """Upload / replace company logo (managers only)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    if not hasattr(request.user, 'manager'):
        return JsonResponse({'error': 'not_manager'}, status=403)
    f = request.FILES.get('logo')
    err = _check_upload(f)
    if err:
        return JsonResponse({'error': err}, status=400)
    manager = request.user.manager
    if manager.company_logo:
        manager.company_logo.delete(save=False)
    manager.company_logo = f
    manager.save(update_fields=['company_logo'])
    return JsonResponse({'ok': True, 'url': manager.company_logo.url})


# ─── Resume file upload ───────────────────────────────────────────────────────

RESUME_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
RESUME_ALLOWED_TYPES = {
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
    'application/msword',  # .doc
}
RESUME_ALLOWED_EXTS = {'.docx', '.doc'}


@login_required
def api_upload_resume(request):
    """Upload a Word resume file (.docx / .doc) for the logged-in applicant."""
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    applicant = Applicant.objects.filter(user=request.user).first()
    if not applicant:
        return JsonResponse({'error': 'profile_not_found'}, status=404)
    f = request.FILES.get('resume')
    if not f:
        return JsonResponse({'error': 'no_file'}, status=400)
    if f.size > RESUME_MAX_BYTES:
        return JsonResponse({'error': 'file_too_large'}, status=400)
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in RESUME_ALLOWED_EXTS:
        return JsonResponse({'error': 'invalid_type'}, status=400)
    # Delete the old file if it exists
    if applicant.resume_file:
        applicant.resume_file.delete(save=False)
    applicant.resume_file = f
    applicant.save(update_fields=['resume_file'])
    return JsonResponse({
        'ok': True,
        'url': applicant.resume_file.url,
        'name': os.path.basename(applicant.resume_file.name),
    })


@login_required
def api_delete_resume(request):
    """DELETE the uploaded Word resume file for the logged-in applicant."""
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    applicant = Applicant.objects.filter(user=request.user).first()
    if not applicant:
        return JsonResponse({'error': 'profile_not_found'}, status=404)
    if applicant.resume_file:
        applicant.resume_file.delete(save=False)
        applicant.resume_file = None
        applicant.save(update_fields=['resume_file'])
    return JsonResponse({'ok': True})


# ─── Bookmarks ────────────────────────────────────────────────────────────────

@login_required
def api_toggle_bookmark(request, pk):
    """POST – toggle bookmark on a vacancy. Returns {'ok', 'bookmarked'}."""
    if request.method != 'POST':
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    from vacancies.models import Vacancy, Bookmark
    try:
        vacancy = Vacancy.objects.get(pk=pk)
    except Vacancy.DoesNotExist:
        return JsonResponse({'error': 'not_found'}, status=404)
    obj, created = Bookmark.objects.get_or_create(user=request.user, vacancy=vacancy)
    if not created:
        obj.delete()
        return JsonResponse({'ok': True, 'bookmarked': False})
    return JsonResponse({'ok': True, 'bookmarked': True})


# ─── Applicant analytics ──────────────────────────────────────────────────────

@login_required
def api_applicant_analytics(request):
    """Return personal analytics: bookmarks, viewed vacancies, profile data for charts."""
    from vacancies.models import Bookmark, VacancyView

    user = request.user

    # ── All bookmarks (loaded once; slice for display list) ───────────────────
    all_bookmarks_qs = (
        Bookmark.objects.filter(user=user)
        .select_related('vacancy__employer')
        .order_by('-created_at')
    )

    bookmark_list = []
    for b in all_bookmarks_qs[:20]:
        v = b.vacancy
        bookmark_list.append({
            'id': v.pk, 'external_id': v.external_id, 'title': v.title, 'company': v.company,
            'region': v.region,
            'salary_from': v.salary_from, 'salary_to': v.salary_to,
            'salary_currency': v.salary_currency,
            'logo_url': v.employer_logo_url or '',
            'saved_at': b.created_at.strftime('%d.%m.%Y'),
            'experience_name': v.experience_name or '',
        })

    # ── Recently viewed ───────────────────────────────────────────────────────
    viewed_qs = (
        VacancyView.objects.filter(user=user)
        .select_related('vacancy__employer')
        .order_by('-viewed_at')[:200]
    )
    viewed_list = []
    for vv in viewed_qs:
        v = vv.vacancy
        viewed_list.append({
            'id': v.pk, 'external_id': v.external_id, 'title': v.title, 'company': v.company,
            'region': v.region,
            'salary_from': v.salary_from, 'salary_to': v.salary_to,
            'salary_currency': v.salary_currency,
            'logo_url': v.employer_logo_url or '',
            'viewed_at': vv.viewed_at.strftime('%d.%m.%Y %H:%M'),
        })

    # ── Profile completeness + skills + salary ────────────────────────────────
    applicant = getattr(user, 'applicant', None)
    profile_completeness = {'filled': 0, 'total': 0, 'fields': {}}
    skills = []
    salary_data = {'expectation_from': None, 'expectation_to': None, 'market': []}
    charts_data  = {'experience': {}, 'work_format': {}}

    if applicant:
        fields_map = {
            'Фото': bool(applicant.avatar),
            'Имя': bool(user.first_name and user.first_name.strip()),
            'Телефон': bool(applicant.phone),
            'Город': bool(applicant.city),
            'Дата рождения': bool(applicant.birth_date),
            'Пол': bool(applicant.gender),
            'Гражданство': bool(applicant.citizenship),
            'Навыки': bool(applicant.skills),
            'Образование': applicant.educations.exists(),
            'Опыт работы': applicant.work_experiences.exists(),
            'Зарплатные ожидания': bool(applicant.salary_expectation_from),
        }
        profile_completeness = {
            'filled': sum(fields_map.values()),
            'total': len(fields_map),
            'fields': fields_map,
        }

        skills = applicant.skills or []

        # Salary data + chart distributions — single pass over all bookmarks
        from collections import Counter
        market_salaries = []
        exp_counter  = Counter()
        fmt_counter  = Counter()
        for b in all_bookmarks_qs:
            v = b.vacancy
            if v.salary_from or v.salary_to:
                market_salaries.append({
                    'from': v.salary_from,
                    'to': v.salary_to,
                    'currency': v.salary_currency or 'RUB',
                })
            exp_counter[v.experience_name or 'Не указан'] += 1
            has_fmt = False
            if v.is_remote: fmt_counter['Удалённо'] += 1; has_fmt = True
            if v.is_hybrid: fmt_counter['Гибрид']   += 1; has_fmt = True
            if v.is_onsite and not v.is_remote and not v.is_hybrid:
                fmt_counter['Офис'] += 1; has_fmt = True
            if not has_fmt:
                fmt_counter['Не указан'] += 1

        salary_data = {
            'expectation_from': applicant.salary_expectation_from,
            'expectation_to': applicant.salary_expectation_to,
            'market': market_salaries,
        }
        charts_data = {
            'experience':  dict(exp_counter.most_common()),
            'work_format': dict(fmt_counter.most_common()),
        }

    # ── Activity data (heatmap + weekly line chart) ────────────────────────────
    from datetime import date as _date, timedelta
    from django.db.models import Count as _Count
    from django.db.models.functions import (
        TruncDate as _TruncDate, TruncWeek as _TruncWeek,
        TruncMonth as _TruncMonth, TruncYear as _TruncYear,
        ExtractHour as _ExtractHour,
    )

    today_d   = _date.today()
    since_365 = today_d - timedelta(days=364)
    since_16w = today_d - timedelta(weeks=16)
    since_30d = today_d - timedelta(days=30)
    since_24m = today_d - timedelta(days=730)

    daily_qs = (
        VacancyView.objects
        .filter(user=user, viewed_at__date__gte=since_365)
        .annotate(day=_TruncDate('viewed_at'))
        .values('day')
        .annotate(count=_Count('id'))
        .order_by('day')
    )
    daily_counts = {str(row['day']): row['count'] for row in daily_qs}

    weekly_qs = (
        VacancyView.objects
        .filter(user=user, viewed_at__date__gte=since_16w)
        .annotate(week=_TruncWeek('viewed_at'))
        .values('week')
        .annotate(count=_Count('id'))
        .order_by('week')
    )
    weekly_counts = [
        {'week': row['week'].strftime('%d.%m'), 'count': row['count']}
        for row in weekly_qs
    ]

    hourly_qs = (
        VacancyView.objects
        .filter(user=user, viewed_at__date__gte=since_30d)
        .annotate(hour=_ExtractHour('viewed_at'))
        .values('hour')
        .annotate(count=_Count('id'))
        .order_by('hour')
    )
    hourly_counts = {str(row['hour']): row['count'] for row in hourly_qs}

    monthly_qs = (
        VacancyView.objects
        .filter(user=user, viewed_at__date__gte=since_24m)
        .annotate(month=_TruncMonth('viewed_at'))
        .values('month')
        .annotate(count=_Count('id'))
        .order_by('month')
    )
    monthly_counts = [
        {'month': row['month'].strftime('%m.%Y'), 'count': row['count']}
        for row in monthly_qs
    ]

    yearly_qs = (
        VacancyView.objects
        .filter(user=user)
        .annotate(year=_TruncYear('viewed_at'))
        .values('year')
        .annotate(count=_Count('id'))
        .order_by('year')
    )
    yearly_counts = [
        {'year': row['year'].strftime('%Y'), 'count': row['count']}
        for row in yearly_qs
    ]

    activity_data = {
        'daily':   daily_counts,
        'weekly':  weekly_counts,
        'hourly':  hourly_counts,
        'monthly': monthly_counts,
        'yearly':  yearly_counts,
        'today':   str(today_d),
    }

    return JsonResponse({
        'ok': True,
        'bookmarks': bookmark_list,
        'viewed_vacancies': viewed_list,
        'profile_completeness': profile_completeness,
        'skills': skills,
        'salary_data': salary_data,
        'activity': activity_data,
        'charts_data': charts_data,
    })




@login_required
def vacancy_applications(request, pk):
    """Manager sees all applicants who applied to a specific vacancy."""
    from django.shortcuts import get_object_or_404
    from django.db.models import Prefetch
    if not hasattr(request.user, 'manager'):
        from django.shortcuts import redirect
        return redirect('vacancy-list')
    from vacancies.models import Vacancy
    vacancy = get_object_or_404(Vacancy, pk=pk)
    apps = (
        Application.objects
        .filter(vacancy=vacancy)
        .select_related('applicant', 'applicant__applicant')
        .prefetch_related(
            Prefetch('applicant__applicant__educations',
                     queryset=Education.objects.order_by('-order')),
            Prefetch('applicant__applicant__work_experiences',
                     queryset=WorkExperience.objects.order_by('-order')),
        )
        .order_by('-created_at')
    )
    return render(request, 'accounts/vacancy_applications.html', {
        'vacancy': vacancy,
        'applications': apps,
        'status_choices': Application.STATUS_CHOICES,
    })



@swagger_auto_schema(method='get', operation_summary="Анализ резюме", tags=['accounts'])
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_resume_analyze(request):
    """Analyze the current user's resume for completeness, inconsistencies, and spelling."""
    import requests as _req
    from datetime import date as _date

    applicant = getattr(request.user, 'applicant', None)
    if not applicant:
        return JsonResponse({'error': 'not_applicant'}, status=403)

    educations  = list(applicant.educations.all())
    experiences = list(applicant.work_experiences.all())
    today_year  = _date.today().year
    birth_year  = applicant.birth_date.year if applicant.birth_date else None

    issues = []

    # ── Completeness ─────────────────────────────────────────────
    if not applicant.about_me:
        issues.append({'type': 'tip', 'section': 'О себе',
                       'text': 'Добавьте краткое описание «О себе» — это первое, что читает рекрутер'})
    if not applicant.desired_position:
        issues.append({'type': 'tip', 'section': 'Желаемая должность',
                       'text': 'Укажите желаемую должность, чтобы рекрутер сразу понял, на что вы претендуете'})
    if not applicant.skills:
        issues.append({'type': 'warning', 'section': 'Навыки',
                       'text': 'Навыки не указаны — это снижает шансы попасть в результаты поиска'})
    if not applicant.phone:
        issues.append({'type': 'tip', 'section': 'Контакты',
                       'text': 'Укажите номер телефона для связи'})
    if not applicant.city:
        issues.append({'type': 'tip', 'section': 'Город',
                       'text': 'Укажите город проживания'})
    if not applicant.birth_date:
        issues.append({'type': 'tip', 'section': 'Личные данные',
                       'text': 'Укажите дату рождения'})
    if not experiences:
        issues.append({'type': 'warning', 'section': 'Опыт работы',
                       'text': 'Не добавлен опыт работы'})
    if not educations:
        issues.append({'type': 'warning', 'section': 'Образование',
                       'text': 'Не добавлено образование'})
    if not applicant.salary_expectation_from:
        issues.append({'type': 'tip', 'section': 'Зарплата',
                       'text': 'Укажите ожидаемую зарплату — работодатели ориентируются на неё'})
    if not applicant.github_url and not applicant.portfolio_url:
        issues.append({'type': 'tip', 'section': 'Ссылки',
                       'text': 'Добавьте ссылку на GitHub или портфолио — это выделяет вас среди кандидатов'})

    # ── Temporal / logical inconsistencies ───────────────────────
    for exp in experiences:
        label = f'«{exp.company}»'
        if exp.start_year:
            if birth_year and exp.start_year < birth_year + 14:
                issues.append({'type': 'suspicious', 'section': 'Опыт работы',
                                'text': f'{label}: начало в {exp.start_year}, но по дате рождения вам было бы < 14 лет'})
            if exp.start_year > today_year + 1:
                issues.append({'type': 'error', 'section': 'Опыт работы',
                                'text': f'{label}: дата начала в будущем ({exp.start_year})'})
            if exp.end_year:
                if exp.end_year < exp.start_year:
                    issues.append({'type': 'error', 'section': 'Опыт работы',
                                   'text': f'{label}: год окончания ({exp.end_year}) раньше года начала ({exp.start_year})'})
                if not exp.is_current and exp.end_year > today_year:
                    issues.append({'type': 'suspicious', 'section': 'Опыт работы',
                                   'text': f'{label}: год окончания {exp.end_year} в будущем, но не отмечено «Работаю сейчас»'})
        if exp.responsibilities and len(exp.responsibilities.strip()) < 30:
            issues.append({'type': 'tip', 'section': 'Опыт работы',
                           'text': f'{label}: описание обязанностей очень короткое — расскажите подробнее'})

    # Overlapping work periods
    periods = []
    for exp in experiences:
        if exp.start_year:
            end = today_year if exp.is_current else (exp.end_year or today_year)
            periods.append((exp.start_year, end, exp.company))
    for i in range(len(periods)):
        for j in range(i + 1, len(periods)):
            a_s, a_e, a_c = periods[i]
            b_s, b_e, b_c = periods[j]
            overlap = min(a_e, b_e) - max(a_s, b_s)
            if overlap >= 1:
                issues.append({'type': 'suspicious', 'section': 'Опыт работы',
                               'text': f'Пересекающиеся периоды: «{a_c}» и «{b_c}» ({max(a_s,b_s)}–{min(a_e,b_e)} г.)'})

    for edu in educations:
        if edu.graduation_year:
            if birth_year and edu.graduation_year < birth_year + 15:
                issues.append({'type': 'suspicious', 'section': 'Образование',
                               'text': f'«{edu.institution}»: год окончания {edu.graduation_year} — вам было бы < 15 лет'})
            if edu.graduation_year > today_year + 8:
                issues.append({'type': 'suspicious', 'section': 'Образование',
                               'text': f'«{edu.institution}»: год окончания {edu.graduation_year} — слишком далеко в будущем'})

    # High salary with no experience
    if applicant.salary_expectation_from and not experiences:
        if applicant.salary_expectation_from > 200_000:
            issues.append({'type': 'suspicious', 'section': 'Зарплата',
                           'text': f'Ожидаемая зарплата {applicant.salary_expectation_from:,} ₽ при отсутствии опыта работы — возможно, завышена'})

    # ── Spell check via Yandex Speller (free, no key needed) ─────
    spell_errors = []
    texts_to_check = []
    if applicant.about_me:
        texts_to_check.append(('О себе', applicant.about_me))
    if applicant.desired_position:
        texts_to_check.append(('Желаемая должность', applicant.desired_position))
    for exp in experiences:
        if exp.responsibilities:
            texts_to_check.append((f'Опыт: {exp.company}', exp.responsibilities))

    try:
        for label, text in texts_to_check[:6]:
            resp = _req.post(
                'https://speller.yandex.net/services/spellservice.json/checkText',
                data={'text': text[:3000], 'lang': 'ru,en', 'options': 4},
                timeout=4,
            )
            if resp.status_code == 200:
                for err in resp.json()[:8]:
                    spell_errors.append({
                        'section':     label,
                        'word':        err.get('word', ''),
                        'suggestions': err.get('s', [])[:3],
                    })
    except Exception:
        pass  # spell check is best-effort

    return JsonResponse({'ok': True, 'issues': issues, 'spell_errors': spell_errors})


@login_required
def export_applications_csv(request, pk):
    """Manager downloads a CSV with all applicants for a specific vacancy."""
    from django.shortcuts import get_object_or_404
    from vacancies.models import Vacancy
    if not hasattr(request.user, 'manager'):
        return redirect('vacancy-list')
    vacancy = get_object_or_404(Vacancy, pk=pk)
    apps = (
        Application.objects
        .filter(vacancy=vacancy)
        .select_related('applicant', 'applicant__applicant')
        .order_by('-created_at')
    )
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    filename = f"applicants_{vacancy.pk}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(['ФИО', 'Email', 'Телефон', 'Город', 'Навыки', 'Статус', 'Дата отклика', 'Сопроводительное письмо'])
    status_labels = dict(Application.STATUS_CHOICES)
    for app in apps:
        u  = app.applicant
        ap = getattr(u, 'applicant', None)
        writer.writerow([
            u.get_full_name() or u.username,
            u.email,
            ap.phone if ap else '',
            ap.city  if ap else '',
            ', '.join(ap.skills) if ap and ap.skills else '',
            status_labels.get(app.status, app.status),
            app.created_at.strftime('%d.%m.%Y'),
            app.cover_letter,
        ])
    return response


@login_required
def resume_pdf(request, pk):
    """Print-friendly resume page for an applicant (accessible to the applicant and managers)."""
    from django.shortcuts import get_object_or_404
    applicant = get_object_or_404(Applicant, pk=pk)
    is_own    = (request.user == applicant.user)
    is_mgr    = hasattr(request.user, 'manager')
    is_admin  = request.user.is_superuser
    if not (is_own or is_mgr or is_admin):
        from django.http import Http404
        raise Http404

    # Manager viewing resume → mark pending applications as "viewed"
    if is_mgr and not is_own:
        from vacancies.models import Vacancy
        mgr_vacancies = Vacancy.objects.filter(created_by=request.user)
        Application.objects.filter(
            applicant=applicant.user,
            vacancy__in=mgr_vacancies,
            status='pending',
        ).update(status='viewed')

    educations = applicant.educations.order_by('order')
    experiences = applicant.work_experiences.order_by('order')
    extra_educations = applicant.extra_educations.order_by('order')
    return render(request, 'accounts/resume_pdf.html', {
        'applicant':        applicant,
        'educations':       educations,
        'experiences':      experiences,
        'extra_educations': extra_educations,
    })


@login_required
def resume_word_view(request, pk):
    """Render a Word resume (.docx) as styled HTML (manager or owner only)."""
    from django.shortcuts import get_object_or_404, redirect
    from django.http import Http404
    from django.utils.html import escape

    applicant = get_object_or_404(Applicant, pk=pk)
    is_own = (request.user == applicant.user)
    is_mgr = hasattr(request.user, 'manager')
    if not (is_own or is_mgr):
        raise Http404

    # Manager viewing resume → mark pending applications as "viewed"
    if is_mgr and not is_own:
        from vacancies.models import Vacancy
        mgr_vacancies = Vacancy.objects.filter(created_by=request.user)
        Application.objects.filter(
            applicant=applicant.user,
            vacancy__in=mgr_vacancies,
            status='pending',
        ).update(status='viewed')

    if not applicant.resume_file:
        return redirect('accounts:resume_pdf', pk=pk)

    file_path = applicant.resume_file.path
    ext = os.path.splitext(file_path)[1].lower()

    html_parts = []

    try:
        if ext == '.docx':
            from docx import Document
            from docx.oxml.ns import qn as _qn
            from docx.text.paragraph import Paragraph as _Paragraph
            from docx.table import Table as _Table
            from docx.enum.text import WD_ALIGN_PARAGRAPH

            ALIGN_MAP = {
                WD_ALIGN_PARAGRAPH.LEFT:      'left',
                WD_ALIGN_PARAGRAPH.CENTER:    'center',
                WD_ALIGN_PARAGRAPH.RIGHT:     'right',
                WD_ALIGN_PARAGRAPH.JUSTIFY:   'justify',
                WD_ALIGN_PARAGRAPH.DISTRIBUTE:'justify',
            }

            def _emu_to_px(emu):
                if emu is None:
                    return None
                return round(emu / 914400 * 96)

            def _process_para(para):
                fmt = para.paragraph_format
                style_name = (para.style.name or '').lower()
                level = None
                if 'heading 1' in style_name:
                    level = 1
                elif 'heading 2' in style_name:
                    level = 2
                elif 'heading 3' in style_name:
                    level = 3

                para_styles = []
                align = ALIGN_MAP.get(para.alignment)
                if align:
                    para_styles.append(f'text-align:{align}')
                li = fmt.left_indent
                if li is not None:
                    px = _emu_to_px(li)
                    if px and px > 0:
                        para_styles.append(f'margin-left:{px}px')
                sb = fmt.space_before
                if sb is not None:
                    px = _emu_to_px(sb)
                    if px and px > 0:
                        para_styles.append(f'margin-top:{px}px')
                sa = fmt.space_after
                if sa is not None:
                    px = _emu_to_px(sa)
                    if px and px > 0:
                        para_styles.append(f'margin-bottom:{px}px')

                runs_html = ''
                for run in para.runs:
                    text = escape(run.text)
                    if not text:
                        continue
                    rs = []
                    if run.font.size:
                        pt = run.font.size / 12700
                        if pt > 0:
                            rs.append(f'font-size:{pt:.0f}pt')
                    try:
                        rgb = run.font.color.rgb
                        if rgb is not None:
                            rs.append(f'color:#{str(rgb)}')
                    except Exception:
                        pass
                    decorations = []
                    if run.underline:
                        decorations.append('underline')
                    if run.font.strike:
                        decorations.append('line-through')
                    if decorations:
                        rs.append(f'text-decoration:{" ".join(decorations)}')
                    if rs:
                        text = f'<span style="{";".join(rs)}">{text}</span>'
                    if run.bold and run.italic:
                        text = f'<strong><em>{text}</em></strong>'
                    elif run.bold:
                        text = f'<strong>{text}</strong>'
                    elif run.italic:
                        text = f'<em>{text}</em>'
                    runs_html += text

                if not runs_html.strip():
                    return '<p class="dp-empty">&nbsp;</p>'
                tag = f'h{level}' if level else 'p'
                css = f'dh{level}' if level else 'dp'
                style_attr = f' style="{";".join(para_styles)}"' if para_styles else ''
                return f'<{tag} class="{css}"{style_attr}>{runs_html}</{tag}>'

            def _process_table(table):
                rows_html = ''
                for row in table.rows:
                    cells_html = ''
                    for cell in row.cells:
                        cell_inner = ''.join(_process_para(p) for p in cell.paragraphs)
                        cells_html += f'<td>{cell_inner}</td>'
                    rows_html += f'<tr>{cells_html}</tr>'
                return f'<table class="dt">{rows_html}</table>'

            doc = Document(file_path)
            for child in doc.element.body:
                if child.tag == _qn('w:p'):
                    html_parts.append(_process_para(_Paragraph(child, doc)))
                elif child.tag == _qn('w:tbl'):
                    html_parts.append(_process_table(_Table(child, doc)))
        else:
            html_parts.append('<p class="dp">Предпросмотр .doc не поддерживается. Загрузите файл в формате .docx</p>')
    except Exception:
        html_parts.append('<p class="dp">Не удалось прочитать файл. Убедитесь, что файл не повреждён.</p>')

    return render(request, 'accounts/resume_word.html', {
        'applicant':        applicant,
        'educations':       applicant.educations.order_by('order'),
        'extra_educations': applicant.extra_educations.order_by('order'),
        'experiences':      applicant.work_experiences.order_by('order'),
        'content_html':     '\n'.join(html_parts),
        'file_name':        os.path.basename(applicant.resume_file.name),
    })


# ─────────────────────────────────────────────────────────────
#  Manager analytics
# ─────────────────────────────────────────────────────────────

@login_required
def manager_analytics(request):
    """Aggregated analytics page for a manager: vacancy performance + application stats."""
    from django.db.models import Count, Q as DQ
    from vacancies.models import Vacancy, VacancyView
    if not hasattr(request.user, 'manager'):
        return redirect('vacancy-list')

    user = request.user

    vacancies = (
        Vacancy.objects
        .filter(created_by=user)
        .annotate(
            total_views=Count('views', distinct=True),
            total_apps=Count('applications', distinct=True),
            accepted=Count('applications', filter=DQ(applications__status='accepted'), distinct=True),
            rejected=Count('applications', filter=DQ(applications__status='rejected'), distinct=True),
            pending=Count('applications',  filter=DQ(applications__status='pending'),  distinct=True),
        )
        .order_by('-created_at')
    )

    total_vacancies = vacancies.count()
    total_active    = sum(1 for v in vacancies if v.is_active)
    total_apps      = sum(v.total_apps   for v in vacancies)
    total_accepted  = sum(v.accepted     for v in vacancies)
    total_rejected  = sum(v.rejected     for v in vacancies)
    total_pending   = sum(v.pending      for v in vacancies)
    total_views     = sum(v.total_views  for v in vacancies)

    # Recent applications (past 30 days)
    from datetime import timedelta
    from django.utils import timezone
    since_30d = timezone.now() - timedelta(days=30)
    recent_apps = (
        Application.objects
        .filter(vacancy__created_by=user, created_at__gte=since_30d)
        .select_related('applicant', 'vacancy')
        .order_by('-created_at')[:20]
    )

    manager_obj = request.user.manager
    return render(request, 'accounts/manager_analytics.html', {
        'vacancies':       vacancies,
        'total_vacancies': total_vacancies,
        'total_active':    total_active,
        'total_apps':      total_apps,
        'total_accepted':  total_accepted,
        'total_rejected':  total_rejected,
        'total_pending':   total_pending,
        'total_views':     total_views,
        'recent_apps':     recent_apps,
        'status_choices':  Application.STATUS_CHOICES,
        # Notification settings (for the Notifications tab)
        'mgr_consent_telegram': manager_obj.consent_telegram,
        'mgr_consent_email':    manager_obj.consent_email,
        'mgr_tg_linked':        bool(manager_obj.telegram_chat_id),
        'mgr_telegram':         manager_obj.telegram,
    })


# ─────────────────────────────────────────────────────────────
#  Admin panel
# ─────────────────────────────────────────────────────────────

@admin_required
def admin_panel(request):
    """Main page for system administrators."""
    from django.contrib.auth.models import User as _User
    from vacancies.models import Vacancy

    from django.db.models import Q as _Q
    # Count users who currently have a Manager profile
    # OR applicants who have ever switched to manager (was_manager=True)
    total_managers = _User.objects.filter(
        _Q(manager__isnull=False) | _Q(applicant__was_manager=True)
    ).distinct().count()

    stats = {
        'total_users':      _User.objects.count(),
        'total_applicants': Applicant.objects.count(),
        'total_managers':   total_managers,
        'total_vacancies':  Vacancy.objects.count(),
        'total_admins':     Administrator.objects.count(),
    }

    # Build backup list for the admin panel.
    from pathlib import Path as _Path
    from datetime import datetime as _dt
    from django.conf import settings as _cfg
    _backup_dir = _Path(getattr(_cfg, 'BACKUP_DIR',
                                _Path(_cfg.DATABASES['default']['NAME']).parent / 'backups'))
    backups = []
    if _backup_dir.exists():
        for _bf in sorted(_backup_dir.glob('db_backup_*.sqlite3'), reverse=True):
            _ts = _dt.fromtimestamp(_bf.stat().st_mtime)
            backups.append({
                'filename':    _bf.name,
                'size_kb':     round(_bf.stat().st_size / 1024, 1),
                'created_str': _ts.strftime('%d.%m.%Y %H:%M:%S'),
            })

    try:
        log_page = int(request.GET.get('log_page', '1') or '1')
    except ValueError:
        log_page = 1

    action_label_map = {
        'backup_create': 'Создание бэкапа',
        'backup_restore': 'Восстановление бэкапа',
        'backup_delete': 'Удаление бэкапа',
        'switch_role': 'Смена роли',
        'register_applicant': 'Регистрация соискателя',
        'register_manager': 'Регистрация менеджера',
        'application_status_change': 'Изменение статуса отклика',
        'preset_create': 'Создание пресета',
        'preset_update': 'Обновление пресета',
        'preset_delete': 'Удаление пресета',
        'interview_schedule': 'Назначение собеседования',
        'interview_cancel': 'Отмена собеседования',
        'interview_reschedule': 'Перенос собеседования',
        'delete_account': 'Удаление аккаунта',
        'admin_user_delete': 'Удаление пользователя администратором',
        'admin_user_contacts_update': 'Обновление контактов пользователя',
        'admin_user_role_change': 'Смена роли пользователя администратором',
    }
    actor_label_map = {
        'system': 'Система',
        'admin': 'Администратор',
        'manager': 'Менеджер',
        'applicant': 'Соискатель',
        'user': 'Пользователь',
    }

    logs_qs = ApiActionLog.objects.select_related('user').order_by('-created_at')
    logs_paginator = Paginator(logs_qs, 20)
    logs_page_obj = logs_paginator.get_page(log_page)
    audit_logs = []
    for item in logs_page_obj.object_list:
        username = 'system'
        if item.user:
            username = item.user.get_full_name() or item.user.username
        audit_logs.append({
            'id': item.pk,
            'created_at': item.created_at,
            'actor_role': item.actor_role,
            'actor_label': actor_label_map.get(item.actor_role, 'Пользователь'),
            'username': username,
            'method': item.method,
            'endpoint': item.endpoint,
            'action': item.action,
            'action_label': action_label_map.get(item.action, item.action.replace('_', ' ')),
            'success': item.success,
            'status_code': item.status_code,
            'before_human': _humanize_payload(item.before_data),
            'after_human': _humanize_payload(item.after_data),
            'before_json': json.dumps(item.before_data or {}, ensure_ascii=False, indent=2),
            'after_json': json.dumps(item.after_data or {}, ensure_ascii=False, indent=2),
        })

    return render(request, 'accounts/admin_panel.html', {
        'admin_profile': request.user.admin_profile,
        'stats': stats,
        'backups': backups,
        'audit_logs': audit_logs,
        'logs_page_obj': logs_page_obj,
    })


def _admin_user_role(user_obj):
    if is_admin_user(user_obj):
        return 'admin'
    if hasattr(user_obj, 'manager'):
        return 'manager'
    if hasattr(user_obj, 'applicant'):
        return 'applicant'
    return 'user'


def _admin_set_user_role(target_user, new_role):
    """Set user role from admin panel while preserving contact data where possible."""
    if new_role not in ('admin', 'manager', 'applicant'):
        return False, 'invalid_role'

    applicant = Applicant.objects.filter(user=target_user).first()
    manager = Manager.objects.filter(user=target_user).first()

    if new_role == 'admin':
        if not target_user.is_superuser:
            target_user.is_superuser = True
            target_user.save(update_fields=['is_superuser'])
        Administrator.objects.get_or_create(user=target_user)
        return True, 'role_updated'

    # Demote from admin when switching to business roles.
    if target_user.is_superuser:
        target_user.is_superuser = False
        target_user.save(update_fields=['is_superuser'])
    Administrator.objects.filter(user=target_user).delete()

    if new_role == 'manager':
        if manager:
            return True, 'role_updated'
        manager = Manager(user=target_user)
        if applicant:
            manager.patronymic = applicant.patronymic
            manager.phone = applicant.phone
            manager.telegram = applicant.telegram
            if applicant.avatar:
                manager.avatar = applicant.avatar.name
            if applicant.manager_company_logo:
                manager.company_logo = applicant.manager_company_logo
            if not applicant.was_manager:
                applicant.was_manager = True
                applicant.save(update_fields=['was_manager'])
        manager.save()
        return True, 'role_updated'

    # new_role == 'applicant'
    applicant, _ = Applicant.objects.get_or_create(
        user=target_user,
        defaults={
            'telegram': manager.telegram if manager and manager.telegram else f'@{target_user.username}',
            'phone': manager.phone if manager else '',
            'patronymic': manager.patronymic if manager else '',
            'city': '',
        },
    )
    if manager:
        changed_fields = []
        if manager.avatar and not applicant.avatar:
            applicant.avatar = manager.avatar.name
            changed_fields.append('avatar')
        if manager.company_logo:
            applicant.manager_company_logo = manager.company_logo.name
            changed_fields.append('manager_company_logo')
        if changed_fields:
            applicant.save(update_fields=changed_fields)
        manager.delete()
    return True, 'role_updated'


@admin_required
def admin_users(request):
    """Admin page to manage users: list/paginate/edit contacts/delete/switch role."""
    q = (request.GET.get('q') or '').strip()
    page_num = request.GET.get('page') or '1'
    status = (request.GET.get('status') or '').strip()
    status_text_map = {
        'saved': 'Данные пользователя сохранены.',
        'deleted': 'Пользователь удален.',
        'role_changed': 'Роль пользователя изменена.',
        'invalid_user': 'Некорректный идентификатор пользователя.',
        'not_found': 'Пользователь не найден.',
        'cannot_delete_self': 'Нельзя удалить собственный аккаунт.',
        'email_exists': 'Пользователь с таким email уже существует.',
        'telegram_exists': 'Пользователь с таким Telegram уже существует.',
        'invalid_telegram': 'Telegram должен начинаться с @.',
        'invalid_role': 'Недопустимая роль.',
        'unknown_action': 'Неизвестное действие.',
    }
    status_text = status_text_map.get(status, '')

    def _redirect_with_status(code):
        params = {'status': code}
        if q:
            params['q'] = q
        if page_num:
            params['page'] = page_num
        return redirect(reverse('accounts:admin_users') + '?' + urlencode(params))

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()
        try:
            user_id = int(request.POST.get('user_id') or '0')
        except ValueError:
            return _redirect_with_status('invalid_user')
        target_user = User.objects.filter(pk=user_id).first()
        if not target_user:
            return _redirect_with_status('not_found')

        if action == 'delete':
            if target_user.pk == request.user.pk:
                return _redirect_with_status('cannot_delete_self')
            before = {
                'user_id': target_user.pk,
                'username': target_user.username,
                'role': _admin_user_role(target_user),
            }
            Applicant.objects.filter(user=target_user).delete()
            Manager.objects.filter(user=target_user).delete()
            Administrator.objects.filter(user=target_user).delete()
            target_user.delete()
            _log_api_action(
                request,
                action='admin_user_delete',
                before=before,
                after={'deleted': True},
                success=True,
                status_code=200,
                endpoint='admin_users',
            )
            return _redirect_with_status('deleted')

        if action == 'save':
            first_name = (request.POST.get('first_name') or '').strip()
            last_name = (request.POST.get('last_name') or '').strip()
            email = (request.POST.get('email') or '').strip().lower()
            patronymic = (request.POST.get('patronymic') or '').strip()
            phone = (request.POST.get('phone') or '').strip()
            telegram = (request.POST.get('telegram') or '').strip()
            city = (request.POST.get('city') or '').strip()
            company = (request.POST.get('company') or '').strip()

            if email and User.objects.filter(email__iexact=email).exclude(pk=target_user.pk).exists():
                return _redirect_with_status('email_exists')
            if telegram and not telegram.startswith('@'):
                return _redirect_with_status('invalid_telegram')
            if telegram and (
                Applicant.objects.filter(telegram__iexact=telegram).exclude(user=target_user).exists()
                or Manager.objects.filter(telegram__iexact=telegram).exclude(user=target_user).exists()
            ):
                return _redirect_with_status('telegram_exists')

            before = {
                'user_id': target_user.pk,
                'first_name': target_user.first_name,
                'last_name': target_user.last_name,
                'email': target_user.email,
            }

            target_user.first_name = first_name
            target_user.last_name = last_name
            if email:
                target_user.email = email
            target_user.save(update_fields=['first_name', 'last_name', 'email'])

            applicant = Applicant.objects.filter(user=target_user).first()
            manager = Manager.objects.filter(user=target_user).first()

            if applicant:
                app_updates = []
                applicant.patronymic = patronymic
                app_updates.append('patronymic')
                applicant.phone = phone
                app_updates.append('phone')
                if telegram:
                    applicant.telegram = telegram
                    app_updates.append('telegram')
                applicant.city = city
                app_updates.append('city')
                applicant.save(update_fields=app_updates)

            # For non-admin users, allow editing manager fields in the same form
            # even if they did not have a manager profile yet.
            if (not is_admin_user(target_user)) and not manager:
                manager = Manager.objects.create(
                    user=target_user,
                    patronymic=patronymic,
                    phone=phone,
                    telegram=telegram or '',
                    company=company,
                )

            if manager:
                mgr_updates = []
                manager.patronymic = patronymic
                mgr_updates.append('patronymic')
                manager.phone = phone
                mgr_updates.append('phone')
                manager.telegram = telegram or manager.telegram
                mgr_updates.append('telegram')
                manager.company = company
                mgr_updates.append('company')
                manager.save(update_fields=mgr_updates)

            _log_api_action(
                request,
                action='admin_user_contacts_update',
                before=before,
                after={
                    'user_id': target_user.pk,
                    'first_name': target_user.first_name,
                    'last_name': target_user.last_name,
                    'email': target_user.email,
                    'phone': phone,
                    'telegram': telegram,
                    'city': city,
                    'company': company,
                },
                success=True,
                status_code=200,
                endpoint='admin_users',
            )
            return _redirect_with_status('saved')

        if action == 'change_role':
            new_role = (request.POST.get('new_role') or '').strip()
            old_role = _admin_user_role(target_user)
            ok, code = _admin_set_user_role(target_user, new_role)
            _log_api_action(
                request,
                action='admin_user_role_change',
                before={'user_id': target_user.pk, 'from_role': old_role},
                after={'to_role': new_role, 'result': code},
                success=ok,
                status_code=200 if ok else 400,
                endpoint='admin_users',
            )
            return _redirect_with_status('role_changed' if ok else code)

        return _redirect_with_status('unknown_action')

    users_qs = User.objects.select_related('applicant', 'manager').order_by('-date_joined')
    if q:
        users_qs = users_qs.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(applicant__phone__icontains=q)
            | Q(manager__phone__icontains=q)
            | Q(applicant__telegram__icontains=q)
            | Q(manager__telegram__icontains=q)
        ).distinct()

    paginator = Paginator(users_qs, 20)
    page_obj = paginator.get_page(page_num)

    rows = []
    for u in page_obj.object_list:
        applicant = getattr(u, 'applicant', None)
        manager = getattr(u, 'manager', None)
        role = _admin_user_role(u)
        role_label = {
            'admin': 'Администратор',
            'manager': 'Менеджер',
            'applicant': 'Соискатель',
            'user': 'Пользователь',
        }.get(role, 'Пользователь')
        rows.append({
            'user': u,
            'role': role,
            'role_label': role_label,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'email': u.email,
            'patronymic': (applicant.patronymic if applicant else (manager.patronymic if manager else '')),
            'phone': (applicant.phone if applicant else (manager.phone if manager else '')),
            'telegram': (applicant.telegram if applicant else (manager.telegram if manager else '')),
            'city': (applicant.city if applicant else ''),
            'company': (manager.company if manager else ''),
            'is_self': (u.pk == request.user.pk),
        })

    return render(request, 'accounts/admin_users.html', {
        'rows': rows,
        'page_obj': page_obj,
        'q': q,
        'status': status,
        'status_text': status_text,
    })


@admin_required
def admin_profile_page(request):
    """Admin profile page is intentionally disabled; keep admins in control panel."""
    return redirect('accounts:admin_panel')


@admin_required
def api_admin_backup_create(request):
    """POST — create an immediate database backup; return filename and size."""
    if request.method != 'POST':
        _log_api_action(
            request,
            action='backup_create',
            after={'error': 'method_not_allowed'},
            success=False,
            status_code=405,
            endpoint='api_admin_backup_create',
        )
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    import sqlite3 as _sqlite3
    from contextlib import closing as _closing
    from pathlib import Path as _Path
    from datetime import datetime as _dt
    from django.conf import settings as _cfg

    db_path    = _Path(_cfg.DATABASES['default']['NAME'])
    backup_dir = _Path(getattr(_cfg, 'BACKUP_DIR', db_path.parent / 'backups'))
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp   = _dt.now().strftime('%Y%m%d_%H%M%S')
    backup_path = backup_dir / f'db_backup_{timestamp}.sqlite3'

    try:
        with _closing(_sqlite3.connect(str(db_path))) as src:
            with _closing(_sqlite3.connect(str(backup_path))) as dst:
                src.backup(dst)
    except Exception as exc:
        _log_api_action(
            request,
            action='backup_create',
            after={'error': str(exc)},
            success=False,
            status_code=500,
            endpoint='api_admin_backup_create',
        )
        return JsonResponse({'error': str(exc)}, status=500)

    # Rotation
    max_count = getattr(_cfg, 'DB_BACKUP_MAX_COUNT', 3)
    existing  = sorted(backup_dir.glob('db_backup_*.sqlite3'))
    while len(existing) > max_count:
        existing[0].unlink()
        existing = existing[1:]

    _log_api_action(
        request,
        action='backup_create',
        after={'filename': backup_path.name, 'size_kb': round(backup_path.stat().st_size / 1024, 1)},
        success=True,
        status_code=200,
        endpoint='api_admin_backup_create',
    )
    return JsonResponse({
        'ok':       True,
        'filename': backup_path.name,
        'size_kb':  round(backup_path.stat().st_size / 1024, 1),
    })


@admin_required
def api_admin_backup_restore(request):
    """POST {filename} — restore the SQLite database from a named backup file.

    Only plain filenames matching the expected pattern are accepted to prevent
    path-traversal attacks.  A safety snapshot of the current database is
    written to the backup directory before overwriting.
    """
    import sqlite3 as _sqlite3
    from contextlib import closing as _closing
    import shutil as _shutil
    from pathlib import Path as _Path
    from django.conf import settings as _cfg
    from django.db import connections as _connections

    if request.method != 'POST':
        _log_api_action(
            request,
            action='backup_restore',
            after={'error': 'method_not_allowed'},
            success=False,
            status_code=405,
            endpoint='api_admin_backup_restore',
        )
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        _log_api_action(
            request,
            action='backup_restore',
            after={'error': 'invalid_json'},
            success=False,
            status_code=400,
            endpoint='api_admin_backup_restore',
        )
        return JsonResponse({'error': 'invalid_json'}, status=400)

    filename = (data.get('filename') or '').strip()
    # Path-traversal guard: only allow the exact backup filename format.
    if not filename or not re.fullmatch(r'db_backup_[0-9]{8}_[0-9]{6}\.sqlite3', filename):
        _log_api_action(
            request,
            action='backup_restore',
            after={'error': 'invalid_filename', 'filename': filename},
            success=False,
            status_code=400,
            endpoint='api_admin_backup_restore',
        )
        return JsonResponse({'error': 'invalid_filename'}, status=400)

    db_path    = _Path(_cfg.DATABASES['default']['NAME'])
    backup_dir = _Path(getattr(_cfg, 'BACKUP_DIR', db_path.parent / 'backups'))
    backup_path = backup_dir / filename

    if not backup_path.exists():
        _log_api_action(
            request,
            action='backup_restore',
            after={'error': 'not_found', 'filename': filename},
            success=False,
            status_code=404,
            endpoint='api_admin_backup_restore',
        )
        return JsonResponse({'error': 'not_found'}, status=404)

    # Close all active DB connections before replacing the underlying file.
    for _conn in _connections.all():
        try:
            _conn.close()
        except Exception:
            pass

    # Safety snapshot so the admin can undo if needed.
    safety = backup_dir / f'before_restore_{filename}'
    try:
        _shutil.copy2(str(db_path), str(safety))
    except Exception:
        pass

    try:
        with _closing(_sqlite3.connect(str(backup_path))) as src:
            with _closing(_sqlite3.connect(str(db_path))) as dst:
                src.backup(dst)
    except Exception as exc:
        try:
            _shutil.copy2(str(safety), str(db_path))
        except Exception:
            pass
        _log_api_action(
            request,
            action='backup_restore',
            before={'filename': filename},
            after={'error': f'restore_failed: {exc}'},
            success=False,
            status_code=500,
            endpoint='api_admin_backup_restore',
        )
        return JsonResponse({'error': f'restore_failed: {exc}'}, status=500)

    _log_api_action(
        request,
        action='backup_restore',
        before={'filename': filename},
        after={'restored_from': filename, 'safety_snapshot': safety.name},
        success=True,
        status_code=200,
        endpoint='api_admin_backup_restore',
    )
    return JsonResponse({'ok': True, 'restored_from': filename})


@admin_required
def api_admin_backup_delete(request):
    """POST {filename} — delete a named backup file.

    Only filenames matching the expected pattern are accepted to prevent
    path-traversal attacks.
    """
    from pathlib import Path as _Path
    from django.conf import settings as _cfg

    if request.method != 'POST':
        _log_api_action(
            request,
            action='backup_delete',
            after={'error': 'method_not_allowed'},
            success=False,
            status_code=405,
            endpoint='api_admin_backup_delete',
        )
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        _log_api_action(
            request,
            action='backup_delete',
            after={'error': 'invalid_json'},
            success=False,
            status_code=400,
            endpoint='api_admin_backup_delete',
        )
        return JsonResponse({'error': 'invalid_json'}, status=400)

    filename = (data.get('filename') or '').strip()
    if not filename or not re.fullmatch(r'db_backup_[0-9]{8}_[0-9]{6}\.sqlite3', filename):
        _log_api_action(
            request,
            action='backup_delete',
            after={'error': 'invalid_filename', 'filename': filename},
            success=False,
            status_code=400,
            endpoint='api_admin_backup_delete',
        )
        return JsonResponse({'error': 'invalid_filename'}, status=400)

    db_path    = _Path(_cfg.DATABASES['default']['NAME'])
    backup_dir = _Path(getattr(_cfg, 'BACKUP_DIR', db_path.parent / 'backups'))
    backup_path = backup_dir / filename

    if not backup_path.exists():
        _log_api_action(
            request,
            action='backup_delete',
            before={'filename': filename},
            after={'error': 'not_found'},
            success=False,
            status_code=404,
            endpoint='api_admin_backup_delete',
        )
        return JsonResponse({'error': 'not_found'}, status=404)

    try:
        backup_path.unlink()
    except Exception as exc:
        _log_api_action(
            request,
            action='backup_delete',
            before={'filename': filename},
            after={'error': str(exc)},
            success=False,
            status_code=500,
            endpoint='api_admin_backup_delete',
        )
        return JsonResponse({'error': str(exc)}, status=500)

    _log_api_action(
        request,
        action='backup_delete',
        before={'filename': filename},
        after={'deleted': filename},
        success=True,
        status_code=200,
        endpoint='api_admin_backup_delete',
    )
    return JsonResponse({'ok': True, 'deleted': filename})


# ─────────────────────────────────────────────────────────────
#  Chat views
# ─────────────────────────────────────────────────────────────

@login_required
def chat_list(request):
    """All chats the current user participates in (excluding ones they deleted)."""
    user = request.user
    chats = (
        Chat.objects
        .filter(
            Q(manager=user,   deleted_by_manager=False) |
            Q(applicant=user, deleted_by_applicant=False)
        )
        .select_related('manager', 'applicant',
                        'manager__manager', 'applicant__applicant')
        .prefetch_related('messages')
        .order_by('-created_at')
    )
    chat_data = []
    for chat in chats:
        is_manager = (user == chat.manager)
        other = chat.applicant if is_manager else chat.manager
        other_deleted = chat.deleted_by_applicant if is_manager else chat.deleted_by_manager
        last_msg = chat.messages.last()
        unread = chat.messages.filter(is_read=False).exclude(sender=user).count()
        profile = getattr(other, 'applicant', None) or getattr(other, 'manager', None)
        other_avatar_url = profile.avatar.url if profile and profile.avatar else ''
        chat_data.append({
            'chat':            chat,
            'other':           other,
            'last_msg':        last_msg,
            'unread':          unread,
            'other_deleted':   other_deleted,
            'other_avatar_url': other_avatar_url,
        })
    return render(request, 'accounts/chat_list.html', {'chat_data': chat_data})


@login_required
def chat_detail(request, pk):
    """Single chat thread – only accessible by the participant who has NOT deleted it."""
    from django.shortcuts import get_object_or_404
    from django.http import Http404
    user = request.user
    chat = get_object_or_404(
        Chat.objects.select_related('manager', 'applicant',
                                    'manager__manager', 'applicant__applicant'),
        Q(manager=user) | Q(applicant=user),
        pk=pk,
    )
    is_manager = (user == chat.manager)
    # If this user already soft-deleted the chat, they shouldn't see it
    if (is_manager and chat.deleted_by_manager) or (not is_manager and chat.deleted_by_applicant):
        raise Http404
    # Mark all incoming messages as read
    chat.messages.filter(is_read=False).exclude(sender=user).update(is_read=True)
    messages_qs = chat.messages.select_related('sender').order_by('created_at')
    other = chat.applicant if is_manager else chat.manager
    other_deleted = chat.deleted_by_applicant if is_manager else chat.deleted_by_manager
    profile = getattr(other, 'applicant', None) or getattr(other, 'manager', None)
    other_avatar_url = profile.avatar.url if profile and profile.avatar else ''
    # Most recent application from this applicant on any of the manager's vacancies
    application = None
    if is_manager:
        application = (
            Application.objects
            .filter(applicant=other, vacancy__created_by=user)
            .order_by('-created_at')
            .first()
        )
    return render(request, 'accounts/chat_detail.html', {
        'chat':             chat,
        'messages':         messages_qs,
        'other':            other,
        'other_deleted':    other_deleted,
        'is_manager':       is_manager,
        'other_avatar_url': other_avatar_url,
        'application':      application,
    })


@swagger_auto_schema(method='post', operation_summary="Начать чат с соискателем", tags=['accounts'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_chat_start(request):
    """Manager starts (or reopens) a chat with an applicant."""
    import django.db.models as _m
    user = request.user
    if not hasattr(user, 'manager'):
        return JsonResponse({'error': 'only_managers'}, status=403)
    applicant_user_id = (request.data or {}).get('applicant_user_id')
    if not applicant_user_id:
        return JsonResponse({'error': 'applicant_user_id_required'}, status=400)
    try:
        applicant_user = User.objects.get(pk=applicant_user_id)
    except User.DoesNotExist:
        return JsonResponse({'error': 'not_found'}, status=404)
    if not hasattr(applicant_user, 'applicant'):
        return JsonResponse({'error': 'target_not_applicant'}, status=400)
    chat, created = Chat.objects.get_or_create(manager=user, applicant=applicant_user)
    # If manager had previously deleted this chat, restore their view
    if not created and chat.deleted_by_manager:
        chat.deleted_by_manager = False
        chat.save(update_fields=['deleted_by_manager'])
    return JsonResponse({'ok': True, 'chat_id': chat.pk})


@swagger_auto_schema(method='post', operation_summary="Отправить сообщение в чат", tags=['accounts'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_chat_send(request, pk):
    """Send a message (text and/or file attachment) in a chat."""
    from django.shortcuts import get_object_or_404
    user = request.user
    chat = get_object_or_404(
        Chat,
        Q(manager=user) | Q(applicant=user),
        pk=pk,
    )
    is_manager = (user == chat.manager)
    # Block if the *other* side deleted the chat
    other_deleted = chat.deleted_by_applicant if is_manager else chat.deleted_by_manager
    if other_deleted:
        return JsonResponse({'error': 'other_deleted'}, status=403)

    # Support both JSON (text-only) and multipart/form-data (file + optional text)
    data = request.data or {}
    text = (data.get('text') or '').strip()
    uploaded_file = request.FILES.get('file')

    if not text and not uploaded_file:
        return JsonResponse({'error': 'empty'}, status=400)
    if text and len(text) > 4000:
        return JsonResponse({'error': 'too_long'}, status=400)
    if uploaded_file and uploaded_file.size > 20 * 1024 * 1024:   # 20 MB cap
        return JsonResponse({'error': 'file_too_large'}, status=400)

    msg = Message.objects.create(chat=chat, sender=user, text=text,
                                  file=uploaded_file or None)

    # Build file info for the response
    file_url  = msg.file.url  if msg.file else None
    file_name = msg.file.name.split('/')[-1] if msg.file else None

    # Notify the recipient about the new message (fire-and-forget)
    recipient   = chat.applicant if is_manager else chat.manager
    sender_name = user.get_full_name() or user.username
    notify_new_chat_message(recipient, sender_name, text or f'[{file_name}]', chat.pk)

    return JsonResponse({
        'ok': True,
        'message': {
            'id':         msg.pk,
            'text':       msg.text,
            'file_url':   file_url,
            'file_name':  file_name,
            'sender_id':  msg.sender_id,
            'created_at': msg.created_at.strftime('%d.%m.%Y %H:%M'),
            'is_mine':    True,
        }
    })


@swagger_auto_schema(method='get', operation_summary="Получить новые сообщения чата", tags=['accounts'])
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_chat_messages(request, pk):
    """Poll new messages since a given id."""
    from django.shortcuts import get_object_or_404
    user = request.user
    chat = get_object_or_404(
        Chat,
        Q(manager=user) | Q(applicant=user),
        pk=pk,
    )
    since_id = int(request.GET.get('since', 0))
    msgs = chat.messages.filter(pk__gt=since_id).select_related('sender').order_by('created_at')
    # mark incoming as read
    msgs.filter(is_read=False).exclude(sender=user).update(is_read=True)
    return JsonResponse({
        'ok': True,
        'messages': [
            {
                'id':          m.pk,
                'text':        m.text,
                'file_url':    m.file.url  if m.file else None,
                'file_name':   m.file.name.split('/')[-1] if m.file else None,
                'sender_id':   m.sender_id,
                'sender_name': m.sender.get_full_name() or m.sender.username,
                'created_at':  m.created_at.strftime('%d.%m.%Y %H:%M'),
                'is_mine':     m.sender_id == user.pk,
            }
            for m in msgs
        ]
    })


@swagger_auto_schema(method='delete', operation_summary="Удалить чат", tags=['accounts'])
@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def api_chat_delete(request, pk):
    """Soft-delete a chat for the requesting user.
    If both sides have deleted it, the record is hard-deleted."""
    from django.shortcuts import get_object_or_404
    user = request.user
    chat = get_object_or_404(
        Chat,
        Q(manager=user) | Q(applicant=user),
        pk=pk,
    )
    if user == chat.manager:
        chat.deleted_by_manager = True
        chat.save(update_fields=['deleted_by_manager'])
    else:
        chat.deleted_by_applicant = True
        chat.save(update_fields=['deleted_by_applicant'])
    # Hard-delete only when both sides have dismissed it
    if chat.deleted_by_manager and chat.deleted_by_applicant:
        chat.delete()
    return JsonResponse({'ok': True})


@swagger_auto_schema(method='post', operation_summary="Сменить роль", tags=['accounts'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_switch_role(request):
    """Toggle current user between applicant and manager roles."""
    user = request.user
    before_role = 'manager' if Manager.objects.filter(user=user).exists() else 'applicant'
    manager = Manager.objects.filter(user=user).first()
    if manager:
        # Manager → Applicant: check for conflicts with existing Applicant records
        if manager.phone:
            if Applicant.objects.filter(phone=manager.phone).exclude(user=user).exists():
                _log_api_action(
                    request,
                    action='switch_role',
                    before={'from_role': before_role},
                    after={'error': 'phone_conflict'},
                    success=False,
                    status_code=400,
                    endpoint='api_switch_role',
                )
                return JsonResponse({'error': 'phone_conflict'}, status=400)
        if manager.telegram:
            if Applicant.objects.filter(telegram=manager.telegram).exclude(user=user).exists():
                _log_api_action(
                    request,
                    action='switch_role',
                    before={'from_role': before_role},
                    after={'error': 'telegram_conflict'},
                    success=False,
                    status_code=400,
                    endpoint='api_switch_role',
                )
                return JsonResponse({'error': 'telegram_conflict'}, status=400)

        # Manager → Applicant: remove Manager record
        # Preserve avatar AND company logo path on the applicant record before deleting manager
        applicant, _ = Applicant.objects.get_or_create(user=user)
        applicant_changed = []
        if manager.avatar and not applicant.avatar:
            applicant.avatar = manager.avatar.name   # string assignment preserves file on disk
            applicant_changed.append('avatar')
        if manager.company_logo:
            applicant.manager_company_logo = manager.company_logo.name
            applicant_changed.append('manager_company_logo')
        if applicant_changed:
            applicant.save(update_fields=applicant_changed)
        manager.delete()
        new_role = 'applicant'
    else:
        # Applicant → Manager: check for conflicts with existing Manager records
        applicant = Applicant.objects.filter(user=user).first()
        if applicant:
            if applicant.phone:
                if Manager.objects.filter(phone=applicant.phone).exists():
                    _log_api_action(
                        request,
                        action='switch_role',
                        before={'from_role': before_role},
                        after={'error': 'phone_conflict'},
                        success=False,
                        status_code=400,
                        endpoint='api_switch_role',
                    )
                    return JsonResponse({'error': 'phone_conflict'}, status=400)
            if applicant.telegram:
                if Manager.objects.filter(telegram=applicant.telegram).exists():
                    _log_api_action(
                        request,
                        action='switch_role',
                        before={'from_role': before_role},
                        after={'error': 'telegram_conflict'},
                        success=False,
                        status_code=400,
                        endpoint='api_switch_role',
                    )
                    return JsonResponse({'error': 'telegram_conflict'}, status=400)

        m = Manager(user=user)
        if applicant:
            m.patronymic = applicant.patronymic
            m.phone      = applicant.phone
            m.telegram   = applicant.telegram
            # Carry personal avatar path to the new manager record
            if applicant.avatar:
                m.avatar = applicant.avatar.name  # string assignment
            # Restore previously saved company logo path (survives role switches)
            if applicant.manager_company_logo:
                m.company_logo = applicant.manager_company_logo
            # Remember that this applicant has been a manager
            if not applicant.was_manager:
                applicant.was_manager = True
                applicant.save(update_fields=['was_manager'])
        m.save()
        new_role = 'manager'
    _log_api_action(
        request,
        action='switch_role',
        before={'from_role': before_role},
        after={'to_role': new_role},
        success=True,
        status_code=200,
        endpoint='api_switch_role',
    )
    return JsonResponse({'ok': True, 'role': new_role})


@swagger_auto_schema(method='post', operation_summary="Добавить запись об образовании", tags=['accounts'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_education_create(request):
    applicant = Applicant.objects.filter(user=request.user).first()
    if not applicant:
        return JsonResponse({'error': 'no_applicant'}, status=403)
    data = request.data or {}
    institution = (data.get('institution') or '').strip()
    if not institution:
        return JsonResponse({'error': 'institution_required'}, status=400)
    level = (data.get('level') or '').strip()
    VALID = {c[0] for c in Education.LEVEL_CHOICES}
    if level not in VALID:
        return JsonResponse({'error': 'invalid_level'}, status=400)
    try:
        grad_year = int(data['graduation_year']) if data.get('graduation_year') else None
    except (ValueError, TypeError):
        grad_year = None
    order = applicant.educations.count()
    edu = Education.objects.create(
        applicant=applicant, level=level, institution=institution,
        graduation_year=grad_year,
        faculty=(data.get('faculty') or '').strip(),
        specialization=(data.get('specialization') or '').strip(),
        order=order,
    )
    return JsonResponse({
        'ok': True, 'id': edu.pk, 'level': edu.level,
        'level_display': edu.get_level_display(),
        'institution': edu.institution, 'graduation_year': edu.graduation_year,
        'faculty': edu.faculty, 'specialization': edu.specialization,
    })


@swagger_auto_schema(methods=['patch'], operation_summary="Обновить запись об образовании", tags=['accounts'])
@swagger_auto_schema(methods=['delete'], operation_summary="Удалить запись об образовании", tags=['accounts'])
@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def api_education_crud(request, pk):
    edu = Education.objects.filter(pk=pk, applicant__user=request.user).first()
    if not edu:
        return JsonResponse({'error': 'not_found'}, status=404)
    if request.method == 'DELETE':
        edu.delete()
        return JsonResponse({'ok': True})
    data = request.data or {}
    VALID = {c[0] for c in Education.LEVEL_CHOICES}
    if 'institution' in data:
        val = (data.get('institution') or '').strip()
        if not val:
            return JsonResponse({'error': 'institution_required'}, status=400)
        edu.institution = val
    if 'level' in data:
        lvl = (data.get('level') or '').strip()
        if lvl not in VALID:
            return JsonResponse({'error': 'invalid_level'}, status=400)
        edu.level = lvl
    if 'graduation_year' in data:
        try:
            edu.graduation_year = int(data['graduation_year']) if data['graduation_year'] else None
        except (ValueError, TypeError):
            pass
    for f in ('faculty', 'specialization'):
        if f in data:
            setattr(edu, f, (data.get(f) or '').strip())
    edu.save()
    return JsonResponse({
        'ok': True, 'id': edu.pk, 'level': edu.level,
        'level_display': edu.get_level_display(),
        'institution': edu.institution, 'graduation_year': edu.graduation_year,
        'faculty': edu.faculty, 'specialization': edu.specialization,
    })


@swagger_auto_schema(method='post', operation_summary="Добавить запись о дополнительном образовании", tags=['accounts'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_extra_edu_create(request):
    applicant = Applicant.objects.filter(user=request.user).first()
    if not applicant:
        return JsonResponse({'error': 'no_applicant'}, status=403)
    data = request.data or {}
    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'error': 'name_required'}, status=400)
    order = applicant.extra_educations.count()
    obj = ExtraEducation.objects.create(
        applicant=applicant,
        name=name,
        description=(data.get('description') or '').strip(),
        order=order,
    )
    return JsonResponse({'ok': True, 'id': obj.pk, 'name': obj.name, 'description': obj.description})


@swagger_auto_schema(methods=['patch'], operation_summary="Обновить запись о дополнительном образовании", tags=['accounts'])
@swagger_auto_schema(methods=['delete'], operation_summary="Удалить запись о дополнительном образовании", tags=['accounts'])
@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def api_extra_edu_crud(request, pk):
    obj = ExtraEducation.objects.filter(pk=pk, applicant__user=request.user).first()
    if not obj:
        return JsonResponse({'error': 'not_found'}, status=404)
    if request.method == 'DELETE':
        obj.delete()
        return JsonResponse({'ok': True})
    data = request.data or {}
    if 'name' in data:
        val = (data.get('name') or '').strip()
        if not val:
            return JsonResponse({'error': 'name_required'}, status=400)
        obj.name = val
    if 'description' in data:
        obj.description = (data.get('description') or '').strip()
    obj.save()
    return JsonResponse({'ok': True, 'id': obj.pk, 'name': obj.name, 'description': obj.description})


@swagger_auto_schema(method='post', operation_summary="Добавить место работы", tags=['accounts'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_work_create(request):
    applicant = Applicant.objects.filter(user=request.user).first()
    if not applicant:
        return JsonResponse({'error': 'no_applicant'}, status=403)
    data = request.data or {}
    company  = (data.get('company') or '').strip()
    position = (data.get('position') or '').strip()
    if not company or not position:
        return JsonResponse({'error': 'company_position_required'}, status=400)

    def _si(v):
        try:
            return int(v) if v else None
        except (ValueError, TypeError):
            return None

    order = applicant.work_experiences.count()
    is_cur = bool(data.get('is_current'))
    w = WorkExperience.objects.create(
        applicant=applicant, company=company, position=position,
        start_month=_si(data.get('start_month')),
        start_year=_si(data.get('start_year')),
        end_month=None if is_cur else _si(data.get('end_month')),
        end_year=None if is_cur else _si(data.get('end_year')),
        is_current=is_cur,
        responsibilities=(data.get('responsibilities') or '').strip(),
        order=order,
    )
    return JsonResponse({
        'ok': True, 'id': w.pk, 'company': w.company, 'position': w.position,
        'start_month': w.start_month, 'start_year': w.start_year,
        'end_month': w.end_month, 'end_year': w.end_year,
        'is_current': w.is_current, 'responsibilities': w.responsibilities,
    })


@swagger_auto_schema(methods=['patch'], operation_summary="Обновить место работы", tags=['accounts'])
@swagger_auto_schema(methods=['delete'], operation_summary="Удалить место работы", tags=['accounts'])
@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def api_work_crud(request, pk):
    w = WorkExperience.objects.filter(pk=pk, applicant__user=request.user).first()
    if not w:
        return JsonResponse({'error': 'not_found'}, status=404)
    if request.method == 'DELETE':
        w.delete()
        return JsonResponse({'ok': True})
    data = request.data or {}

    def _si(v):
        try:
            return int(v) if v else None
        except (ValueError, TypeError):
            return None

    for f in ('company', 'position', 'responsibilities'):
        if f in data:
            setattr(w, f, (data.get(f) or '').strip())
    if 'is_current' in data:
        w.is_current = bool(data['is_current'])
    for f in ('start_month', 'start_year', 'end_month', 'end_year'):
        if f in data:
            setattr(w, f, _si(data[f]))
    if w.is_current:
        w.end_month = None
        w.end_year = None
    w.save()
    return JsonResponse({
        'ok': True, 'id': w.pk, 'company': w.company, 'position': w.position,
        'start_month': w.start_month, 'start_year': w.start_year,
        'end_month': w.end_month, 'end_year': w.end_year,
        'is_current': w.is_current, 'responsibilities': w.responsibilities,
    })


@swagger_auto_schema(method='put', operation_summary="Обновить список навыков", tags=['accounts'])
@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def api_skills_update(request):
    applicant = Applicant.objects.filter(user=request.user).first()
    if not applicant:
        return JsonResponse({'error': 'no_applicant'}, status=403)
    skills = (request.data or {}).get('skills', [])
    if not isinstance(skills, list):
        return JsonResponse({'error': 'invalid_skills'}, status=400)
    applicant.skills = [s.strip() for s in skills if isinstance(s, str) and s.strip()]
    applicant.save(update_fields=['skills'])
    return JsonResponse({'ok': True, 'skills': applicant.skills})


@swagger_auto_schema(method='post', operation_summary="Сохранить согласие на уведомления в Telegram", tags=['accounts'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_set_consent(request):
    # Accept boolean-like values from JSON or form
    try:
        val = request.data.get('consent_telegram')
    except Exception:
        # fallback
        val = None

    if isinstance(val, bool):
        consent = val
    else:
        consent = str(val).lower() in ('1', 'true', 'yes', 'on')

    applicant = Applicant.objects.filter(user=request.user).first()
    if applicant:
        applicant.consent_telegram = consent
        if not applicant.telegram_start_token:
            applicant.telegram_start_token = uuid.uuid4().hex
            applicant.save(update_fields=['consent_telegram', 'telegram_start_token'])
        else:
            applicant.save(update_fields=['consent_telegram'])
        bot_username = get_bot_username()
        bot_start_url = None
        if bot_username and applicant.telegram_start_token:
            bot_start_url = f'https://t.me/{bot_username}?start={applicant.telegram_start_token}'
        return JsonResponse({'ok': True, 'consent_telegram': applicant.consent_telegram, 'bot_start_url': bot_start_url})

    manager = Manager.objects.filter(user=request.user).first()
    if manager:
        manager.consent_telegram = consent
        manager.save(update_fields=['consent_telegram'])
        bot_start_url = None
        if consent:
            bot_username = get_bot_username()
            if bot_username:
                bot_start_url = f'https://t.me/{bot_username}'
        return JsonResponse({'ok': True, 'consent_telegram': manager.consent_telegram, 'bot_start_url': bot_start_url})

    return JsonResponse({'error': 'no_profile'}, status=400)


@swagger_auto_schema(method='post', operation_summary="Отправить тестовое уведомление в Telegram", tags=['accounts'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_test_message(request):
    applicant = Applicant.objects.filter(user=request.user).first()
    if applicant:
        if not applicant.consent_telegram:
            return JsonResponse({'error': 'no_consent'}, status=400)
        if not applicant.telegram_chat_id and applicant.telegram_start_token:
            chat_id = resolve_chat_id_by_token(applicant.telegram_start_token)
            if chat_id:
                applicant.telegram_chat_id = chat_id
                applicant.save(update_fields=['telegram_chat_id'])
        if not applicant.telegram_chat_id:
            return JsonResponse({'error': 'chat_id_missing'}, status=400)
        send_hello_async(applicant.telegram_chat_id,
                         text='Это тестовое сообщение от JobFlex. Уведомления работают корректно.')
        return JsonResponse({'ok': True})

    manager = Manager.objects.filter(user=request.user).first()
    if manager:
        if not manager.consent_telegram:
            return JsonResponse({'error': 'no_consent'}, status=400)
        if not manager.telegram_chat_id:
            return JsonResponse({'error': 'chat_id_missing'}, status=400)
        send_hello_async(manager.telegram_chat_id,
                         text='Это тестовое сообщение от JobFlex. Уведомления работают корректно.')
        return JsonResponse({'ok': True})

    return JsonResponse({'error': 'no_profile'}, status=400)


@swagger_auto_schema(method='post', operation_summary="Открепить Telegram", tags=['accounts'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_unlink_telegram(request):
    applicant = Applicant.objects.filter(user=request.user).first()
    if applicant:
        applicant.telegram_chat_id = None
        applicant.consent_telegram = False
        applicant.save(update_fields=['telegram_chat_id', 'consent_telegram'])
        return JsonResponse({'ok': True})

    manager = Manager.objects.filter(user=request.user).first()
    if manager:
        manager.telegram_chat_id = None
        manager.consent_telegram = False
        manager.save(update_fields=['telegram_chat_id', 'consent_telegram'])
        return JsonResponse({'ok': True})

    return JsonResponse({'error': 'no_profile'}, status=400)


# ──────────────────── Email notification endpoints ────────────────────────

@swagger_auto_schema(method='post', operation_summary="Сохранить согласие на уведомления по электронной почте", tags=['accounts'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_set_email_consent(request):
    try:
        val = request.data.get('consent_email')
    except Exception:
        val = None

    if isinstance(val, bool):
        consent = val
    else:
        consent = str(val).lower() in ('1', 'true', 'yes', 'on')

    applicant = Applicant.objects.filter(user=request.user).first()
    if applicant:
        applicant.consent_email = consent
        applicant.save(update_fields=['consent_email'])
        return JsonResponse({'ok': True, 'consent_email': applicant.consent_email})

    manager = Manager.objects.filter(user=request.user).first()
    if manager:
        manager.consent_email = consent
        manager.save(update_fields=['consent_email'])
        return JsonResponse({'ok': True, 'consent_email': manager.consent_email})

    return JsonResponse({'error': 'no_profile'}, status=400)


@swagger_auto_schema(method='post', operation_summary="Отправить тестовое письмо", tags=['accounts'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_test_email(request):
    # Resolve consent flag from whichever profile the caller has
    _has_consent = False
    applicant = Applicant.objects.filter(user=request.user).first()
    if applicant:
        _has_consent = applicant.consent_email
    else:
        manager = Manager.objects.filter(user=request.user).first()
        if manager:
            _has_consent = manager.consent_email
        else:
            return JsonResponse({'error': 'no_profile'}, status=400)
    if not _has_consent:
        return JsonResponse({'error': 'no_consent'}, status=400)

    email_address = request.user.email
    if not email_address:
        return JsonResponse({'error': 'no_email'}, status=400)

    # Guard: email backend must be configured with credentials
    host_user = django_settings.EMAIL_HOST_USER
    if not host_user and django_settings.EMAIL_BACKEND == 'django.core.mail.backends.smtp.EmailBackend':
        return JsonResponse({'error': 'email_not_configured',
                             'detail': 'EMAIL_HOST_USER is not set in .env'}, status=503)

    # Mail.ru (and most SMTP providers) require From == authenticated user
    from_email = host_user if host_user else django_settings.DEFAULT_FROM_EMAIL

    try:
        send_mail(
            subject='Тестовое уведомление от JobFlex',
            message='Это тестовое письмо от JobFlex. Email-уведомления работают корректно.',
            from_email=from_email,
            recipient_list=[email_address],
            fail_silently=False,
        )
    except Exception as exc:
        return JsonResponse({'error': 'send_failed', 'detail': str(exc)}, status=500)

    return JsonResponse({'ok': True})


@swagger_auto_schema(method='post', operation_summary="Отключить уведомления по электронной почте", tags=['accounts'])
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_unlink_email(request):
    applicant = Applicant.objects.filter(user=request.user).first()
    if applicant:
        applicant.consent_email = False
        applicant.save(update_fields=['consent_email'])
        return JsonResponse({'ok': True})

    manager = Manager.objects.filter(user=request.user).first()
    if manager:
        manager.consent_email = False
        manager.save(update_fields=['consent_email'])
        return JsonResponse({'ok': True})

    return JsonResponse({'error': 'no_profile'}, status=400)


@swagger_auto_schema(method='post', operation_summary="Удалить аккаунт", tags=['accounts'])
@api_view(['POST'])
@permission_classes([AllowAny])
@login_required
def delete_account(request):
    user = request.user
    _log_api_action(
        request,
        action='delete_account',
        before={'user_id': user.pk, 'username': user.username},
        after={'deleted': True},
        success=True,
        status_code=200,
        endpoint='delete_account',
    )
    try:
        auth_logout(request)
    except Exception:
        pass
    Applicant.objects.filter(user=user).delete()
    User.objects.filter(pk=user.pk).delete()
    return JsonResponse({'ok': True, 'redirect': '/'})


# ──────────────────── Filter Presets endpoints ────────────────────────

@swagger_auto_schema(methods=['get'], operation_summary="Список пресетов фильтров", tags=['presets'])
@swagger_auto_schema(methods=['post'], operation_summary="Создать пресет фильтров", tags=['presets'])
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def api_presets(request):
    if request.method == 'GET':
        presets = list(FilterPreset.objects.filter(user=request.user).values('id', 'name', 'filters'))
        return JsonResponse({'ok': True, 'presets': presets})

    # POST — create new preset
    data = request.data or {}
    name = (data.get('name') or '').strip()
    if not name:
        _log_api_action(
            request,
            action='preset_create',
            after={'error': 'name_required'},
            success=False,
            status_code=400,
            endpoint='api_presets',
        )
        return JsonResponse({'error': 'name_required'}, status=400)
    filters = data.get('filters')
    if not isinstance(filters, dict):
        _log_api_action(
            request,
            action='preset_create',
            after={'error': 'filters_must_be_dict'},
            success=False,
            status_code=400,
            endpoint='api_presets',
        )
        return JsonResponse({'error': 'filters_must_be_dict'}, status=400)
    # Optionally back-fill skills from the applicant profile
    if data.get('from_profile_skills'):
        applicant = Applicant.objects.filter(user=request.user).first()
        if applicant and applicant.skills and not filters.get('skills'):
            filters = dict(filters)
            filters['skills'] = ', '.join(applicant.skills)
    preset = FilterPreset.objects.create(user=request.user, name=name, filters=filters)
    _log_api_action(
        request,
        action='preset_create',
        after={'preset_id': preset.pk, 'name': preset.name, 'filters': preset.filters},
        success=True,
        status_code=201,
        endpoint='api_presets',
    )
    return JsonResponse({'ok': True, 'id': preset.pk, 'name': preset.name, 'filters': preset.filters}, status=201)


@swagger_auto_schema(methods=['patch'], operation_summary="Обновить пресет фильтров", tags=['presets'])
@swagger_auto_schema(methods=['delete'], operation_summary="Удалить пресет фильтров", tags=['presets'])
@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def api_preset_detail(request, pk):
    preset = FilterPreset.objects.filter(pk=pk, user=request.user).first()
    if not preset:
        _log_api_action(
            request,
            action='preset_update' if request.method == 'PATCH' else 'preset_delete',
            before={'preset_id': pk},
            after={'error': 'not_found'},
            success=False,
            status_code=404,
            endpoint='api_preset_detail',
        )
        return JsonResponse({'error': 'not_found'}, status=404)
    before_state = {'preset_id': preset.pk, 'name': preset.name, 'filters': preset.filters}
    if request.method == 'DELETE':
        preset.delete()
        _log_api_action(
            request,
            action='preset_delete',
            before=before_state,
            after={'deleted': True},
            success=True,
            status_code=200,
            endpoint='api_preset_detail',
        )
        return JsonResponse({'ok': True})
    # PATCH
    data = request.data or {}
    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            _log_api_action(
                request,
                action='preset_update',
                before=before_state,
                after={'error': 'name_required'},
                success=False,
                status_code=400,
                endpoint='api_preset_detail',
            )
            return JsonResponse({'error': 'name_required'}, status=400)
        preset.name = name
    if 'filters' in data:
        filters = data.get('filters')
        if not isinstance(filters, dict):
            _log_api_action(
                request,
                action='preset_update',
                before=before_state,
                after={'error': 'filters_must_be_dict'},
                success=False,
                status_code=400,
                endpoint='api_preset_detail',
            )
            return JsonResponse({'error': 'filters_must_be_dict'}, status=400)
        preset.filters = filters
    preset.save()
    _log_api_action(
        request,
        action='preset_update',
        before=before_state,
        after={'preset_id': preset.pk, 'name': preset.name, 'filters': preset.filters},
        success=True,
        status_code=200,
        endpoint='api_preset_detail',
    )
    return JsonResponse({'ok': True, 'id': preset.pk, 'name': preset.name, 'filters': preset.filters})


# ────────────────────────────────────────────────────────────
#  Calendar API
# ────────────────────────────────────────────────────────────

@login_required
def api_calendar_events(request):
    """GET ?date=YYYY-MM-DD — role-aware calendar events.
    Managers: applications on their vacancies + interviews + notes.
    Applicants: vacancy views + their own applications + interviews + notes.
    Admins: notes + interviews only.
    """
    from datetime import date as _date
    from django.utils.timezone import localtime as _localtime
    from vacancies.models import VacancyView
    from django.db.models import Q as _Q

    raw = (request.GET.get('date') or '').strip()
    try:
        day = _date.fromisoformat(raw)
    except ValueError:
        return JsonResponse({'error': 'invalid_date'}, status=400)

    is_admin = is_admin_user(request.user)
    is_mgr   = (not is_admin) and hasattr(request.user, 'manager')
    events   = []

    if not is_admin:
        if is_mgr:
            # ─ Applications on manager's vacancies ───────────────
            apps_qs = (
                Application.objects
                .filter(vacancy__created_by=request.user, created_at__date=day)
                .select_related('vacancy', 'applicant')
                .order_by('created_at')
            )
            for a in apps_qs:
                applicant_name = a.applicant.get_full_name() or a.applicant.username
                events.append({
                    'type':  'application',
                    'icon':  '📩',
                    'title': 'Отклик: ' + applicant_name,
                    'sub':   a.vacancy.title,
                    'time':  _localtime(a.created_at).strftime('%H:%M'),
                    'color': '#70b87e',
                })
        else:
            # ─ Vacancy views (applicant only) ────────────────────
            views_qs = (
                VacancyView.objects
                .filter(user=request.user, viewed_at__date=day)
                .select_related('vacancy')
                .order_by('viewed_at')
            )
            for v in views_qs:
                events.append({
                    'type':  'view',
                    'icon':  '👀',
                    'title': v.vacancy.title,
                    'sub':   v.vacancy.company or '',
                    'time':  _localtime(v.viewed_at).strftime('%H:%M'),
                    'color': '#6c9bd2',
                    'url':   '/' + v.vacancy.external_id + '/',
                })

            # ─ Own applications (applicant only) ─────────────────
            apps_qs = (
                Application.objects
                .filter(applicant=request.user, created_at__date=day)
                .select_related('vacancy')
                .order_by('created_at')
            )
            STATUS_LABEL = {'pending': 'На рассмотрении', 'accepted': 'Принят', 'rejected': 'Отказ'}
            for a in apps_qs:
                events.append({
                    'type':  'application',
                    'icon':  '📩',
                    'title': 'Отклик: ' + a.vacancy.title,
                    'sub':   a.vacancy.company + ' · ' + STATUS_LABEL.get(a.status, a.status),
                    'time':  _localtime(a.created_at).strftime('%H:%M'),
                    'color': '#70b87e',
                    'url':   '/' + a.vacancy.external_id + '/',
                })

    # ─ Personal notes (both roles) ────────────────────────────
    notes_qs = CalendarNote.objects.filter(user=request.user, date=day)
    for n in notes_qs:
        note_time = n.note_time.strftime('%H:%M') if n.note_time else _localtime(n.created_at).strftime('%H:%M')
        events.append({
            'type':  'note',
            'id':    n.pk,
            'icon':  '📝',
            'title': n.title or n.text[:60],
            'body':  n.text,
            'sub':   '',
            'time':  note_time,
            'note_time_raw': n.note_time.strftime('%H:%M') if n.note_time else '',
            'color': n.color or '#c2a35a',
        })

    # ─ Interviews (both roles via Q filter) ───────────────────
    itv_qs = (
        Interview.objects
        .filter(
            _Q(manager=request.user) | _Q(applicant=request.user),
            scheduled_at__date=day,
            status=Interview.STATUS_SCHEDULED,
        )
        .select_related('manager', 'applicant', 'vacancy')
        .order_by('scheduled_at')
    )
    for itv in itv_qs:
        if itv.manager_id == request.user.pk:
            title = 'Собеседование с ' + (itv.applicant.get_full_name() or itv.applicant.username)
            sub   = (itv.vacancy.title if itv.vacancy else '') + (' · ' + itv.location if itv.location else '')
        else:
            title = 'Собеседование'
            if itv.vacancy:
                title += ': ' + itv.vacancy.title
            sub = (itv.manager.get_full_name() or itv.manager.username) + (' · ' + itv.location if itv.location else '')
        events.append({
            'type':       'interview',
            'id':         itv.pk,
            'icon':       '🎤',
            'title':      title,
            'sub':        sub.strip(' ·'),
            'time':       _localtime(itv.scheduled_at).strftime('%H:%M'),
            'color':      '#9b59b6',
            'can_cancel': itv.manager_id == request.user.pk,
            'url':        ('/' + itv.vacancy.external_id + '/') if itv.vacancy else None,
        })

    events.sort(key=lambda e: e['time'])

    # ─ month_marks: {date_str: [colors]} ──────────────────────
    month_marks = {}
    first_day = day.replace(day=1)
    if day.month == 12:
        last_day = day.replace(year=day.year + 1, month=1, day=1)
    else:
        last_day = day.replace(month=day.month + 1, day=1)

    def _add_mark(d_str, color):
        month_marks.setdefault(d_str, [])
        if color not in month_marks[d_str]:
            month_marks[d_str].append(color)

    if not is_admin:
        if is_mgr:
            for a in Application.objects.filter(
                vacancy__created_by=request.user,
                created_at__date__gte=first_day,
                created_at__date__lt=last_day,
            ).values_list('created_at', flat=True):
                _add_mark(str(a.date()), '#70b87e')
        else:
            for v in VacancyView.objects.filter(
                user=request.user,
                viewed_at__date__gte=first_day,
                viewed_at__date__lt=last_day,
            ).values_list('viewed_at', flat=True):
                _add_mark(str(v.date()), 'var(--accent)')
            for a in Application.objects.filter(
                applicant=request.user,
                created_at__date__gte=first_day,
                created_at__date__lt=last_day,
            ).values_list('created_at', flat=True):
                _add_mark(str(a.date()), '#70b87e')

    for n in CalendarNote.objects.filter(
        user=request.user, date__gte=first_day, date__lt=last_day
    ).values_list('date', 'color'):
        _add_mark(str(n[0]), n[1] or '#c2a35a')
    for itv in Interview.objects.filter(
        _Q(manager=request.user) | _Q(applicant=request.user),
        scheduled_at__date__gte=first_day,
        scheduled_at__date__lt=last_day,
        status=Interview.STATUS_SCHEDULED,
    ).values_list('scheduled_at', flat=True):
        _add_mark(str(itv.date()), '#9b59b6')

    return JsonResponse({'ok': True, 'events': events, 'month_marks': month_marks, 'is_manager': is_mgr})


@login_required
def api_calendar_note_save(request):
    """POST {date, title?, text?, color?, time?} — create a note.
    DELETE {id} — remove a note.
    PATCH {id, date?, title?, text?, color?, time?} — update date / content / color / time."""
    from datetime import date as _date, time as _time

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'invalid_json'}, status=400)

    def _parse_time(raw):
        raw = (raw or '').strip()
        if not raw:
            return None, False  # (value, had_value)
        try:
            parts = raw.split(':')
            return _time(int(parts[0]), int(parts[1])), True
        except (ValueError, IndexError):
            return None, True  # explicit clear

    def _resolve_notify_settings(user):
        """Resolve notification channels for a calendar-note event."""
        consent_email = False
        consent_telegram = False
        tg_chat_id = None

        # Prefer manager profile if it exists (manager users can also keep
        # applicant records after role switches).
        try:
            prof = user.manager
            consent_email = bool(prof.consent_email)
            consent_telegram = bool(prof.consent_telegram)
            tg_chat_id = prof.telegram_chat_id
            return consent_email, consent_telegram, tg_chat_id
        except Exception:
            pass

        try:
            prof = user.applicant
            consent_email = bool(prof.consent_email)
            consent_telegram = bool(prof.consent_telegram)
            tg_chat_id = prof.telegram_chat_id
        except Exception:
            pass

        return consent_email, consent_telegram, tg_chat_id

    def _notify_note_event(user, subject, text):
        # Admin calendar actions should be silent (no Telegram/email).
        if is_admin_user(user):
            return

        consent_email, consent_telegram, tg_chat_id = _resolve_notify_settings(user)

        if consent_telegram and tg_chat_id:
            try:
                send_hello_async(tg_chat_id, text=text)
            except Exception:
                pass

        if consent_email and user.email:
            try:
                send_mail(
                    subject=subject,
                    message=text + '\n\n— JobFlex',
                    from_email=django_settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=True,
                )
            except Exception:
                pass

    if request.method == 'PATCH':
        note_id = data.get('id')
        try:
            note = CalendarNote.objects.get(pk=note_id, user=request.user)
        except CalendarNote.DoesNotExist:
            return JsonResponse({'error': 'not_found'}, status=404)

        old_date = note.date
        old_time = note.note_time

        update_fields = []
        # Date
        new_date = (data.get('date') or '').strip()
        if new_date:
            try:
                note.date = _date.fromisoformat(new_date)
                update_fields.append('date')
            except (ValueError, AttributeError):
                return JsonResponse({'error': 'invalid_date'}, status=400)
        # Title
        if 'title' in data:
            note.title = (data['title'] or '').strip()
            update_fields.append('title')
        # Text / body
        if 'text' in data:
            note.text = (data['text'] or '').strip()
            update_fields.append('text')
        # Color
        if 'color' in data:
            raw_color = (data['color'] or '').strip()
            if raw_color:
                note.color = raw_color
                update_fields.append('color')
        # Time  — if key present, update (even to null for "clear")
        if 'time' in data:
            note.note_time, _ = _parse_time(data['time'])
            update_fields.append('note_time')

        moved = (note.date != old_date) or (note.note_time != old_time)
        if moved:
            note.reminded = False
            if 'reminded' not in update_fields:
                update_fields.append('reminded')

        if update_fields:
            note.save(update_fields=update_fields)

        if moved:
            old_date_str = old_date.strftime('%d.%m.%Y')
            new_date_str = note.date.strftime('%d.%m.%Y')
            old_time_str = old_time.strftime('%H:%M') if old_time else 'без времени'
            new_time_str = note.note_time.strftime('%H:%M') if note.note_time else 'без времени'
            note_title = note.title or (note.text[:60] if note.text else 'Без названия')
            msg = (
                '📝 Заметка перенесена\n\n'
                f'Заметка: {note_title}\n'
                f'Было: {old_date_str} в {old_time_str}\n'
                f'Стало: {new_date_str} в {new_time_str}'
            )
            _notify_note_event(
                request.user,
                subject='Заметка перенесена — JobFlex',
                text=msg,
            )

        return JsonResponse({'ok': True})

    if request.method == 'POST':
        raw      = (data.get('date') or '').strip()
        title    = (data.get('title') or '').strip()
        text     = (data.get('text') or '').strip()
        color    = (data.get('color') or '#c2a35a').strip()
        time_raw = (data.get('time') or '').strip()
        if not title and not text:
            return JsonResponse({'error': 'empty_note'}, status=400)
        try:
            day = _date.fromisoformat(raw)
        except ValueError:
            return JsonResponse({'error': 'invalid_date'}, status=400)
        note_time, _ = _parse_time(time_raw)
        note = CalendarNote.objects.create(
            user=request.user, date=day,
            title=title, text=text, color=color, note_time=note_time,
        )
        return JsonResponse({'ok': True, 'id': note.pk})

    if request.method == 'DELETE':
        note_id = data.get('id')
        note = CalendarNote.objects.filter(pk=note_id, user=request.user).first()
        if not note:
            return JsonResponse({'ok': False})

        note_title = note.title or (note.text[:60] if note.text else 'Без названия')
        date_str = note.date.strftime('%d.%m.%Y')
        time_str = note.note_time.strftime('%H:%M') if note.note_time else 'без времени'

        note.delete()

        msg = (
            '🗑 Заметка удалена\n\n'
            f'Заметка: {note_title}\n'
            f'Дата: {date_str}\n'
            f'Время: {time_str}'
        )
        _notify_note_event(
            request.user,
            subject='Заметка удалена — JobFlex',
            text=msg,
        )
        return JsonResponse({'ok': True})

    return JsonResponse({'error': 'method_not_allowed'}, status=405)


@login_required
def api_calendar_month_export(request):
    """GET ?year=Y&month=M — all notes + interviews for the month (for .ics export / week-view preload)."""
    from datetime import date as _date
    try:
        year  = int(request.GET.get('year',  0))
        month = int(request.GET.get('month', 0))
        if not (1 <= month <= 12):
            raise ValueError
    except (ValueError, TypeError):
        return JsonResponse({'error': 'invalid_params'}, status=400)

    events = []
    for note in CalendarNote.objects.filter(
        user=request.user, date__year=year, date__month=month
    ).order_by('date', 'note_time'):
        events.append({
            'type':  'note',
            'id':    note.pk,
            'date':  str(note.date),
            'title': note.title or note.text[:60],
            'text':  note.text,
            'time':  str(note.note_time)[:5] if note.note_time else None,
            'color': note.color or '#c2a35a',
        })

    try:
        ivs = Interview.objects.filter(
            applicant__user=request.user,
            scheduled_at__year=year,
            scheduled_at__month=month,
        ).exclude(status='cancelled').select_related('vacancy', 'manager__user')
        for iv in ivs:
            dt = iv.scheduled_at
            events.append({
                'type':     'interview',
                'id':       iv.pk,
                'date':     dt.strftime('%Y-%m-%d'),
                'title':    (iv.vacancy.title if (iv.vacancy and iv.vacancy.title) else 'Собеседование'),
                'company':  (iv.vacancy.company_name if (iv.vacancy and iv.vacancy.company_name) else ''),
                'time':     dt.strftime('%H:%M'),
                'location': iv.location or '',
            })
    except Exception:
        pass

    return JsonResponse({'ok': True, 'events': events})


@login_required
def api_calendar_notes_index(request):
    """GET — global note index for calendar search (all dates for current user)."""
    notes = []
    for note in CalendarNote.objects.filter(user=request.user).order_by('date', 'note_time', 'created_at'):
        notes.append({
            'type': 'note',
            'id': note.pk,
            'date': str(note.date),
            'title': note.title or note.text[:60],
            'text': note.text or '',
            'time': str(note.note_time)[:5] if note.note_time else None,
            'color': note.color or '#c2a35a',
        })
    return JsonResponse({'ok': True, 'events': notes})


@login_required
def api_interview_schedule(request):
    """POST {applicant_user_id, vacancy_id, date, time, location, notes} — schedule an interview."""
    from datetime import datetime as _dt, timezone as _tz

    if request.method != 'POST':
        _log_api_action(
            request,
            action='interview_schedule',
            after={'error': 'method_not_allowed'},
            success=False,
            status_code=405,
            endpoint='api_interview_schedule',
        )
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    if not hasattr(request.user, 'manager'):
        _log_api_action(
            request,
            action='interview_schedule',
            after={'error': 'forbidden'},
            success=False,
            status_code=403,
            endpoint='api_interview_schedule',
        )
        return JsonResponse({'error': 'forbidden'}, status=403)

    try:
        data = json.loads(request.body)
    except Exception:
        _log_api_action(
            request,
            action='interview_schedule',
            after={'error': 'invalid_json'},
            success=False,
            status_code=400,
            endpoint='api_interview_schedule',
        )
        return JsonResponse({'error': 'invalid_json'}, status=400)

    applicant_uid = data.get('applicant_user_id')
    date_str      = (data.get('date') or '').strip()
    time_str      = (data.get('time') or '00:00').strip()
    location      = (data.get('location') or '').strip()
    notes_text    = (data.get('notes') or '').strip()
    vacancy_id    = data.get('vacancy_id')

    if not applicant_uid or not date_str:
        _log_api_action(
            request,
            action='interview_schedule',
            after={'error': 'missing_fields', 'applicant_user_id': applicant_uid, 'date': date_str},
            success=False,
            status_code=400,
            endpoint='api_interview_schedule',
        )
        return JsonResponse({'error': 'missing_fields'}, status=400)

    try:
        applicant_user = User.objects.get(pk=applicant_uid, applicant__isnull=False)
    except User.DoesNotExist:
        _log_api_action(
            request,
            action='interview_schedule',
            after={'error': 'applicant_not_found', 'applicant_user_id': applicant_uid},
            success=False,
            status_code=404,
            endpoint='api_interview_schedule',
        )
        return JsonResponse({'error': 'applicant_not_found'}, status=404)

    try:
        naive = _dt.strptime(date_str + ' ' + time_str, '%Y-%m-%d %H:%M')
        from django.utils.timezone import make_aware as _make_aware
        scheduled_at = _make_aware(naive)
    except ValueError:
        _log_api_action(
            request,
            action='interview_schedule',
            after={'error': 'invalid_datetime', 'date': date_str, 'time': time_str},
            success=False,
            status_code=400,
            endpoint='api_interview_schedule',
        )
        return JsonResponse({'error': 'invalid_datetime'}, status=400)

    vacancy = None
    if vacancy_id:
        from vacancies.models import Vacancy
        vacancy = Vacancy.objects.filter(pk=vacancy_id).first()

    itv = Interview.objects.create(
        manager=request.user,
        applicant=applicant_user,
        vacancy=vacancy,
        scheduled_at=scheduled_at,
        location=location,
        notes=notes_text,
    )

    # Update the application status to "accepted" (Приглашение)
    if vacancy:
        Application.objects.filter(
            applicant=applicant_user, vacancy=vacancy
        ).exclude(status='accepted').update(status='accepted')

    # ── Schedule exact-time Telegram/email notifications (24h, 1h, 5min before) ────────
    try:
        from accounts.tasks import send_interview_notification_task
        from django.utils.timezone import now as _tz_now
        from datetime import timedelta as _td
        _now = _tz_now()
        for _label, _delta in [('1d', _td(hours=24)), ('1h', _td(hours=1)), ('now', _td(minutes=5))]:
            _eta = scheduled_at - _delta
            if _eta > _now:
                send_interview_notification_task.apply_async(args=[itv.pk, _label], eta=_eta)
    except Exception:
        pass  # scheduling is best-effort

    # Post a system message in the chat between manager and applicant
    try:
        chat, _ = Chat.objects.get_or_create(
            manager=request.user, applicant=applicant_user
        )
        scheduled_str = scheduled_at.strftime('%d.%m.%Y %H:%M') + ' UTC'
        msg_lines = ['📅 Собеседование назначено']
        if vacancy:
            msg_lines[0] += ': ' + vacancy.title
        msg_lines.append('📆 ' + scheduled_str)
        if location:
            msg_lines.append('📍 ' + location)
        msg_text = '\n'.join(msg_lines)
        Message.objects.create(chat=chat, sender=request.user, text=msg_text)
        sender_name = request.user.get_full_name() or request.user.username
        notify_new_chat_message(applicant_user, sender_name, msg_text, chat.pk)
    except Exception:
        pass  # chat notification is best-effort

    # ── Immediate Telegram / email notification to both parties ──────────────
    try:
        from django.utils import timezone as _tz_util
        local_dt  = _tz_util.localtime(scheduled_at)
        date_disp = local_dt.strftime('%d.%m.%Y')
        time_disp = local_dt.strftime('%H:%M')
        vacancy_title = vacancy.title if vacancy else '—'

        # Notification for the applicant
        applicant_profile = getattr(applicant_user, 'applicant', None)
        if applicant_profile:
            lines = [
                '📅 Вас приглашают на собеседование!',
                f'Вакансия: {vacancy_title}',
                f'Дата и время: {date_disp} в {time_disp}',
            ]
            if location:
                lines.append(f'Место/ссылка: {location}')
            msg_applicant = '\n'.join(lines)
            if applicant_profile.consent_telegram and applicant_profile.telegram_chat_id:
                send_hello_async(applicant_profile.telegram_chat_id, msg_applicant)
            if applicant_profile.consent_email and applicant_user.email:
                send_mail(
                    subject=f'Приглашение на собеседование: {vacancy_title}',
                    message=msg_applicant + '\n\n— JobFlex',
                    from_email=django_settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[applicant_user.email],
                    fail_silently=True,
                )

        # Notification for the manager (confirmation)
        manager_profile = getattr(request.user, 'manager', None)
        if manager_profile:
            applicant_name = applicant_user.get_full_name() or applicant_user.username
            lines = [
                '📅 Собеседование назначено',
                f'Соискатель: {applicant_name}',
                f'Вакансия: {vacancy_title}',
                f'Дата и время: {date_disp} в {time_disp}',
            ]
            if location:
                lines.append(f'Место/ссылка: {location}')
            msg_manager = '\n'.join(lines)
            if manager_profile.consent_telegram and manager_profile.telegram_chat_id:
                send_hello_async(manager_profile.telegram_chat_id, msg_manager)
            if manager_profile.consent_email and request.user.email:
                send_mail(
                    subject=f'Собеседование назначено: {applicant_name}',
                    message=msg_manager + '\n\n— JobFlex',
                    from_email=django_settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[request.user.email],
                    fail_silently=True,
                )
    except Exception:
        pass  # notifications are best-effort

    _log_api_action(
        request,
        action='interview_schedule',
        after={
            'interview_id': itv.pk,
            'applicant_user_id': applicant_user.pk,
            'vacancy_id': vacancy.pk if vacancy else None,
            'scheduled_at': str(itv.scheduled_at),
            'location': location,
        },
        success=True,
        status_code=200,
        endpoint='api_interview_schedule',
    )

    return JsonResponse({'ok': True, 'id': itv.pk})


@login_required
def api_interview_cancel(request):
    """DELETE {id} — cancel a scheduled interview (manager OR applicant)."""
    from django.db.models import Q as _Q

    if request.method != 'DELETE':
        _log_api_action(
            request,
            action='interview_cancel',
            after={'error': 'method_not_allowed'},
            success=False,
            status_code=405,
            endpoint='api_interview_cancel',
        )
        return JsonResponse({'error': 'method_not_allowed'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        _log_api_action(
            request,
            action='interview_cancel',
            after={'error': 'invalid_json'},
            success=False,
            status_code=400,
            endpoint='api_interview_cancel',
        )
        return JsonResponse({'error': 'invalid_json'}, status=400)

    try:
        itv = Interview.objects.select_related(
            'manager', 'applicant', 'vacancy'
        ).get(
            _Q(manager=request.user) | _Q(applicant=request.user),
            pk=data.get('id'),
            status=Interview.STATUS_SCHEDULED,
        )
    except Interview.DoesNotExist:
        _log_api_action(
            request,
            action='interview_cancel',
            before={'interview_id': data.get('id')},
            after={'error': 'not_found'},
            success=False,
            status_code=404,
            endpoint='api_interview_cancel',
        )
        return JsonResponse({'error': 'not_found'}, status=404)

    action = (data.get('action') or '').strip()
    before_state = {
        'interview_id': itv.pk,
        'status': itv.status,
        'scheduled_at': str(itv.scheduled_at),
        'vacancy_id': itv.vacancy_id,
    }
    itv.status = Interview.STATUS_CANCELLED
    itv.save(update_fields=['status'])

    # If manager explicitly rejects — update application status
    if action == 'reject' and itv.vacancy and request.user == itv.manager:
        Application.objects.filter(
            applicant=itv.applicant, vacancy=itv.vacancy
        ).update(status='rejected')

    canceller_name = request.user.get_full_name() or request.user.username
    vacancy_title  = itv.vacancy.title if itv.vacancy else '—'

    # Post a system message in the chat between manager and applicant
    try:
        chat, _ = Chat.objects.get_or_create(
            manager=itv.manager, applicant=itv.applicant
        )
        scheduled_str = itv.scheduled_at.strftime('%d.%m.%Y %H:%M') + ' UTC'
        msg_lines = ['❌ Собеседование отменено']
        if itv.vacancy:
            msg_lines[0] += ': ' + itv.vacancy.title
        msg_lines.append('📆 ' + scheduled_str)
        msg_lines.append('Отменил(а): ' + canceller_name)
        msg_text = '\n'.join(msg_lines)
        Message.objects.create(chat=chat, sender=request.user, text=msg_text)
        other_user = itv.applicant if request.user == itv.manager else itv.manager
        notify_new_chat_message(other_user, canceller_name, msg_text, chat.pk)
    except Exception:
        pass  # chat notification is best-effort

    # ── Telegram / email cancellation notifications ───────────────────────────
    try:
        from django.utils import timezone as _tz_util
        from django.core.mail import send_mail as _send_mail

        local_dt  = _tz_util.localtime(itv.scheduled_at)
        date_disp = local_dt.strftime('%d.%m.%Y')
        time_disp = local_dt.strftime('%H:%M')

        # Notify applicant
        applicant_profile = getattr(itv.applicant, 'applicant', None)
        if applicant_profile:
            lines = [
                '❌ Собеседование отменено',
                f'Вакансия: {vacancy_title}',
                f'Дата и время: {date_disp} в {time_disp}',
                f'Отменил(а): {canceller_name}',
            ]
            msg_a = '\n'.join(lines)
            if applicant_profile.consent_telegram and applicant_profile.telegram_chat_id:
                send_hello_async(applicant_profile.telegram_chat_id, msg_a)
            if applicant_profile.consent_email and itv.applicant.email:
                _send_mail(
                    subject=f'Собеседование отменено: {vacancy_title}',
                    message=msg_a + '\n\n— JobFlex',
                    from_email=django_settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[itv.applicant.email],
                    fail_silently=True,
                )

        # Notify manager
        manager_profile = getattr(itv.manager, 'manager', None)
        if manager_profile:
            applicant_name = itv.applicant.get_full_name() or itv.applicant.username
            lines = [
                '❌ Собеседование отменено',
                f'Соискатель: {applicant_name}',
                f'Вакансия: {vacancy_title}',
                f'Дата и время: {date_disp} в {time_disp}',
                f'Отменил(а): {canceller_name}',
            ]
            msg_m = '\n'.join(lines)
            if manager_profile.consent_telegram and manager_profile.telegram_chat_id:
                send_hello_async(manager_profile.telegram_chat_id, msg_m)
            if manager_profile.consent_email and itv.manager.email:
                _send_mail(
                    subject=f'Собеседование отменено: {applicant_name}',
                    message=msg_m + '\n\n— JobFlex',
                    from_email=django_settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[itv.manager.email],
                    fail_silently=True,
                )
    except Exception:
        pass  # notifications are best-effort

    _log_api_action(
        request,
        action='interview_cancel',
        before=before_state,
        after={
            'interview_id': itv.pk,
            'status': itv.status,
            'cancel_action': action,
        },
        success=True,
        status_code=200,
        endpoint='api_interview_cancel',
    )

    return JsonResponse({'ok': True})


@login_required
def api_interview_reschedule(request):
    """PATCH {id, date, time} — reschedule an interview (manager only)."""
    from datetime import datetime as _dt

    if request.method != 'PATCH':
        _log_api_action(
            request,
            action='interview_reschedule',
            after={'error': 'method_not_allowed'},
            success=False,
            status_code=405,
            endpoint='api_interview_reschedule',
        )
        return JsonResponse({'error': 'method_not_allowed'}, status=405)
    if not hasattr(request.user, 'manager'):
        _log_api_action(
            request,
            action='interview_reschedule',
            after={'error': 'forbidden'},
            success=False,
            status_code=403,
            endpoint='api_interview_reschedule',
        )
        return JsonResponse({'error': 'forbidden'}, status=403)

    try:
        data = json.loads(request.body)
    except Exception:
        _log_api_action(
            request,
            action='interview_reschedule',
            after={'error': 'invalid_json'},
            success=False,
            status_code=400,
            endpoint='api_interview_reschedule',
        )
        return JsonResponse({'error': 'invalid_json'}, status=400)

    try:
        itv = Interview.objects.select_related('manager', 'applicant', 'vacancy').get(
            manager=request.user,
            pk=data.get('id'),
            status=Interview.STATUS_SCHEDULED,
        )
    except Interview.DoesNotExist:
        _log_api_action(
            request,
            action='interview_reschedule',
            before={'interview_id': data.get('id')},
            after={'error': 'not_found'},
            success=False,
            status_code=404,
            endpoint='api_interview_reschedule',
        )
        return JsonResponse({'error': 'not_found'}, status=404)

    date_str = (data.get('date') or '').strip()
    time_str = (data.get('time') or '10:00').strip()
    try:
        naive = _dt.strptime(date_str + ' ' + time_str, '%Y-%m-%d %H:%M')
        from django.utils.timezone import make_aware as _make_aware
        scheduled_at = _make_aware(naive)
    except ValueError:
        _log_api_action(
            request,
            action='interview_reschedule',
            before={'interview_id': itv.pk},
            after={'error': 'invalid_datetime', 'date': date_str, 'time': time_str},
            success=False,
            status_code=400,
            endpoint='api_interview_reschedule',
        )
        return JsonResponse({'error': 'invalid_datetime'}, status=400)

    old_dt = itv.scheduled_at
    itv.scheduled_at = scheduled_at
    itv.reminded_1d = False
    itv.reminded_1h = False
    itv.reminded_now = False
    itv.save(update_fields=['scheduled_at', 'reminded_1d', 'reminded_1h', 'reminded_now'])

    # Notify applicant
    try:
        from django.utils import timezone as _tz_util
        from django.core.mail import send_mail as _send_mail
        local_old = _tz_util.localtime(old_dt)
        local_new = _tz_util.localtime(scheduled_at)
        vacancy_title = itv.vacancy.title if itv.vacancy else '—'
        lines = [
            '📅 Собеседование перенесено',
            f'Вакансия: {vacancy_title}',
            f'Старое время: {local_old.strftime("%d.%m.%Y %H:%M")}',
            f'Новое время: {local_new.strftime("%d.%m.%Y %H:%M")}',
        ]
        if itv.location:
            lines.append(f'Место/ссылка: {itv.location}')
        msg = '\n'.join(lines)
        sender_name = request.user.get_full_name() or request.user.username
        chat, _ = Chat.objects.get_or_create(manager=request.user, applicant=itv.applicant)
        Message.objects.create(chat=chat, sender=request.user, text=msg)
        notify_new_chat_message(itv.applicant, sender_name, msg, chat.pk)
        applicant_profile = getattr(itv.applicant, 'applicant', None)
        if applicant_profile:
            if applicant_profile.consent_telegram and applicant_profile.telegram_chat_id:
                send_hello_async(applicant_profile.telegram_chat_id, msg)
            if applicant_profile.consent_email and itv.applicant.email:
                _send_mail(
                    subject=f'Собеседование перенесено: {vacancy_title}',
                    message=msg + '\n\n— JobFlex',
                    from_email=django_settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[itv.applicant.email],
                    fail_silently=True,
                )
    except Exception:
        pass

    _log_api_action(
        request,
        action='interview_reschedule',
        before={'interview_id': itv.pk, 'scheduled_at': str(old_dt)},
        after={'interview_id': itv.pk, 'scheduled_at': str(itv.scheduled_at)},
        success=True,
        status_code=200,
        endpoint='api_interview_reschedule',
    )

    return JsonResponse({'ok': True})


@login_required
def api_manager_calendar_events(request):
    """GET ?date=YYYY-MM-DD — return applications on manager's vacancies, interviews and notes."""
    from datetime import date as _date
    from django.utils.timezone import localtime as _localtime
    from django.db.models import Q as _Q

    if not hasattr(request.user, 'manager'):
        return JsonResponse({'error': 'forbidden'}, status=403)

    raw = (request.GET.get('date') or '').strip()
    try:
        day = _date.fromisoformat(raw)
    except ValueError:
        return JsonResponse({'error': 'invalid_date'}, status=400)

    events = []

    # ─ Applications on manager's vacancies ────────────────────────
    apps_qs = (
        Application.objects
        .filter(vacancy__created_by=request.user, created_at__date=day)
        .select_related('vacancy', 'applicant')
        .order_by('created_at')
    )
    for a in apps_qs:
        applicant_name = a.applicant.get_full_name() or a.applicant.username
        events.append({
            'type':  'application',
            'icon':  '📩',
            'title': 'Отклик: ' + applicant_name,
            'sub':   a.vacancy.title,
            'time':  _localtime(a.created_at).strftime('%H:%M'),
            'color': '#70b87e',
        })

    # ─ Interviews (manager side) ───────────────────────────────────
    itv_qs = (
        Interview.objects
        .filter(manager=request.user, scheduled_at__date=day, status=Interview.STATUS_SCHEDULED)
        .select_related('applicant', 'vacancy')
        .order_by('scheduled_at')
    )
    for itv in itv_qs:
        applicant_name = itv.applicant.get_full_name() or itv.applicant.username
        sub = itv.vacancy.title if itv.vacancy else ''
        if itv.location:
            sub += (' · ' if sub else '') + itv.location
        events.append({
            'type':       'interview',
            'id':         itv.pk,
            'icon':       '🎤',
            'title':      'Собеседование с ' + applicant_name,
            'sub':        sub.strip(' ·'),
            'time':       _localtime(itv.scheduled_at).strftime('%H:%M'),
            'color':      '#9b59b6',
            'can_cancel': True,
        })

    # ─ Personal notes ─────────────────────────────────────────────
    notes_qs = CalendarNote.objects.filter(user=request.user, date=day)
    for n in notes_qs:
        note_time = n.note_time.strftime('%H:%M') if n.note_time else _localtime(n.created_at).strftime('%H:%M')
        events.append({
            'type':  'note',
            'id':    n.pk,
            'icon':  '📝',
            'title': n.title or n.text[:60],
            'body':  n.text,
            'sub':   '',
            'time':  note_time,
            'note_time_raw': n.note_time.strftime('%H:%M') if n.note_time else '',
            'color': n.color or '#c2a35a',
        })

    events.sort(key=lambda e: e['time'])

    # ─ month_marks: {date_str: [colors]} ──────────────────────────
    month_marks = {}
    first_day = day.replace(day=1)
    if day.month == 12:
        last_day = day.replace(year=day.year + 1, month=1, day=1)
    else:
        last_day = day.replace(month=day.month + 1, day=1)

    def _add_mark(d_str, color):
        month_marks.setdefault(d_str, [])
        if color not in month_marks[d_str]:
            month_marks[d_str].append(color)

    for a in Application.objects.filter(
        vacancy__created_by=request.user,
        created_at__date__gte=first_day,
        created_at__date__lt=last_day,
    ).values_list('created_at', flat=True):
        _add_mark(str(a.date()), '#70b87e')

    for n in CalendarNote.objects.filter(
        user=request.user,
        date__gte=first_day,
        date__lt=last_day,
    ).values_list('date', 'color'):
        _add_mark(str(n[0]), n[1] or '#c2a35a')

    for itv in Interview.objects.filter(
        manager=request.user,
        scheduled_at__date__gte=first_day,
        scheduled_at__date__lt=last_day,
        status=Interview.STATUS_SCHEDULED,
    ).values_list('scheduled_at', flat=True):
        _add_mark(str(itv.date()), '#9b59b6')

    return JsonResponse({'ok': True, 'events': events, 'month_marks': month_marks})
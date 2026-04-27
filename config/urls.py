"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic.base import RedirectView
from django.templatetags.static import static as static_url
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from rest_framework import permissions
from vacancies.views import custom_403, custom_404

handler404 = custom_404
handler403 = custom_403


class IsAdminUserWithProfile(permissions.BasePermission):
    """
    Grants access only to users who are both superusers
    and have an Administrator profile in the database.
    """
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.is_superuser
            and hasattr(request.user, 'admin_profile')
        )


api_info = openapi.Info(
    title="JobFlex — API агрегатора вакансий",
    default_version='v1',
    description=(
        "Документация REST API платформы JobFlex (агрегация вакансий, профили, модерация).\n\n"
        "## Как пользоваться из Swagger UI и ReDoc\n\n"
        "1. **Сессия.** Большинство методов требуют авторизации через cookie `sessionid`. "
        "Сначала выполните `POST /accounts/api/login/` (или войдите через сайт), "
        "затем в интерфейсе нажмите **Authorize** и выберите схему **Session**.\n\n"
        "2. **CSRF.** Для изменяющих запросов (POST, PUT, PATCH, DELETE) из браузера нужен заголовок "
        "`X-CSRFToken` с тем же значением, что и cookie `csrftoken`. После входа через Swagger/ReDoc "
        "заголовок обычно подставляется автоматически.\n\n"
        "3. **Примеры.** У каждой операции в описании приведены примеры тел запросов и ответов в Markdown "
        "(ReDoc и Swagger отображают их под заголовком операции).\n\n"
        "## Разделы\n\n"
        "- **accounts** — регистрация, вход, профиль, файлы, отклики, чаты, календарь, собеседования.\n"
        "- **vacancies / moderation** — жалобы, модерация, мягкое удаление вакансий.\n"
        "- **api** — вспомогательные публичные методы (описание вакансии, рейтинг работодателя).\n\n"
        "⚠️ **Доступ к этой странице документации** (Swagger и ReDoc) разрешён только администраторам "
        "с профилем в системе."
    ),
    contact=openapi.Contact(name="Поддержка JobFlex", email="admin@jobapp.local"),
)

schema_view = get_schema_view(
    api_info,
    public=False,
    permission_classes=[IsAdminUserWithProfile],
)

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url=static_url('logo/logo.png'), permanent=True)),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    # Swagger / ReDoc — must come before the vacancies catch-all
    re_path(r'^swagger(?P<format>\.json|\.yaml)$', schema_view.without_ui(cache_timeout=0), name='schema-json'),
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    path('403/', custom_403),  # dev preview
    path('404/', custom_404),  # dev preview
    path('', include('vacancies.urls')),
]
# Serve uploaded media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Catch-all — must be last; renders custom 404 even when DEBUG=True
urlpatterns += [re_path(r'^.*$', custom_404)]
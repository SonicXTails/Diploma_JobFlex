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
    title="Job Aggregator API",
    default_version='v1',
    description=(
        "REST API для системы агрегации вакансий.\n\n"
        "**accounts/** — регистрация, авторизация, профиль пользователя, Telegram-интеграция.\n\n"
        "**vacancies/** — список вакансий, детальная страница, рейтинг работодателей.\n\n"
        "⚠️ Swagger UI доступен только администраторам системы."
    ),
    contact=openapi.Contact(email="admin@jobapp.local"),
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
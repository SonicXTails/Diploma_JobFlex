from django.contrib import admin
from .models import Applicant, Manager, Administrator, ApiActionLog


@admin.register(Applicant)
class ApplicantAdmin(admin.ModelAdmin):
    list_display = ('user', 'telegram', 'phone', 'gender', 'city', 'citizenship', 'consent_email', 'consent_telegram')
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'telegram', 'phone', 'city')


@admin.register(Manager)
class ManagerAdmin(admin.ModelAdmin):
    list_display = ('user', 'telegram', 'company', 'phone')
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'telegram', 'company')


@admin.register(Administrator)
class AdministratorAdmin(admin.ModelAdmin):
    list_display  = ('user', 'is_superuser_ok', 'created_at')
    search_fields = ('user__email', 'user__username', 'user__first_name', 'user__last_name')
    readonly_fields = ('created_at',)

    @admin.display(boolean=True, description='Superuser')
    def is_superuser_ok(self, obj):
        return obj.user.is_superuser


@admin.register(ApiActionLog)
class ApiActionLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor_role', 'user', 'method', 'action', 'endpoint', 'success', 'status_code')
    list_filter = ('actor_role', 'method', 'success', 'endpoint', 'created_at')
    search_fields = ('user__username', 'user__email', 'action', 'endpoint', 'path')
    readonly_fields = ('created_at',)

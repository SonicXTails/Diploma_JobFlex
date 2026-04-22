from django.contrib import admin

from vacancies.models import VacancyReport


@admin.register(VacancyReport)
class VacancyReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'vacancy', 'user', 'reason_code', 'self_status', 'reviewed_by', 'created_at')
    list_filter = ('reason_code', 'self_status', 'created_at')
    search_fields = ('vacancy__title', 'vacancy__company', 'user__username', 'user__email')
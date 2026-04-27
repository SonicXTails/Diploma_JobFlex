from django.contrib import admin

from vacancies.models import VacancyReport


@admin.register(VacancyReport)
class VacancyReportAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'vacancy_label',
        'user_label',
        'reason_label',
        'status_label',
        'reviewed_by_label',
        'created_at',
    )
    list_filter = ('reason_code', 'self_status', 'created_at')
    search_fields = ('vacancy__title', 'vacancy__company', 'user__username', 'user__email')

    @admin.display(description='Вакансия')
    def vacancy_label(self, obj):
        return obj.vacancy

    @admin.display(description='Пользователь')
    def user_label(self, obj):
        return obj.user

    @admin.display(description='Причина')
    def reason_label(self, obj):
        return obj.get_reason_code_display()

    @admin.display(description='Статус')
    def status_label(self, obj):
        return obj.get_self_status_display()

    @admin.display(description='Проверил')
    def reviewed_by_label(self, obj):
        return obj.reviewed_by
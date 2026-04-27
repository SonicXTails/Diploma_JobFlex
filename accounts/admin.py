from django.contrib import admin
from .models import Applicant, Manager, Administrator, Moderator, ApiActionLog, UserDocument, UserDocumentFile

admin.site.site_header = 'Администрирование JobFlex'
admin.site.site_title = 'Панель администратора JobFlex'
admin.site.index_title = 'Управление данными JobFlex'


@admin.register(Applicant)
class ApplicantAdmin(admin.ModelAdmin):
    list_display = (
        'user_label',
        'telegram_label',
        'phone',
        'gender',
        'city',
        'citizenship',
        'consent_email',
        'consent_telegram',
    )
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'telegram', 'phone', 'city')

    @admin.display(description='Пользователь')
    def user_label(self, obj):
        return obj.user

    @admin.display(description='Телеграм')
    def telegram_label(self, obj):
        return obj.telegram


@admin.register(Manager)
class ManagerAdmin(admin.ModelAdmin):
    list_display = ('user_label', 'telegram_label', 'company', 'phone')
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'telegram', 'company')

    @admin.display(description='Пользователь')
    def user_label(self, obj):
        return obj.user

    @admin.display(description='Телеграм')
    def telegram_label(self, obj):
        return obj.telegram


@admin.register(Administrator)
class AdministratorAdmin(admin.ModelAdmin):
    list_display  = ('user_label', 'is_superuser_ok', 'created_at')
    search_fields = ('user__email', 'user__username', 'user__first_name', 'user__last_name')
    readonly_fields = ('created_at',)

    @admin.display(description='Пользователь')
    def user_label(self, obj):
        return obj.user

    @admin.display(boolean=True, description='Суперпользователь')
    def is_superuser_ok(self, obj):
        return obj.user.is_superuser


@admin.register(Moderator)
class ModeratorAdmin(admin.ModelAdmin):
    list_display = ('user_label', 'telegram_label', 'phone', 'created_at')
    search_fields = ('user__email', 'user__username', 'user__first_name', 'user__last_name', 'telegram', 'phone')
    readonly_fields = ('created_at',)

    @admin.display(description='Пользователь')
    def user_label(self, obj):
        return obj.user

    @admin.display(description='Телеграм')
    def telegram_label(self, obj):
        return obj.telegram


@admin.register(ApiActionLog)
class ApiActionLogAdmin(admin.ModelAdmin):
    list_display = (
        'created_at',
        'actor_role_label',
        'user_label',
        'method_label',
        'action',
        'endpoint',
        'success_label',
        'status_code_label',
    )
    list_filter = ('actor_role', 'method', 'success', 'endpoint', 'created_at')
    search_fields = ('user__username', 'user__email', 'action', 'endpoint', 'path')
    readonly_fields = ('created_at',)

    @admin.display(description='Роль')
    def actor_role_label(self, obj):
        return obj.get_actor_role_display()

    @admin.display(description='Пользователь')
    def user_label(self, obj):
        return obj.user

    @admin.display(description='Метод')
    def method_label(self, obj):
        return obj.method

    @admin.display(boolean=True, description='Успешно')
    def success_label(self, obj):
        return obj.success

    @admin.display(description='Код ответа')
    def status_code_label(self, obj):
        return obj.status_code


class UserDocumentFileInline(admin.TabularInline):
    model = UserDocumentFile
    extra = 0
    verbose_name = 'Файл'
    verbose_name_plural = 'Файлы'


@admin.register(UserDocument)
class UserDocumentAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_label', 'doc_type', 'serial', 'number', 'created_at')
    list_filter = ('doc_type', 'created_at')
    search_fields = ('user__username', 'user__email', 'serial', 'number', 'issued_by')
    inlines = [UserDocumentFileInline]

    @admin.display(description='Пользователь')
    def user_label(self, obj):
        return obj.user

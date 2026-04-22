from django.urls import path, re_path

from vacancies.views import (
    VacancyListView, VacancyDetailView,
    employer_rating_api, vacancy_description_api,
    vacancy_branded_frame_view,
    vacancy_create, vacancy_edit, vacancy_delete, my_vacancies,
    api_vacancy_toggle_active,
    api_vacancy_report, api_report_self_status_update, api_vacancy_moderation_update,
    api_moderator_delete_vacancy, api_moderator_report_restore,
)

urlpatterns = [
    path("", VacancyListView.as_view(), name="vacancy-list"),
    path("create/", vacancy_create, name="vacancy-create"),
    path("my/", my_vacancies, name="my-vacancies"),
    re_path(r"^(?P<pk>[\w-]+)/$", VacancyDetailView.as_view(), name="vacancy-detail"),
    path("<int:pk>/edit/", vacancy_edit, name="vacancy-edit"),
    path("<int:pk>/delete/", vacancy_delete, name="vacancy-delete"),
    path("<int:pk>/toggle-active/", api_vacancy_toggle_active, name="vacancy-toggle-active"),
    path("<int:pk>/report/", api_vacancy_report, name="vacancy-report"),
    path("api/reports/<int:pk>/self-status/", api_report_self_status_update, name="report-self-status"),
    path("api/reports/vacancy/<int:vacancy_id>/state/", api_vacancy_moderation_update, name="vacancy-moderation-state"),
    path("api/moderator/vacancy/<int:vacancy_id>/delete/", api_moderator_delete_vacancy, name="moderator-vacancy-delete"),
    path("api/admin/moderator-report/<int:report_id>/restore/", api_moderator_report_restore, name="moderator-report-restore"),
    path("<int:pk>/branded/", vacancy_branded_frame_view, name="vacancy-branded-frame"),
    path("api/employer-rating/<str:hh_id>/", employer_rating_api, name="employer-rating-api"),
    path("api/vacancy-description/<int:pk>/", vacancy_description_api, name="vacancy-description-api"),
]
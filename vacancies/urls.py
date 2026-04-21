from django.urls import path, re_path

from vacancies.views import (
    VacancyListView, VacancyDetailView,
    employer_rating_api, vacancy_description_api,
    vacancy_branded_frame_view,
    vacancy_create, vacancy_edit, vacancy_delete, my_vacancies,
    api_vacancy_toggle_active,
)

urlpatterns = [
    path("", VacancyListView.as_view(), name="vacancy-list"),
    path("create/", vacancy_create, name="vacancy-create"),
    path("my/", my_vacancies, name="my-vacancies"),
    re_path(r"^(?P<pk>[\w-]+)/$", VacancyDetailView.as_view(), name="vacancy-detail"),
    path("<int:pk>/edit/", vacancy_edit, name="vacancy-edit"),
    path("<int:pk>/delete/", vacancy_delete, name="vacancy-delete"),
    path("<int:pk>/toggle-active/", api_vacancy_toggle_active, name="vacancy-toggle-active"),
    path("<int:pk>/branded/", vacancy_branded_frame_view, name="vacancy-branded-frame"),
    path("api/employer-rating/<str:hh_id>/", employer_rating_api, name="employer-rating-api"),
    path("api/vacancy-description/<int:pk>/", vacancy_description_api, name="vacancy-description-api"),
]
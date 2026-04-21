import json
import random
import re
import uuid

from faker import Faker
from locust import HttpUser, SequentialTaskSet, TaskSet, between, task

fake = Faker("ru_RU")
Faker.seed(0)

SEARCH_TERMS = [
    "python", "django", "менеджер", "java", "разработчик",
    "аналитик", "дизайнер", "маркетолог", "бухгалтер", "водитель",
    "продавец", "инженер", "тестировщик", "DevOps", "data scientist",
]

REGIONS = [
    "Москва", "Санкт-Петербург", "Екатеринбург",
    "Новосибирск", "Казань", "Нижний Новгород",
]

EXPERIENCE_IDS = ["noExperience", "between1And3", "between3And6", "moreThan6"]

CITIZENSHIP_CODES = ["RU", "BY", "KZ", "KG", "AM", "TJ", "UZ"]

SORT_OPTIONS = ["", "salary", "salary_asc"]

WORK_FORMATS = ["remote", "hybrid", "onsite"]

SALARY_LEVELS = [30_000, 50_000, 80_000, 100_000, 150_000, 200_000]

_discovered_vacancy_ids: list[int] = []

def _csrf(client) -> str:
    return client.cookies.get("csrftoken", "")


def _json_headers(client) -> dict:
    return {
        "Content-Type": "application/json",
        "X-CSRFToken": _csrf(client),
    }

def _extract_vacancy_ids(html: str) -> list[int]:
    ids = re.findall(r"/vacancies/(\d+)/", html or "")
    return [int(i) for i in set(ids)]

def _random_phone() -> str:
    digits = "".join(str(random.randint(0, 9)) for _ in range(9))
    return f"79{digits}"

def _make_applicant_payload() -> dict:
    uid = uuid.uuid4().hex[:10]
    first_name = fake.first_name()
    last_name = fake.last_name()
    username = f"u_{uid}"

    return {
        "last_name":        last_name,
        "first_name":       first_name,
        "patronymic":       fake.middle_name(),
        "username":         username,
        "email":            f"{uid}@locust.invalid",
        "telegram":         f"@{username}",
        "phone":            _random_phone(),
        "gender":           random.choice(["M", "F"]),
        "city":             random.choice(REGIONS),
        "birth_date":       fake.date_of_birth(minimum_age=18, maximum_age=50).isoformat(),
        "citizenship":      random.choice(CITIZENSHIP_CODES),
        "password":         "LocustPass1!",
        "consent_email":    False,
        "consent_telegram": False,
    }

class AnonymousBrowseTasks(TaskSet):
    @task(10)
    def browse_homepage(self):
        resp = self.client.get("/", name="[GET] Главная / все вакансии")
        ids = _extract_vacancy_ids(resp.text)
        if ids:
            _discovered_vacancy_ids.extend(ids)
            del _discovered_vacancy_ids[300:]

    @task(10)
    def search_vacancies_by_keyword(self):
        term = random.choice(SEARCH_TERMS)
        self.client.get(f"/?q={term}", name="[GET] Поиск по ключевому слову")

    @task(8)
    def filter_by_salary(self):
        salary_min = random.choice(SALARY_LEVELS)
        self.client.get(
            f"/?only_with_salary=1&salary_min={salary_min}",
            name="[GET] Фильтр: с зарплатой ≥ N",
        )

    @task(7)
    def filter_by_experience_and_format(self):
        exp = random.choice(EXPERIENCE_IDS)
        fmt = random.choice(WORK_FORMATS)
        self.client.get(
            f"/?experience={exp}&format={fmt}",
            name="[GET] Фильтр: опыт + формат работы",
        )

    @task(5)
    def search_with_combined_filters_and_sort(self):
        term    = random.choice(SEARCH_TERMS)
        exp     = random.choice(EXPERIENCE_IDS)
        sort    = random.choice(SORT_OPTIONS)
        sal_min = random.choice(SALARY_LEVELS)
        self.client.get(
            f"/?q={term}&experience={exp}&only_with_salary=1"
            f"&salary_min={sal_min}&sort={sort}",
            name="[GET] Комбинированный поиск с сортировкой",
        )

    @task(2)
    def register_new_applicant(self):
        self.client.get("/accounts/register/", name="[GET] Страница регистрации")

        payload = _make_applicant_payload()
        self.client.post(
            "/accounts/api/register/",
            data=json.dumps(payload),
            headers=_json_headers(self.client),
            name="[POST] Регистрация нового соискателя",
        )

class RegistrationAndLoginFlow(SequentialTaskSet):

    def on_start(self):
        self._creds = _make_applicant_payload()
        self._target_vacancy_id = None

    @task
    def s01_homepage(self):
        resp = self.client.get("/", name="[SEQ][GET] 01 Главная страница")
        ids = _extract_vacancy_ids(resp.text)
        if ids:
            self._target_vacancy_id = random.choice(ids)
            _discovered_vacancy_ids.extend(ids)
            del _discovered_vacancy_ids[300:]

    @task
    def s02_search_vacancies(self):
        term = random.choice(SEARCH_TERMS)
        resp = self.client.get(f"/?q={term}", name="[SEQ][GET] 02 Поиск вакансий")
        ids = _extract_vacancy_ids(resp.text)
        if ids and not self._target_vacancy_id:
            self._target_vacancy_id = random.choice(ids)

    @task
    def s03_filter_vacancies(self):
        exp = random.choice(EXPERIENCE_IDS)
        self.client.get(
            f"/?experience={exp}&only_with_salary=1",
            name="[SEQ][GET] 03 Фильтрация вакансий",
        )

    @task
    def s04_view_vacancy_detail(self):
        pk = self._target_vacancy_id or (
            random.choice(_discovered_vacancy_ids) if _discovered_vacancy_ids else None
        )
        if pk:
            self.client.get(f"/vacancies/{pk}/", name="[SEQ][GET] 04 Страница вакансии")
        else:
            self.client.get("/", name="[SEQ][GET] 04 Главная (нет ID)")

    @task
    def s05_view_terms(self):
        self.client.get("/accounts/terms/", name="[SEQ][GET] 05 Условия использования")

    @task
    def s06_registration_page(self):
        self.client.get("/accounts/register/", name="[SEQ][GET] 06 Страница регистрации")

    @task
    def s07_submit_registration(self):
        resp = self.client.post(
            "/accounts/api/register/",
            data=json.dumps(self._creds),
            headers=_json_headers(self.client),
            name="[SEQ][POST] 07 Регистрация пользователя",
        )
        if resp.status_code != 200:
            self._creds = _make_applicant_payload()
            self.interrupt()

    @task
    def s08_login_page(self):
        self.client.get("/accounts/login/", name="[SEQ][GET] 08 Страница входа")

    @task
    def s09_submit_login(self):
        resp = self.client.post(
            "/accounts/api/login/",
            data=json.dumps({
                "username": self._creds["username"],
                "password": self._creds["password"],
            }),
            headers=_json_headers(self.client),
            name="[SEQ][POST] 09 Вход в систему",
        )
        if resp.status_code != 200:
            self.interrupt()

    @task
    def s10_homepage_authenticated(self):
        resp = self.client.get("/", name="[SEQ][GET] 10 Главная (авт.)")
        ids = _extract_vacancy_ids(resp.text)
        if ids:
            self._target_vacancy_id = random.choice(ids)
            _discovered_vacancy_ids.extend(ids)

    @task
    def s11_search_authenticated(self):
        term = random.choice(SEARCH_TERMS)
        self.client.get(f"/?q={term}", name="[SEQ][GET] 11 Поиск (авт.)")

    @task
    def s12_vacancy_detail_authenticated(self):
        pk = self._target_vacancy_id or (
            random.choice(_discovered_vacancy_ids) if _discovered_vacancy_ids else None
        )
        if pk:
            self.client.get(f"/vacancies/{pk}/", name="[SEQ][GET] 12 Вакансия (авт.)")

    @task
    def s13_profile_page(self):
        self.client.get("/accounts/profile/", name="[SEQ][GET] 13 Профиль соискателя")

    @task
    def s14_profile_data_api(self):
        self.client.get(
            "/accounts/api/profile-data/",
            name="[SEQ][GET] 14 Данные профиля (API)",
        )

    @task
    def s15_applicant_analytics(self):
        self.client.get(
            "/accounts/api/analytics/",
            name="[SEQ][GET] 15 Аналитика соискателя (API)",
        )

    @task
    def s16_bookmark_vacancy(self):
        pk = self._target_vacancy_id or (
            random.choice(_discovered_vacancy_ids) if _discovered_vacancy_ids else None
        )
        if pk:
            self.client.post(
                f"/accounts/api/bookmark/{pk}/",
                headers={"X-CSRFToken": _csrf(self.client)},
                name="[SEQ][POST] 16 Закладка вакансии",
            )

    @task
    def s17_update_profile(self):
        self.client.patch(
            "/accounts/api/profile/update/",
            data=json.dumps({
                "city":             random.choice(REGIONS),
                "about_me":         fake.text(max_nb_chars=150),
                "desired_position": fake.job()[:255],
                "salary_expectation_from": random.choice(SALARY_LEVELS),
            }),
            headers=_json_headers(self.client),
            name="[SEQ][PATCH] 17 Обновить профиль",
        )

    @task
    def s18_view_updated_profile(self):
        self.client.get("/accounts/profile/", name="[SEQ][GET] 18 Профиль (после обновления)")

    @task
    def s19_browse_before_logout(self):
        self.client.get("/?format=remote", name="[SEQ][GET] 19 Удалённые вакансии (перед выходом)")

    @task
    def s20_logout(self):
        self.client.post(
            "/accounts/api/logout/",
            data=json.dumps({}),
            headers=_json_headers(self.client),
            name="[SEQ][POST] 20 Выход из системы",
        )
        self.interrupt()

class AnonymousVisitor(HttpUser):
    tasks     = [AnonymousBrowseTasks]
    wait_time = between(1, 3)
    weight    = 3


class NewApplicant(HttpUser):
    tasks     = [RegistrationAndLoginFlow]
    wait_time = between(2, 5)
    weight    = 1
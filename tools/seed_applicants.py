import django, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import User
from accounts.models import Applicant

USERS = [
    {
        'username': 'ivanov_a',
        'first_name': 'Алексей',
        'last_name': 'Иванов',
        'email': 'ivanov@example.com',
        'applicant': {
            'patronymic': 'Сергеевич',
            'phone': '+7 900 111-22-33',
            'city': 'Москва',
            'gender': 'M',
            'skills': ['Python', 'Django', 'PostgreSQL', 'REST API', 'Docker'],
            'location_type': 'metro',
            'metro_station_name': 'Курская',
            'metro_line_name': 'Кольцевая',
            'metro_line_color': 'b44f22',
        }
    },
    {
        'username': 'petrova_m',
        'first_name': 'Мария',
        'last_name': 'Петрова',
        'email': 'petrova@example.com',
        'applicant': {
            'patronymic': 'Игоревна',
            'phone': '+7 912 333-44-55',
            'city': 'Санкт-Петербург',
            'gender': 'F',
            'skills': ['JavaScript', 'React', 'TypeScript', 'CSS', 'Node.js', 'Figma'],
            'location_type': 'address',
            'address': 'Невский проспект, 28',
        }
    },
    {
        'username': 'sidorov_k',
        'first_name': 'Кирилл',
        'last_name': 'Сидоров',
        'email': 'sidorov@example.com',
        'applicant': {
            'patronymic': 'Олегович',
            'phone': '+7 926 555-66-77',
            'city': 'Москва',
            'gender': 'M',
            'skills': ['Java', 'Spring Boot', 'Kafka', 'Kubernetes', 'SQL', 'Redis', 'Microservices'],
            'location_type': 'metro',
            'metro_station_name': 'Белорусская',
            'metro_line_name': 'Замоскворецкая',
            'metro_line_color': '00853e',
        }
    },
]

for u_data in USERS:
    a_data = u_data.pop('applicant')
    u, created = User.objects.get_or_create(username=u_data['username'], defaults=u_data)
    if created:
        u.set_password('testpass123')
        u.save()
    a, _ = Applicant.objects.get_or_create(user=u)
    for k, v in a_data.items():
        setattr(a, k, v)
    a.save()
    status = 'created' if created else 'updated'
    print(status + ': ' + u.get_full_name() + ' (' + u.username + ')')

print('Done.')

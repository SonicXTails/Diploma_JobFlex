import os
import django
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from vacancies.models import Employer

hh_id = '600589'
new_rating = 3.5

emp = Employer.objects.filter(hh_id=hh_id).first()
if not emp:
    print('Employer not found:', hh_id)
else:
    emp.hh_rating = new_rating
    emp.rating_raw = str(new_rating)
    emp.rating_updated_at = timezone.now()
    emp.save(update_fields=['hh_rating', 'rating_raw', 'rating_updated_at'])
    print('Updated employer', emp.id, 'hh_id', emp.hh_id, '->', emp.hh_rating)

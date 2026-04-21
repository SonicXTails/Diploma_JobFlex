import os,sys,json
sys.path.insert(0,'.')
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from vacancies.models import Vacancy
qs=Vacancy.objects.exclude(raw_json={})[:50]
for v in qs:
    r=v.raw_json if isinstance(v.raw_json,dict) else {}
    addr=r.get('address')
    print('---',v.pk,v.region)
    print('address type:', type(addr).__name__)
    print('address repr:', repr(addr)[:400])
    if isinstance(addr,dict):
        for k in ('raw','value','display','lat','lng','city','street','building','house'):
            if k in addr:
                print('  ',k,':',addr.get(k))
    area=r.get('area')
    if area:
        print(' area:', repr(area)[:200])
    print()
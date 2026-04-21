"""
Seed HhArea and HhDictionaryItem from local JSON files.
Run with: python manage.py shell < tools/seed_filters.py
Or: python manage.py runscript tools/seed_filters  (with django-extensions)
"""
import json, os, django, sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
django.setup()

from django.db import transaction
from vacancies.models import HhArea, HhDictionaryItem

# ---- Areas ----
with open(os.path.join(BASE, "tools", "hh_areas.json"), encoding="utf-8") as f:
    areas_payload = json.load(f)


def iter_area_nodes(nodes, parent_id=""):
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        item_id = node.get("id")
        if not item_id:
            continue
        flat = dict(node)
        flat["_parent_id"] = str(node.get("parent_id") or parent_id or "")
        yield flat
        yield from iter_area_nodes(node.get("areas") or [], parent_id=str(item_id))


area_objs = [
    HhArea(
        area_id=str(a.get("id") or ""),
        name=str(a.get("name") or ""),
        parent_id=str(a.get("_parent_id") or ""),
        raw_json=a,
    )
    for a in iter_area_nodes(areas_payload)
    if a.get("id")
]

with transaction.atomic():
    HhArea.objects.all().delete()
    HhArea.objects.bulk_create(area_objs, batch_size=500)
print(f"Areas inserted: {HhArea.objects.count()}")

# ---- Dictionaries ----
with open(os.path.join(BASE, "tools", "hh_dictionaries.json"), encoding="utf-8") as f:
    dicts_payload = json.load(f)

dict_objs = []
for dict_name, items in dicts_payload.items():
    if not isinstance(items, list):
        continue
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        name = str(item.get("name") or item.get("text") or "")
        if not item_id or not name:
            continue
        dict_objs.append(HhDictionaryItem(
            dictionary=dict_name,
            item_id=item_id,
            name=name,
            raw_json=item,
        ))

with transaction.atomic():
    HhDictionaryItem.objects.all().delete()
    HhDictionaryItem.objects.bulk_create(dict_objs, batch_size=500)
print(f"Dictionary items inserted: {HhDictionaryItem.objects.count()}")

# ---- Verify ----
print(f"Regions (parent=113): {HhArea.objects.filter(parent_id='113').count()}")
for d in ["experience", "schedule", "employment", "employment_form"]:
    items = list(HhDictionaryItem.objects.filter(dictionary=d).values_list("item_id", "name"))
    print(f"  [{d}]: {items}")

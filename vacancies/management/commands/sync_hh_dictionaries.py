import json
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand

from vacancies.models import HhArea, HhDictionaryItem


class Command(BaseCommand):
    help = "Sync HH dictionaries and areas into local database"

    def handle(self, *args, **options):
        areas_payload = self._fetch_json("https://api.hh.ru/areas")
        dictionaries_payload = self._fetch_json("https://api.hh.ru/dictionaries")

        areas_created, areas_updated = self._save_areas(areas_payload)
        dict_created, dict_updated = self._save_dictionaries(dictionaries_payload)

        self.stdout.write(self.style.SUCCESS(
            "Done. "
            f"Areas created={areas_created}, updated={areas_updated}. "
            f"Dictionary items created={dict_created}, updated={dict_updated}."
        ))

    def _fetch_json(self, url):
        request = Request(url, headers={"User-Agent": "job-aggregator-diploma/1.0"})
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def _save_areas(self, payload):
        created_count = 0
        updated_count = 0

        for area in self._iter_area_nodes(payload):
            defaults = {
                "name": str(area.get("name") or ""),
                "parent_id": str(area.get("_parent_id") or ""),
                "raw_json": area,
            }
            _, created = HhArea.objects.update_or_create(
                area_id=str(area.get("id") or ""),
                defaults=defaults,
            )
            created_count += int(created)
            updated_count += int(not created)

        return created_count, updated_count

    def _iter_area_nodes(self, nodes, parent_id=""):
        if not isinstance(nodes, list):
            return

        for node in nodes:
            if not isinstance(node, dict):
                continue

            item_id = node.get("id")
            if not item_id:
                continue

            flat_node = dict(node)
            flat_node["_parent_id"] = str(node.get("parent_id") or parent_id or "")
            yield flat_node

            children = node.get("areas") or []
            yield from self._iter_area_nodes(children, parent_id=str(item_id))

    def _save_dictionaries(self, payload):
        created_count = 0
        updated_count = 0

        if not isinstance(payload, dict):
            return created_count, updated_count

        for dictionary_name, items in payload.items():
            for item in self._iter_dictionary_items(items):
                item_id = str(item.get("id") or "")
                name = str(item.get("name") or item.get("text") or "")
                if not item_id or not name:
                    continue

                defaults = {
                    "name": name,
                    "parent_id": str(item.get("parent_id") or ""),
                    "raw_json": item,
                }
                _, created = HhDictionaryItem.objects.update_or_create(
                    dictionary=str(dictionary_name),
                    item_id=item_id,
                    defaults=defaults,
                )
                created_count += int(created)
                updated_count += int(not created)

        return created_count, updated_count

    def _iter_dictionary_items(self, items):
        if not isinstance(items, list):
            return

        for item in items:
            if not isinstance(item, dict):
                continue

            yield item

            children = item.get("items") or []
            if isinstance(children, list):
                yield from self._iter_dictionary_items(children)

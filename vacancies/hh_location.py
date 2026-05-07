"""Normalize country/region from HH vacancy JSON (list or detail)."""

_CIS_COUNTRY_NAMES = frozenset({
    "Казахстан",
    "Беларусь",
    "Узбекистан",
    "Грузия",
    "Армения",
    "Кыргызстан",
    "Азербайджан",
})
# HH area id for Россия at the top of the tree (used when name is unreliable).
_RUSSIA_ROOT_AREA_IDS = frozenset({"113"})


def extract_country_region_from_hh_item(item: dict) -> tuple[str, str]:
    """Return (country, region) for Vacancy.country / Vacancy.region.

    List items often have area = Россия and the city only under address.
    """
    if not isinstance(item, dict):
        return "Россия", ""

    area = item.get("area")
    if not isinstance(area, dict):
        area = {}
    area_name = str(area.get("name") or "").strip()
    area_id = str(area.get("id") or "").strip()

    addr = item.get("address")
    if not isinstance(addr, dict):
        addr = {}
    city = str(addr.get("city") or "").strip()
    raw_addr = str(addr.get("raw") or "").strip()

    if area_name in _CIS_COUNTRY_NAMES:
        return area_name, ""

    country = "Россия"

    def _trim_region(s: str, max_len: int = 128) -> str:
        s = (s or "").strip()
        return s[:max_len] if len(s) > max_len else s

    region = area_name

    is_russia_blob = (
        area_name in ("Россия", "РФ")
        or area_id in _RUSSIA_ROOT_AREA_IDS
    )
    if is_russia_blob and city:
        region = city
    elif not region and city:
        region = city
    elif not region and raw_addr:
        region = _trim_region(raw_addr)

    return country, _trim_region(region)

import json
import re
import html as _html_unescape
from urllib.request import Request, urlopen

USER_AGENT = 'job-aggregator-diploma/1.0'


def fetch_dreamjob_page(url: str) -> str:
    req = Request(url, headers={'User-Agent': USER_AGENT})
    with urlopen(req, timeout=20) as r:
        return r.read().decode('utf-8', errors='replace')


def normalize_company_name(name: str) -> str:
    if not name:
        return ''
    s = name.lower()
    # remove common legal forms and punctuation
    s = re.sub(r'\b(ooo|ооо|zao|zao\.|пao|пao\.|пao|pao|ao|ао|pa|llc|inc|ltd|gmbh|ooo\.|ооо\.|зао|ип)\b', '', s)
    s = re.sub(r'[\W_]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def search_employer_links_by_name(name: str) -> list:
    """Try several DreamJob search URL patterns to find employer links by name.

    Returns list of absolute URLs (strings).
    """
    base = 'https://dreamjob.ru'
    q = re.sub(r'\s+', '+', name.strip())
    candidates = [
        f'{base}/search?query={q}',
        f'{base}/search/?query={q}',
        f'{base}/search?q={q}',
        f'{base}/search/?q={q}',
        f'{base}/companies?query={q}',
        f'{base}/companies/search?query={q}',
    ]
    found = []
    for url in candidates:
        try:
            html = fetch_dreamjob_page(url)
        except Exception:
            continue
        # unescape and find /employers/<id> links
        t = _html_unescape.unescape(html)
        for m in re.finditer(r'href=["\'](/employers/\d+)["\']', t, re.I):
            u = base + m.group(1)
            if u not in found:
                found.append(u)
        if found:
            break
    return found


def extract_company_name_from_html(text: str) -> str | None:
    t = _html_unescape.unescape(text)
    # try common patterns
    m = re.search(r'Отзывы сотрудников о компании\s*([^<\n\r]+)', t, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r'Работа в\s*([^<\n\r]+)', t, re.I)
    if m:
        # trim trailing words like 'ᐈ' or '—'
        name = m.group(1).strip()
        name = re.split(r'[\u2014\-\u203A\u2039\u203A\u2022\u00B7\u00BB\u00AB\s]{1,}', name)[0]
        return name.strip()
    # fallback: title tag
    m = re.search(r'<title[^>]*>(.*?)</title>', t, re.I | re.S)
    if m:
        title = re.sub('<[^<]+?>', '', m.group(1)).strip()
        # try to extract last token after 'в ' or 'в компании '
        m2 = re.search(r'в\s+(.+)', title)
        if m2:
            return m2.group(1).split(' ᐈ')[0].strip()
    return None


def extract_rating_from_html(text: str) -> str | None:
    t = _html_unescape.unescape(text)
    # JSON-LD
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', t, re.S | re.I):
        try:
            obj = json.loads(m.group(1))
            agg = obj.get('aggregateRating') or (obj if isinstance(obj, dict) else None)
            if isinstance(agg, dict):
                v = agg.get('ratingValue') or agg.get('rating')
                if v:
                    return str(v)
        except Exception:
            continue

    # specific DreamJob markup: rating-val">4,1 or data-rating="4.1"
    m = re.search(r'rating-val["\'>\s]*>([0-5][\.,][0-9])', t, re.I)
    if m:
        return m.group(1)

    m = re.search(r'data-rating["\']?\s*[:=]?\s*["\']?([0-5][\.,][0-9])["\']?', t, re.I)
    if m:
        return m.group(1)

    # generic JS key like Rating:"3.5"
    m = re.search(r'Rating["\']?\s*[:=]\s*["\']?([0-5](?:[\.,][0-9])?)["\']?', t, re.I)
    if m:
        return m.group(1)

    # visible text near word 'рейтинг'
    m = re.search(r'рейтинг[^\d]{0,40}([0-5](?:[\.,][0-9])?)', t, re.I)
    if m:
        return m.group(1)

    return None


def parse_rating_candidate(value: str) -> float | None:
    if value is None:
        return None
    try:
        s = str(value).strip().replace(',', '.')
        v = float(s)
        if 0 <= v <= 5:
            return v
    except Exception:
        return None
    return None
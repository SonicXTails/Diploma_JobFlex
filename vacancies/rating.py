from typing import Any, Optional, Tuple


def extract_rating_candidate(payload: Any) -> Optional[str]:
    """Return first candidate rating found in payload dict."""
    if not isinstance(payload, dict):
        return None
    for k in ('hh_rating', 'rating', 'rating_avg', 'rating_value', 'rating_raw'):
        v = payload.get(k)
        if v:
            return v
    hh = payload.get('hh')
    if isinstance(hh, dict):
        for k in ('rating', 'ratingValue', 'rating_avg', 'rating_value', 'hh_rating', 'rating_raw'):
            v = hh.get(k)
            if v:
                return v
    return None


def parse_rating(value: Any) -> Optional[float]:
    """Parse numeric rating (0..5) from various input types."""
    if value is None:
        return None
    try:
        v = float(value) if isinstance(value, (int, float)) else float(str(value).strip().replace(',', '.'))
    except Exception:
        return None
    return v if 0 <= v <= 5 else None


def _positive(value) -> Optional[float]:
    """Parse rating, treating 0 as missing."""
    v = parse_rating(value)
    return v if v and v > 0 else None


def compute_vacancy_rating(vacancy) -> Tuple[str, Optional[float], Optional[str]]:
    """Compute display rating for a vacancy.

    Returns (display_string, numeric_value_or_None, raw_candidate_or_None).
    """
    emp = getattr(vacancy, 'employer', None)
    if not emp:
        return '', None, None

    hh = _positive(getattr(emp, 'hh_rating', None))
    dj = _positive(getattr(emp, 'dreamjob_rating', None))

    if hh and dj:
        avg = round((hh + dj) / 2, 2)
        raw = f"hh:{getattr(emp, 'rating_raw', '') or ''}|dj:{getattr(emp, 'dreamjob_rating_raw', '') or ''}"
        return f"{avg:.1f}", avg, raw[:128]

    if hh:
        return f"{hh:.1f}", hh, str(getattr(emp, 'hh_rating', ''))[:128]
    if dj:
        return f"{dj:.1f}", dj, str(getattr(emp, 'dreamjob_rating', ''))[:128]

    # Fallback: employer.raw payload
    candidate = extract_rating_candidate(getattr(emp, 'raw', None) or {})
    parsed = parse_rating(candidate)
    if parsed is not None:
        return f"{parsed:.1f}", parsed, str(candidate)[:128] if candidate else None

    return '', None, None
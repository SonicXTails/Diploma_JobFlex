from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def ru_timesince(value):
    """Return a human-readable Russian time-ago string for a datetime."""
    if not value:
        return ''
    now = timezone.now()
    try:
        diff = now - value
    except TypeError:
        return ''

    total_seconds = int(diff.total_seconds())
    if total_seconds < 0:
        return 'только что'

    minutes = total_seconds // 60
    hours   = minutes   // 60
    days    = hours     // 24
    weeks   = days      // 7
    months  = days      // 30
    years   = days      // 365

    def plural(n, one, few, many):
        n = abs(n) % 100
        n1 = n % 10
        if 11 <= n <= 19:
            return many
        if n1 == 1:
            return one
        if 2 <= n1 <= 4:
            return few
        return many

    if total_seconds < 60:
        return 'только что'
    if minutes < 60:
        return f'{minutes} {plural(minutes, "минуту", "минуты", "минут")} назад'
    if hours < 24:
        return f'{hours} {plural(hours, "час", "часа", "часов")} назад'
    if days < 7:
        return f'{days} {plural(days, "день", "дня", "дней")} назад'
    if weeks < 5:
        return f'{weeks} {plural(weeks, "неделю", "недели", "недель")} назад'
    if months < 12:
        return f'{months} {plural(months, "месяц", "месяца", "месяцев")} назад'
    return f'{years} {plural(years, "год", "года", "лет")} назад'


@register.filter
def salary_fmt(value):
    """Format a salary integer as '100 000' with thin-space thousands separator."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return ''
    # Format with non-breaking thin space (U+202F) as thousands separator
    formatted = f'{n:,}'.replace(',', '\u202f')
    return formatted


@register.simple_tag
def salary_range(salary_from, salary_to, currency=''):
    """
    Return formatted salary string.
    • If both values are equal: show only once.
    • If only one is set: prefix with 'от' / 'до'.
    • Thousands-formatted with narrow no-break space.
    """
    def fmt(v):
        try:
            n = int(v)
            return f'{n:,}'.replace(',', '\u202f')
        except (TypeError, ValueError):
            return ''

    cur = f' {currency}' if currency else ''

    if salary_from and salary_to:
        f = int(salary_from)
        t = int(salary_to)
        if f == t:
            return f'{fmt(f)}{cur}'
        return f'{fmt(f)} — {fmt(t)}{cur}'
    if salary_from:
        return f'от {fmt(salary_from)}{cur}'
    if salary_to:
        return f'до {fmt(salary_to)}{cur}'
    return ''

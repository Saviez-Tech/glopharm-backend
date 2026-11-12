"""
Shared date filter for the admin order cards AND the admin order list, so both
always agree.

Query params (use at most ONE; none = all time):
    period=today | this_month | this_year
    date=YYYY-MM-DD        a specific day
    month=YYYY-MM          a specific month
    year=YYYY              a specific year
"""
from datetime import date, datetime, time, timedelta

from django.utils import timezone


class PeriodFilterError(ValueError):
    pass


def _start_of(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _day_range(day):
    return _start_of(day), _start_of(day + timedelta(days=1))


def _month_range(year, month):
    first = date(year, month, 1)
    next_first = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return _start_of(first), _start_of(next_first)


def _year_range(year):
    return _start_of(date(year, 1, 1)), _start_of(date(year + 1, 1, 1))


def _parse(value, fmt, message):
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        raise PeriodFilterError(message)


def apply_period_filter(queryset, params):
    """
    Returns (filtered_queryset, info). Ranges are half-open [start, end) on
    `created_at`, in the project's timezone, so they can use an index.
    Raises PeriodFilterError with a message that is safe to show.
    """
    given = [key for key in ("period", "date", "month", "year") if params.get(key)]
    if len(given) > 1:
        raise PeriodFilterError("Use only one of: period, date, month, year.")

    if not given:
        return queryset, {"filter": "all", "value": None}

    key = given[0]
    value = params[key].strip()
    today = timezone.localdate()

    if key == "period":
        if value == "today":
            start, end = _day_range(today)
            info = {"filter": "today", "value": today.isoformat()}
        elif value == "this_month":
            start, end = _month_range(today.year, today.month)
            info = {"filter": "this_month", "value": today.strftime("%Y-%m")}
        elif value == "this_year":
            start, end = _year_range(today.year)
            info = {"filter": "this_year", "value": str(today.year)}
        else:
            raise PeriodFilterError("period must be one of: today, this_month, this_year.")

    elif key == "date":
        day = _parse(value, "%Y-%m-%d", "date must be in the format YYYY-MM-DD.").date()
        start, end = _day_range(day)
        info = {"filter": "date", "value": day.isoformat()}

    elif key == "month":
        parsed = _parse(value, "%Y-%m", "month must be in the format YYYY-MM.")
        start, end = _month_range(parsed.year, parsed.month)
        info = {"filter": "month", "value": parsed.strftime("%Y-%m")}

    else:  # year
        parsed = _parse(value, "%Y", "year must be in the format YYYY.")
        start, end = _year_range(parsed.year)
        info = {"filter": "year", "value": str(parsed.year)}

    return queryset.filter(created_at__gte=start, created_at__lt=end), info
"""Expand a five-field cron expression into the sets of values it fires on.

Only what is needed to ask "do these two schedules ever fire in the same minute": ``*``, lists, ranges,
steps and the month/weekday names. Anything else raises ``ValueError`` and the caller treats the job's
timing as unknown rather than guessing.
"""

from __future__ import annotations

_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
    "nov": 11, "dec": 12, "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}


def _value(token: str, index: int) -> int:
    token = token.lower()
    if token.isdigit():
        return int(token)
    if token[:3] in _NAMES and len(token) in (3, 6, 7, 8, 9):
        return _NAMES[token[:3]]
    raise ValueError(f"unknown value {token!r}")


def _expand(field: str, index: int) -> frozenset[int]:
    lo, hi = _RANGES[index]
    out: set[int] = set()
    for part in field.split(","):
        base, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if step < 1:
            raise ValueError(f"bad step in {field!r}")
        if base in ("*", "?"):
            start, end = lo, hi
        elif "-" in base:
            a, b = base.split("-", 1)
            start, end = _value(a, index), _value(b, index)
        else:
            start = _value(base, index)
            end = hi if step_text else start
        top = 7 if index == 4 else hi  # Sunday may be written 7
        if not (lo <= start <= top and lo <= end <= top) or end < start:
            raise ValueError(f"out of range in {field!r}")
        out.update(v % 7 if index == 4 else v for v in range(start, end + 1, step))
    return frozenset(out)


def parse(expr: str) -> tuple[frozenset[int], ...]:
    """Return ``(minutes, hours, days_of_month, months, days_of_week)``."""
    fields = expr.split()
    if len(fields) == 6:  # a leading seconds field is not modelled; drop it
        fields = fields[1:]
    if len(fields) != 5:
        raise ValueError(f"expected 5 fields, got {len(fields)}")
    return tuple(_expand(f, i) for i, f in enumerate(fields))


def overlap(a: tuple[frozenset[int], ...], b: tuple[frozenset[int], ...]) -> bool:
    """True when both schedules can fire in the same minute of some day."""
    return all(x & y for x, y in zip(a, b))


def fires_per_day(parsed: tuple[frozenset[int], ...]) -> float:
    """Average firings per day over a year (months and days-of-month weigh in as fractions)."""
    minutes, hours, dom, months, dow = parsed
    per_day = len(minutes) * len(hours)
    day_share = (len(months) / 12) * (len(dom) / 31 if len(dom) < 31 else 1)
    week_share = len(dow) / 7
    # when both day-of-month and day-of-week are restricted cron fires on either; keep the larger share
    if len(dom) < 31 and len(dow) < 7:
        day_share = (len(months) / 12) * max(len(dom) / 31, week_share)
        return per_day * day_share
    return per_day * day_share * week_share

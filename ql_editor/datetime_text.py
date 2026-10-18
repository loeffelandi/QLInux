"""Datum- und Uhrzeitformate, wie P-touch sie am Objekt anbietet.

Ein Stempel zeigt das Datum, die Uhrzeit oder beides. Die Quelle ist entweder
die aktuelle Zeit (auch beim Drucken) oder ein festes Datum. Ein Versatz
rechnet Minuten, Stunden, Tage, Wochen, Monate oder Jahre dazu oder ab.

Die Einträge in der Auswahl sind die formatierten Beispiele selbst
(„18.10.2026"), nicht das Muster. Monats- und Wochentagsnamen folgen der
Oberflächensprache, nicht dem Systemgebietsschema - sonst hinge ein Etikett
davon ab, welches Locale der Prozess gerade hat.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta

from .i18n import tr

DATE_FORMATS: tuple[str, ...] = (
    "dmy_dot",
    "ymd_slash",
    "iso",
    "dmy_short",
    "long",
    "weekday",
    "month_year",
)
TIME_FORMATS: tuple[str, ...] = ("hm", "hms", "hm12")
OFFSET_UNITS: tuple[str, ...] = (
    "minutes",
    "hours",
    "days",
    "weeks",
    "months",
    "years",
)

DATE_DEFAULT = "dmy_dot"
TIME_DEFAULT = "hm"
MODE_DEFAULT = "both"
UNIT_DEFAULT = "days"


def month_name(month: int) -> str:
    names = (
        tr("Januar"),
        tr("Februar"),
        tr("März"),
        tr("April"),
        tr("Mai"),
        tr("Juni"),
        tr("Juli"),
        tr("August"),
        tr("September"),
        tr("Oktober"),
        tr("November"),
        tr("Dezember"),
    )
    return names[month - 1]


def weekday_name(when: datetime) -> str:
    names = (
        tr("Montag"),
        tr("Dienstag"),
        tr("Mittwoch"),
        tr("Donnerstag"),
        tr("Freitag"),
        tr("Samstag"),
        tr("Sonntag"),
    )
    return names[when.weekday()]


def unit_label(unit: str) -> str:
    labels = {
        "minutes": tr("Minuten"),
        "hours": tr("Stunden"),
        "days": tr("Tage"),
        "weeks": tr("Wochen"),
        "months": tr("Monate"),
        "years": tr("Jahre"),
    }
    return labels.get(unit, tr("Tage"))


def format_date(when: datetime, key: str) -> str:
    """Datum in einem der bekannten Formate. Unbekanntes fällt auf den Standard."""
    day, month, year = when.day, when.month, when.year
    if key == "ymd_slash":
        return f"{year:04d}/{month:02d}/{day:02d}"
    if key == "iso":
        return f"{year:04d}-{month:02d}-{day:02d}"
    if key == "dmy_short":
        return f"{day:02d}.{month:02d}.{year % 100:02d}"
    if key == "long":
        return f"{day}. {month_name(month)} {year}"
    if key == "weekday":
        return f"{weekday_name(when)}, {day}. {month_name(month)} {year}"
    if key == "month_year":
        return f"{month_name(month)} {year}"
    return f"{day:02d}.{month:02d}.{year:04d}"


def format_time(when: datetime, key: str) -> str:
    """Uhrzeit. ``hm12`` ist die 12-Stunden-Form mit AM/PM."""
    if key == "hms":
        return f"{when.hour:02d}:{when.minute:02d}:{when.second:02d}"
    if key == "hm12":
        hour = when.hour % 12 or 12
        suffix = "AM" if when.hour < 12 else "PM"
        return f"{hour}:{when.minute:02d} {suffix}"
    return f"{when.hour:02d}:{when.minute:02d}"


def format_stamp(when: datetime, mode: str, date_key: str, time_key: str) -> str:
    if mode == "time":
        return format_time(when, time_key)
    if mode == "date":
        return format_date(when, date_key)
    return f"{format_date(when, date_key)} {format_time(when, time_key)}"


def shift(when: datetime, amount: int, unit: str) -> datetime:
    """``amount`` Einheiten dazuzählen. Negativ zieht sie ab.

    Monate und Jahre bleiben auf einem gültigen Tag: der 31. Januar plus ein
    Monat ist der 28. oder 29. Februar, nicht der 2. oder 3. März.
    """
    amount = int(amount)
    if amount == 0:
        return when
    if unit == "minutes":
        return when + timedelta(minutes=amount)
    if unit == "hours":
        return when + timedelta(hours=amount)
    if unit == "weeks":
        return when + timedelta(weeks=amount)
    if unit == "months":
        return _add_months(when, amount)
    if unit == "years":
        return _add_months(when, amount * 12)
    return when + timedelta(days=amount)


def _add_months(when: datetime, months: int) -> datetime:
    index = when.month - 1 + months
    year = when.year + index // 12
    month = index % 12 + 1
    day = min(when.day, calendar.monthrange(year, month)[1])
    return when.replace(year=year, month=month, day=day)

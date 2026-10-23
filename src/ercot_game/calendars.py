"""Released classroom schedule and the hourly source-block calendar.

The game (``CLASSROOM_SCHEDULE``) has three weeks of two submissions on one
representative-day package; the week decides whether grid purchases are
charged.

``half_year_calendar`` describes the hourly ACTIVSg2000 source blocks
(``jan_jun``/``jul_dec`` of 2027-2029) from which the representative days are
drawn.  It is a data-provenance helper for the package builders, not a game
schedule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import calendar as _calendar


@dataclass(frozen=True)
class HalfYearCalendar:
    """One hourly ACTIVSg2000 source block (half a calendar year)."""

    year: int
    round_name: str
    start_date: date
    end_date: date
    horizon: int
    source_row_start: int

    @property
    def label(self) -> str:
        return f"{self.year}_{self.round_name}"


@dataclass(frozen=True)
class WeeklyMatch:
    """The two submissions that form one classroom week."""

    week_id: str
    round_keys: tuple[str, str]
    feedback_only: bool = False
    # Whether grid purchases are charged at LMP in both submissions of the week.
    energy_cost_enabled: bool = False

    def __post_init__(self) -> None:
        round_keys = tuple(self.round_keys)
        if len(round_keys) != 2 or any(not key for key in round_keys):
            raise ValueError("a weekly match must contain exactly two round keys")
        if round_keys[0] == round_keys[1]:
            raise ValueError("a weekly match must contain two distinct round keys")
        object.__setattr__(self, "round_keys", round_keys)


SUPPORTED_YEARS = (2027, 2028, 2029)
_ROUND_MONTHS = {"jan_jun": (1, 6), "jul_dec": (7, 12)}


CLASSROOM_SCHEDULE = (
    WeeklyMatch(
        "week-1",
        ("week-1-submission-1", "week-1-submission-2"),
        feedback_only=True,
        energy_cost_enabled=False,
    ),
    WeeklyMatch(
        "week-2",
        ("week-2-submission-1", "week-2-submission-2"),
        energy_cost_enabled=False,
    ),
    WeeklyMatch(
        "week-3",
        ("week-3-submission-1", "week-3-submission-2"),
        energy_cost_enabled=True,
    ),
)

# The six round keys in play order.
ROUND_SEQUENCE = tuple(round_key for match in CLASSROOM_SCHEDULE for round_key in match.round_keys)


def weekly_match_for(round_key: str) -> WeeklyMatch:
    """Return the classroom week containing ``round_key``."""
    for match in CLASSROOM_SCHEDULE:
        if round_key in match.round_keys:
            return match
    raise ValueError(f"unknown classroom round key: {round_key}")


def half_year_calendar(year: int, round_name: str) -> HalfYearCalendar:
    """Return the calendar of one hourly ACTIVSg2000 source block."""
    if year not in SUPPORTED_YEARS:
        raise ValueError(f"year must be one of the supported years: {SUPPORTED_YEARS}")
    if round_name not in _ROUND_MONTHS:
        raise ValueError("round_name must be jan_jun or jul_dec")
    first_month, last_month = _ROUND_MONTHS[round_name]
    start = date(year, first_month, 1)
    end = date(year, last_month, _calendar.monthrange(year, last_month)[1])
    horizon = (end - start).days * 24 + 24
    return HalfYearCalendar(
        year=year,
        round_name=round_name,
        start_date=start,
        end_date=end,
        horizon=horizon,
        source_row_start=0 if round_name == "jan_jun" else (
            (date(year, 7, 1) - date(year, 1, 1)).days * 24
        ),
    )

from datetime import date

import pytest

from ercot_game.calendars import (
    CLASSROOM_SCHEDULE,
    HALF_YEAR_SCHEDULE,
    REPRESENTATIVE_SCHEDULE,
    half_year_calendar,
    weekly_match_for,
)


def test_half_year_calendar_uses_actual_leap_year_lengths():
    assert half_year_calendar(2028, "jan_jun").horizon == 4368
    assert half_year_calendar(2028, "jul_dec").horizon == 4416
    assert half_year_calendar(2027, "jan_jun").horizon == 4344
    assert half_year_calendar(2027, "jul_dec").horizon == 4416


def test_half_year_calendar_exposes_dates_and_source_offset():
    calendar = half_year_calendar(2027, "jan_jun")
    assert calendar.start_date == date(2027, 1, 1)
    assert calendar.end_date == date(2027, 6, 30)
    assert calendar.horizon == 4344
    assert calendar.source_row_start == 0


@pytest.mark.parametrize("year", [2015, 2019, 2020])
def test_half_year_calendar_rejects_years_without_released_artifacts(year):
    with pytest.raises(ValueError, match="supported years"):
        half_year_calendar(year, "jan_jun")


def test_half_year_calendar_rejects_unknown_round():
    with pytest.raises(ValueError, match="jan_jun or jul_dec"):
        half_year_calendar(2027, "annual")


def test_classroom_schedule_has_three_two_submission_weekly_matches():
    assert [match.week_id for match in CLASSROOM_SCHEDULE] == [
        "week-1",
        "week-2",
        "week-3",
    ]
    assert CLASSROOM_SCHEDULE is REPRESENTATIVE_SCHEDULE
    assert [match.round_keys for match in CLASSROOM_SCHEDULE] == [
        ("week-1-submission-1", "week-1-submission-2"),
        ("week-2-submission-1", "week-2-submission-2"),
        ("week-3-submission-1", "week-3-submission-2"),
    ]
    assert all(len(match.round_keys) == 2 for match in CLASSROOM_SCHEDULE)
    # Energy is charged in both submissions of week 3 only; week 1 is practice.
    assert [match.energy_cost_enabled for match in CLASSROOM_SCHEDULE] == [False, False, True]
    assert [match.feedback_only for match in CLASSROOM_SCHEDULE] == [True, False, False]


def test_retired_half_year_schedule_is_still_resolvable():
    assert [match.round_keys for match in HALF_YEAR_SCHEDULE] == [
        ("2027_jan_jun", "2027_jul_dec"),
        ("2028_jan_jun", "2028_jul_dec"),
        ("2029_jan_jun", "2029_jul_dec"),
    ]
    assert weekly_match_for("2028_jul_dec").week_id == "week-2"
    assert weekly_match_for("2028_jul_dec").energy_cost_enabled is None
    assert weekly_match_for("week-3-submission-2").energy_cost_enabled is True

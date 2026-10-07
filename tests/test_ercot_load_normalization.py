from datetime import datetime

from tools.ercot_loads.normalize import normalize_rows


def test_normalize_rows_converts_hour_ending_to_hour_start_and_zone_columns():
    rows = [
        {
            "Hour Ending": "01/01/2017 01:00",
            "COAST": 10,
            "EAST": 2,
            "FWEST": 3,
            "NORTH": 4,
            "NCENT": 5,
            "SOUTH": 6,
            "SCENT": 7,
            "WEST": 8,
            "ERCOT": 45,
        }
    ]
    normalized = normalize_rows(rows, year=2017)
    assert normalized == [
        {
            "timestamp_utc": "2017-01-01 00:00:00",
            "301": 3.0,
            "302": 4.0,
            "303": 8.0,
            "304": 6.0,
            "305": 5.0,
            "306": 7.0,
            "307": 10.0,
            "308": 2.0,
            "ercot_total_mw": 45.0,
        }
    ]


def test_normalize_rows_accepts_ercot_midnight_notation():
    row = {
        "Hour Ending": "01/01/2017 24:00",
        "COAST": 1, "EAST": 1, "FWEST": 1, "NORTH": 1,
        "NCENT": 1, "SOUTH": 1, "SCENT": 1, "WEST": 1,
        "ERCOT": 8,
    }
    assert normalize_rows([row], year=2017)[0]["timestamp_utc"] == "2017-01-01 00:00:00"


def test_normalize_rows_rejects_wrong_year_and_zone_total_mismatch():
    rows = [{
        "Hour Ending": "01/01/2017 01:00",
        "COAST": 1, "EAST": 1, "FWEST": 1, "NORTH": 1,
        "NCENT": 1, "SOUTH": 1, "SCENT": 1, "WEST": 1,
        "ERCOT": 100,
    }]
    try:
        normalize_rows(rows, year=2018)
    except ValueError as exc:
        assert "year" in str(exc) or "total" in str(exc)
    else:
        raise AssertionError("expected invalid ERCOT row to be rejected")

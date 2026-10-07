import csv

from tools.zenodo_texas.build_multiyear_demand import allocate_zone_loads


def test_allocate_zone_loads_preserves_zone_totals(tmp_path):
    bus = tmp_path / "bus.csv"
    with bus.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["bus_id", "Pd", "zone_id"])
        writer.writerows([
            ["b1", 10, 301], ["b2", 30, 301], ["b3", 20, 302],
            ["b4", 10, 303], ["b5", 10, 304], ["b6", 10, 305],
            ["b7", 10, 306], ["b8", 10, 307], ["b9", 10, 308],
        ])
    zone = tmp_path / "zone_load.csv"
    with zone.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp_utc", "301", "302", "303", "304", "305", "306", "307", "308", "ercot_total_mw"])
        writer.writerow(["2017-01-01 00:00:00", 100, 40, 0, 0, 0, 0, 0, 0, 140])
    output = tmp_path / "demand_bus.csv"
    summary = allocate_zone_loads(bus, zone, output)
    with output.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["b1"] == "25.0"
    assert rows[0]["b2"] == "75.0"
    assert rows[0]["b3"] == "40.0"
    assert summary["bus_count"] == 9
    assert summary["row_count"] == 1

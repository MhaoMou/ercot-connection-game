# Official ERCOT hourly load inputs

The multi-year extension uses the official ERCOT historical native-load
archives, reported by ERCOT weather zone:

- [2017 archive](https://www.ercot.com/files/docs/2018/01/09/native_load_2017.zip)
- [2018 archive](https://www.ercot.com/files/docs/2019/01/07/native_load_2018.zip)
- [ERCOT hourly-load archive index](https://www.ercot.com/gridinfo/load/load_hist)

The downloaded ZIP files are intentionally ignored by Git. To reproduce the
processed inputs, download them into this directory and run:

```bash
python -m tools.ercot_loads.normalize \
  --input data/raw/ercot_hourly_load/native_load_2017.xlsx \
  --year 2017 \
  --output data/processed/ercot_loads/2017_zone_load.csv

python -m tools.ercot_loads.normalize \
  --input data/raw/ercot_hourly_load/Native_Load_2018.xlsx \
  --year 2018 \
  --output data/processed/ercot_loads/2018_zone_load.csv
```

The normalizer preserves the workbook's 8,760-row sequence. ERCOT's workbook
contains a repeated daylight-saving-time hour and omits the spring-forward
hour; the builder assigns canonical calendar timestamps by row order so the
sequence remains deterministic and has one row per operating hour.

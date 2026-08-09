# VRF Analyzer

Analysis software for **Mitsubishi VRF** systems. It takes CSV logs exported from
Mitsubishi tools, **indexes** them into a fast columnar store, and **assesses**
the data against the **top 25 issues** common to VRF systems — surfacing findings
with severity, evidence, and recommended action in a web dashboard.

> Status: **working prototype**. 6 of the 25 detectors are implemented
> end-to-end; the remaining 19 are catalogued and wired, ready to implement.
> The CSV parser uses a profile layer that will be tuned to a real Mitsubishi
> export as soon as a sample is provided.

## Pipeline

```
CSV logs ──▶ ingest ──▶ index ──▶ assess ──▶ dashboard / report
           (profiles)  (Parquet   (top-25    (Streamlit UI,
                        + DuckDB)  detectors)  JSON export)
```

- **ingest** — `vrf_analyzer/ingest`: format *profiles* map each vendor CSV
  layout onto one normalized schema (`vrf_analyzer/schema.py`). Adapting a new
  export = one new profile.
- **index** — `vrf_analyzer/index`: writes a partitioned Parquet dataset
  (by system/unit) queried via DuckDB. Scales to large multi-day log sets.
- **rules** — `vrf_analyzer/rules`: a catalog of the 25 issues
  (`catalog.py`) plus pluggable detectors (`detectors.py`). Each detector is
  pure and tunable.
- **dashboard** — `dashboard/app.py`: Streamlit + Plotly UI. The engine is
  UI-agnostic, so the front-end can later be swapped for React without touching
  analysis code.

## Quick start

```bash
pip install -e .            # or: pip install -e ".[dev]" for tests

# 1. See it work end-to-end on synthetic faulted data
vrf demo

# 2. List the top-25 issue catalog and which detectors are live
vrf catalog

# 3. Point it at your own CSVs
vrf index path/to/logs/            # a file or a directory
vrf assess --report findings.json

# 4. Launch the dashboard (good UI)
streamlit run dashboard/app.py
```

The dashboard also runs standalone on **synthetic demo data** with no setup —
useful for exploring the UI before wiring in real logs.

## The top 25 issues

Run `vrf catalog`, or see `vrf_analyzer/rules/catalog.py`. Categories cover
refrigerant charge/leaks, pressures, compressor & electrical health, expansion
valves, airflow/coils, sensors, controls/communication, comfort, and efficiency.

**Live detectors in this prototype:** refrigerant undercharge, high discharge
temperature, compressor short-cycling, room-temp comfort deviation, thermistor
drift/failure, and fault-code rollup.

## Adapting to your CSV format

Mitsubishi exports differ by tool (Maintenance Tool / MN Converter, AE-200 /
EW-50 centralized controller, MELANNEX, Diamond service tool) and locale. Add or
edit a `Profile` in `vrf_analyzer/ingest/profiles.py`:

```python
Profile(
    name="my_export",
    column_map={"Date/Time": "timestamp", "Address": "unit_id", ...},
    datetime_columns=["Date/Time"],
    signature=["Date/Time", "Address"],   # used for auto-detection
)
```

`MITSUBISHI_MN` is a starter mapping with placeholder column names — share a
sample CSV and it gets corrected to match exactly.

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

## Roadmap

- Implement the remaining 19 detectors against real data.
- Saturated-temperature conversion (pressure → `cond_temp`/`evap_temp`) using
  the actual refrigerant (e.g. R410A/R32) for charge & coil diagnostics.
- Multi-day trend detectors (leak, COP degradation).
- Per-detector threshold calibration UI and exportable PDF reports.

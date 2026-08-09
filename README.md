# VRF Analyzer

Analysis software for **Mitsubishi VRF** systems. It takes CSV logs exported from
Mitsubishi tools, **indexes** them into a fast columnar store, and **assesses**
the data against the **top 25 issues** common to VRF systems — surfacing findings
with severity, evidence, and recommended action in a web dashboard.

> Status: **working prototype**. **All 25 detectors are implemented.** On a
> given dataset a detector either produces findings, stays silent, or reports
> `insufficient_data` when its required signals aren't present (e.g. comfort
> needs setpoints, which an outdoor-unit OM export lacks).
> The parser reads real **Mitsubishi MN Converter** service exports
> (auto-detected), converts R410A/R32 pressures to saturation temperatures, and
> derives system- and per-zone subcooling/superheat plus per-zone expansion-valve
> position for refrigerant-cycle diagnostics. Thermistor roles and protection
> thresholds are taken from the **PUMY-P NKMU technical & service manual**
> (see [References](#references)).

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
vrf risk                           # probability each failure mode is present

# 4. Launch the dashboard (good UI)
streamlit run dashboard/app.py
```

The dashboard also runs standalone on **synthetic demo data** with no setup —
useful for exploring the UI before wiring in real logs.

## Failure-mode probability

Beyond pass/fail findings, `vrf risk` (and the dashboard's **Failure-mode
probability** tab) reports a graded **probability that each of the 25 modes is
present**, ranked. Each mode's evidence is a per-sample severity ramp between a
`warn` level (condition starts to matter) and a `fail` level (clearly present),
aggregated over active operation by blending persistence with intensity. Healthy
axes sit near a 1% floor; borderline conditions show honest mid-range values;
modes whose signals are absent, or whose detector is not yet implemented, are
labelled rather than shown as 0%. This is a transparent heuristic confidence,
**not** a statistically calibrated probability — every score ships with the
evidence behind it (see `vrf_analyzer/scoring.py`).

## The top 25 issues

Run `vrf catalog`, or see `vrf_analyzer/rules/catalog.py`. Categories cover
refrigerant charge/leaks, pressures, compressor & electrical health, expansion
valves, airflow/coils, sensors, controls/communication, comfort, and efficiency.

**All 25 detectors are implemented.** Run `vrf catalog` for the list and each
one's default severity. They span refrigerant charge (under/overcharge, leak
trend), pressures and discharge temperature, expansion-valve and reversing-valve
faults, condenser/evaporator/airflow issues, compressor behaviour (short-cycling,
oil return, high current, part-load/oversizing), inverter overheat, sensors,
communications, comfort, mode conflict, efficiency trend, ambient limits, and
fault-code rollup.

### Diagnostic logic notes

- **Charge is judged by subcooling, not superheat.** On a LEV/TXV system the
  expansion valve holds evaporator superheat roughly constant, so superheat is
  not an independent charge indicator. The undercharge detector triggers on
  persistently low subcooling and only escalates to High when superheat is
  *also* elevated (the LEV has run out of travel).
- **Thresholds are manufacturer-grounded:** discharge (TH4) limiting ~110 °C /
  stop ~125 °C; high-pressure switch 4.15 MPa (601 psi); cooling envelope
  −5…46 °C, heating −25…21 °C; normal R410A superheat ~5–15 K, subcool
  ~4.5–8.5 K.
- **Thermistor roles** (PUMY-P): TH2 = HIC pipe, TH3 = outdoor liquid pipe,
  TH4 = compressor discharge, TH6 = suction pipe, TH7 = ambient, TH8 = heat
  sink.

## Supported formats

- **Mitsubishi MN Converter** service exports (CMS-MNG-E family, e.g.
  `OM_*.CSV`) — auto-detected. This is an outdoor-unit-centric wide format with
  a metadata preamble and a repeating per-indoor-unit block; parsed by
  `vrf_analyzer/ingest/mn_converter.py`. Raw pressures (63HS/63LS, psi) are
  converted to kPa and to saturated condensing/evaporating temperatures using
  the unit's refrigerant, so subcooling and suction superheat become available
  for diagnostics.
- **Canonical CSV** — files already in the normalized schema (what the synthetic
  generator emits).
- A trimmed, serial-redacted real export is committed at
  `data/sample/mn_converter_sample.CSV` and drives the regression tests.

Per-indoor `LEV{k}` (expansion-valve opening) and `SC{k}` (subcool, when
populated) are mapped to each indoor unit, and per-zone suction superheat is
derived from the indoor gas-pipe thermistor and the system evaporating
temperature. (`SCm`/`SCm{k}` "subcool target" is a dummy placeholder in these
exports and is deliberately ignored.)

On the sample PUMY-P36/48 export, the tool flags **persistently low subcooling**
(averaging ~1.2 K during 64% of run time, with normal ~6.7 K suction superheat) —
a "verify charge against commissioning" finding rather than a hard fault — plus
an **evaporator icing risk** (evaporating temperature dipping to −9 °C during
low-load operation).

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

- Calibrate thresholds against more labelled real data (turn the heuristic
  probabilities into calibrated ones).
- Second profile for controller-side exports (AE-200/EW-50) to add setpoints,
  unlocking the comfort and mode-conflict detectors on real data.
- Longer-horizon ingest so trend detectors (leak, COP degradation) have weeks
  of data.
- Per-detector threshold calibration UI and exportable PDF reports.

## References

Thermistor definitions, control parameters, protection setpoints, and operating
ranges used to ground the detectors. Load-bearing items were cross-checked
against at least two independent sources:

**Thermistor roles** (TH2 HIC pipe, TH3 outdoor liquid, TH4 compressor, TH6
suction, TH7 ambient, TH8 heat sink) — confirmed by two independent Mitsubishi
service manuals:
- PUMY-P200YKM Technical & Service Manual — thermistor feature chart.
- PUMY-P200YKM manual error-code pages naming "Hic Pipe Temperature Thermistor
  (TH2)" and the suction-pipe thermistor (TH6), independently confirming the
  TH2/TH6 mapping.

**Control parameters** (Mitsubishi multi-zone / MXZ technical documentation):
- **ETm = target evaporating temperature** (COOL mode). Raising it lifts coil
  temperature to prevent dew/condensation at some loss of capacity; lowering it
  raises performance. This matches the observed higher ETm eliminating the
  evaporator-icing risk between the two logs.
- **Pdm = target discharge pressure** (HEAT mode).
- **SC = subcooling**; **63HS/63LS = high/low pressure sensors**. Reported
  pressures are in **psi (gauge)** — confirmed both by the MN Converter tool's
  unit options and by magnitude (values ~180–435 are psi, not kgf/cm²).

**Protection / envelope:**
- R410A high-pressure switch cutout 4.15 MPa (601 psi) — R410A max operating
  pressure per PUMY-P NKMU documentation.
- Discharge-temperature compressor protection (~110 °C limiting, ~125 °C stop)
  for Mitsubishi R410A systems.
- Cooling envelope −5…46 °C, heating −25…21 °C (PUMY-P NKMU operating range).

**Diagnostic principles:**
- TXV/LEV systems are charged by **subcooling**; the valve holds evaporator
  superheat roughly constant, so superheat is not an independent charge
  indicator. VRF inverter compressors modulate frequency to meet the target
  evaporating temperature — so a compressor pinned at minimum speed while unable
  to reach its Te target indicates oversizing/low load.

Numeric thresholds live in each detector's `params` and can be recalibrated per
model without code changes.

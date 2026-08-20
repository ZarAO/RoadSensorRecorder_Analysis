# Stage C — Recording Metadata in the Analyzer (CSV contract v2.1/v3)

**Date:** 2026-08-20
**Status:** Approved scope (user-approved 4-stage decomposition, 2026-08-19); design
grounded in the committed recorder contract (`RoadSensorRecorder/README.md`,
`CHANGELOG.md`) and Stage A/B specs.

## Problem

The recorder now writes a rich comment layer the analyzer silently discards:

- v2 preamble: `# schema=2`, `# units:`, `# anchor:`, `# device:`,
  `# nominal_rate_hz=`, `# app_version=`, `# battery_start_pct=`
- v2.1 inline incidents: `# event: t=<anchored epoch ms>, type=<token>[, k=v...]`
- v2.1 clean-stop footer: `# end: duration_ms=, rows_accel=, rows_gyro=, rows_gps=,
  events=, battery_end_pct=, reason=<user|low_storage|destroy>`
- v3 vehicle block: `# vehicle_<key>=<value>` × 11 keys
  (`vehicle_tire_pressure_bar` optional)

`pandas.read_csv(comment='#')` keeps the data pipeline correct, but reports cannot
answer: was the recording clean or truncated? did sensors stall mid-drive? what
vehicle produced this data? Stage C surfaces all of it in the analysis outputs.

## Scope

**In:** parse the comment layer; add report sections; add a machine-readable
`recording_meta.json` artifact; close the docs 04/08 drift (they still describe
the bare-v2 preamble).

**Out (explicitly):** changing any metric computation. Eq.4/5/6 stays
`VehicleType.GENERIC` — the guidebook calibrates LEV/DSD/GENERIC test vehicles,
and the recorded `vehicle_type` tokens (sedan/suv/…) have no calibrated
coefficient sets, so mapping them would fabricate a calibration. Recorded vehicle
params are *context for cross-run comparison*, not model inputs. Also out:
event-aware segment filtering/flagging of segments overlapping incident windows
(future work, needs its own design), web-admin changes (Stage D).

## Design

### 1. New module `io/metadata.py`

Single public entry point plus dataclasses:

```python
@dataclass
class RecordingEvent:
    t_ms: int                 # anchored epoch ms from `t=`
    type: str                 # token, unknown tokens preserved as-is
    attrs: dict[str, str]     # remaining k=v pairs, values kept as strings

@dataclass
class RecordingMetadata:
    schema: int | None            # from `# schema=N`
    preamble: dict[str, str]      # units/anchor/device/nominal_rate_hz/app_version/
                                  # battery_start_pct — raw strings, keyed w/o '#'
    vehicle: dict[str, str]       # full keys as written: 'vehicle_type', … ; empty
                                  # dict = no block (no active profile / pre-v3)
    events: list[RecordingEvent]  # sorted by t_ms (file order is NOT monotonic)
    footer: dict[str, str] | None # from the LAST `# end:` line
    footer_count: int             # >1 → duplicate footers tolerated + warning
    warnings: list[str]           # every tolerated irregularity, human-readable

    @property
    def clean_stop(self) -> bool: return self.footer is not None

def parse_recording_metadata(filepath: str) -> RecordingMetadata
```

Parsing rules (each traced to the contract):

- One streaming pass over the file (UTF-8, `errors='replace'`), collecting only
  lines starting with `#`. Events and the footer live mid-file/at EOF, so the
  whole file is scanned — line-by-line, no full read into memory (the shipped
  recording is 11 MB; recordings can be much larger).
- `# key=value` → split on the FIRST `=`; value is everything to end of line,
  stripped of the trailing newline only. No other unescaping: the recorder
  replaced `\r` and `\n` with one space each, so `\r\n` in free text arrives as
  TWO spaces — the parser must not normalise or collapse whitespace inside values.
- `# section: payload` (`units`, `anchor`, `device`) → stored raw under the
  section name.
- `# vehicle_<key>=<value>` → into `vehicle` under the full key. Known enum keys
  are validated against the contract token tables; an unknown token produces a
  warning, never an error, and the raw value is kept.
- `# event: ...` → k=v pairs split on `, ` (event attrs are machine tokens and
  numbers per contract — no free text). Missing/unparsable `t=` → warning, event
  kept with `t_ms=-1`. Result list sorted by `t_ms` (contract: sensor batching
  makes file order non-monotonic; "sort by t, don't trust line order").
- `# end: ...` → same k=v parsing. A duplicate footer is tolerated: the last one
  wins, `footer_count` records how many, a warning is added.
- Any other `#` line that matches no rule → warning with the line number, skipped.
- A file with no comments at all (pre-v2.1 recordings, incl. the e2e sample) →
  empty metadata, `clean_stop=False`, zero warnings: absence is not an anomaly.

Interpretation helpers stay in the module so report code has no magic values:
`battery_start_pct`/`battery_end_pct` of `-1` means "unavailable"; `rows_*` and
`events=` in the footer are queue-time UPPER bounds, not exact counts; the
UI-aligned "incident" count = events excluding `accuracy_changed`.

### 2. Pipeline & report integration (`cli.py`)

Step 1 of `analyze()` additionally calls `parse_recording_metadata(input_path)`
and prints a one-line summary (schema, vehicle present?, events, clean/truncated).
Failure to parse metadata must never fail the analysis: a broad exception guard
degrades to empty metadata + a warning in the report (data pipeline correctness
does not depend on the comment layer).

`report.md` gains three sections after "Summary":

- **Recording Metadata** — schema version, device, app_version, nominal rate,
  battery start → end (`-1` rendered as "недоступно"), footer verdict:
  `clean stop (reason=user|low_storage|destroy)` vs `TRUNCATED recording —
  footer absent: file valid up to its last row but incomplete` (contract wording).
  Footer `duration_ms`, and rows_accel/gyro/gps vs the actually parsed row
  counts, labelled as queue-time upper bounds. For pre-v2.1 files the section
  says so in one line.
- **Vehicle Profile** — the recorded `vehicle_*` params as a table (raw values),
  or "немає блоку профілю (запис до v3 або без активного профілю)". A fixed note:
  Eq.4/5/6 computations use GENERIC coefficients regardless; these params exist
  so runs can be compared like-for-like (tire pressure, load, mount affect Grms
  per the ADB guidebook).
- **Recording Events** — counts by type (table), incident count excluding
  `accuracy_changed` (aligned with the app's "Incidents" counter), footer
  `events=` cross-check (upper bound), then the event list (t rendered as
  seconds from the first data row, type, attrs) capped at 50 rows with an
  explicit "…N more" line. Zero events → one line.

Parser warnings, if any, are appended under Recording Metadata.

### 3. New artifact `recording_meta.json`

Written next to `road_segments.csv`: JSON dump of `RecordingMetadata`
(schema, preamble, vehicle, events, footer, footer_count, clean_stop, warnings)
plus `source_file`. Missing values are `null`, never `NaN` (research-python rule).
This is the structured feed the Stage D web admin will ingest.

### 4. Docs drift closure

- `docs/04_experimental_design_and_reproducibility.md` §CSV Structure and
  `docs/08_user_guide_and_cli_reference.md` format section: extend the preamble
  description to v2.1/v3 (event lines, footer, vehicle block) with a pointer to
  the recorder README as the canonical contract; mention the new report sections
  and `recording_meta.json`.
- `docs/00_index.md` artifact list updated if it enumerates outputs.

## Testing

New `analyzer/tests/test_metadata.py` (pure parser, no pipeline):

1. Full v3 file → all preamble keys, 11 vehicle keys, events, footer parsed.
2. No comments at all → empty metadata, `clean_stop=False`, no warnings.
3. Vehicle block without `vehicle_tire_pressure_bar` (the only optional key).
4. Free-text value containing `=` → split on first `=` only.
5. Free-text value with double space (CRLF replacement) → preserved verbatim.
6. Unknown vehicle enum token → kept + warning.
7. Events out of t-order in the file → returned sorted by `t_ms`.
8. Unknown event type → preserved as-is.
9. Duplicate `# end:` → last wins, `footer_count=2`, warning.
10. Footer absent → `clean_stop=False`.
11. `battery_end_pct=-1` → exposed; report helper renders "unavailable".
12. Garbage `#` line → warning, parse continues.

`test_cli.py` extension: `analyze()` on a synthetic v3 drive (conftest
`write_drive_csv` + v3 comment layer) asserts the three report sections and
`recording_meta.json` exist and carry the expected values; `analyze()` on the
bare-header drive still passes untouched (backward-compat pin).

Regression gates: full suite (163 existing tests stay green) and the e2e run on
`storage/data/sensor_data_20250729_163334.csv` still yields 152 segments.

## Non-goals / future work

- Mapping incidents onto segments (mark segments overlapping `sensor_stall`/
  `gps_lost` windows as reduced-confidence) — real value, separate design.
- Using recorded vehicle params in IRI equations — blocked on calibration data.
- Web-admin ingestion of `recording_meta.json` — Stage D.

# Stage C — Recording Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse the CSV v2.1/v3 comment layer (preamble, `# vehicle_*`, `# event:`, `# end:`) and surface it in `report.md` and a new `recording_meta.json`, without touching any metric computation.

**Architecture:** A new self-contained parser module `io/metadata.py` does one streaming pass over the file's `#` lines and returns a `RecordingMetadata` dataclass; `cli.analyze()` calls it in step 1, writes three new report sections and the JSON artifact. Metadata parsing can never fail the analysis.

**Tech Stack:** Python 3.14, dataclasses, pytest; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-20-stage-c-recording-metadata-design.md`

## Global Constraints

- Branch: `v1-1-stage`; no `Co-Authored-By` trailers; no hidden/invisible characters in any file.
- Code/comments/commits in English; report strings may mix Ukrainian like the existing report.
- Metric computations unchanged — Eq.4/5/6 stays `VehicleType.GENERIC`.
- JSON serializes missing values as `null`, never `NaN`.
- Values keep raw whitespace (CRLF was replaced by TWO spaces at write time — do not collapse).
- Regression gates: full pytest suite green; e2e on `storage/data/sensor_data_20250729_163334.csv` still yields 152 segments (19 low-speed).

---

### Task 1: Parser module `io/metadata.py`

**Files:**
- Create: `analyzer/src/road_quality_analyzer/io/metadata.py`
- Modify: `analyzer/src/road_quality_analyzer/io/__init__.py`
- Test: `analyzer/tests/test_metadata.py`

**Interfaces:**
- Produces: `parse_recording_metadata(filepath: str) -> RecordingMetadata`;
  `RecordingMetadata(schema, preamble, vehicle, events, footer, footer_count, warnings)` with `.clean_stop` property and `.incident_count` (events excluding `accuracy_changed`); `RecordingEvent(t_ms: int, type: str, attrs: dict)`; module constants `VEHICLE_ENUM_TOKENS`, `BATTERY_UNAVAILABLE = -1`.
- Exported from `road_quality_analyzer.io`.

- [ ] **Step 1: Write failing tests** — `analyzer/tests/test_metadata.py` with a builder for synthetic comment layers:

```python
"""Unit tests for the CSV v2.1/v3 comment-layer parser (contract: recorder README)."""
import pytest
from road_quality_analyzer.io import parse_recording_metadata

V3_PREAMBLE = (
    "# schema=2\n"
    "# units: accel=m/s^2 (includes gravity), gyro=rad/s, latlon=deg WGS84, time=ms epoch anchored monotonic\n"
    "# anchor: elapsedRealtimeNanos=1000000000, currentTimeMillis=1753796576000\n"
    "# device: SYNTHETIC TEST, android=14\n"
    "# nominal_rate_hz=100\n"
    "# app_version=1.1\n"
    "# battery_start_pct=87\n"
)
VEHICLE_BLOCK = (
    "# vehicle_type=sedan\n"
    "# vehicle_make_model=Skoda Octavia\n"
    "# vehicle_year=2019\n"
    "# vehicle_suspension_type=independent\n"
    "# vehicle_suspension_condition=good\n"
    "# vehicle_tire_size=205/55 R16\n"
    "# vehicle_tire_type=summer\n"
    "# vehicle_tire_pressure_bar=2.3\n"
    "# vehicle_load=driver_only\n"
    "# vehicle_mount=windshield\n"
    "# vehicle_mount_rigid=true\n"
)
HEADER = "Time,Type,X,Y,Z,Latitude,Longitude\n"
ROWS = "1753796576000,Accelerometer,0.0,0.0,9.81,,\n1753796576010,Accelerometer,0.0,0.0,9.81,,\n"
FOOTER = ("# end: duration_ms=20000, rows_accel=2000, rows_gyro=0, rows_gps=20, "
          "events=3, battery_end_pct=85, reason=user\n")

def write(tmp_path, text, name="rec.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)

def test_full_v3_file_parses_everything(tmp_path):
    text = (V3_PREAMBLE + VEHICLE_BLOCK + HEADER + ROWS
            + "# event: t=1753796576500, type=gps_lost, age_s=12\n" + ROWS + FOOTER)
    meta = parse_recording_metadata(write(tmp_path, text))
    assert meta.schema == 2
    assert meta.preamble["device"] == "SYNTHETIC TEST, android=14"
    assert meta.preamble["battery_start_pct"] == "87"
    assert len(meta.vehicle) == 11
    assert meta.vehicle["vehicle_type"] == "sedan"
    assert [e.type for e in meta.events] == ["gps_lost"]
    assert meta.events[0].t_ms == 1753796576500
    assert meta.events[0].attrs == {"age_s": "12"}
    assert meta.footer["reason"] == "user"
    assert meta.clean_stop and meta.footer_count == 1 and meta.warnings == []

def test_bare_file_without_comments(tmp_path):
    meta = parse_recording_metadata(write(tmp_path, HEADER + ROWS))
    assert meta.schema is None and meta.preamble == {} and meta.vehicle == {}
    assert meta.events == [] and meta.footer is None
    assert not meta.clean_stop and meta.warnings == []

def test_optional_tire_pressure_absent(tmp_path):
    block = VEHICLE_BLOCK.replace("# vehicle_tire_pressure_bar=2.3\n", "")
    meta = parse_recording_metadata(write(tmp_path, V3_PREAMBLE + block + HEADER + ROWS))
    assert len(meta.vehicle) == 10 and "vehicle_tire_pressure_bar" not in meta.vehicle

def test_value_split_on_first_equals_only(tmp_path):
    text = V3_PREAMBLE + "# vehicle_make_model=Tesla Model=S\n" + HEADER + ROWS
    meta = parse_recording_metadata(write(tmp_path, text))
    assert meta.vehicle["vehicle_make_model"] == "Tesla Model=S"

def test_crlf_double_space_preserved(tmp_path):
    text = V3_PREAMBLE + "# vehicle_make_model=Skoda  Octavia\n" + HEADER + ROWS
    meta = parse_recording_metadata(write(tmp_path, text))
    assert meta.vehicle["vehicle_make_model"] == "Skoda  Octavia"

def test_unknown_enum_token_warns_but_keeps_value(tmp_path):
    text = V3_PREAMBLE + "# vehicle_type=spaceship\n" + HEADER + ROWS
    meta = parse_recording_metadata(write(tmp_path, text))
    assert meta.vehicle["vehicle_type"] == "spaceship"
    assert any("spaceship" in w for w in meta.warnings)

def test_events_sorted_by_t(tmp_path):
    text = (V3_PREAMBLE + HEADER + ROWS
            + "# event: t=1753796576900, type=sensor_recovered, sensor=accel, gap_ms=2500\n"
            + "# event: t=1753796576400, type=sensor_stall, sensor=accel, gap_ms=2500\n" + ROWS)
    meta = parse_recording_metadata(write(tmp_path, text))
    assert [e.type for e in meta.events] == ["sensor_stall", "sensor_recovered"]

def test_unknown_event_type_kept(tmp_path):
    text = V3_PREAMBLE + HEADER + "# event: t=1753796576400, type=solar_flare\n" + ROWS
    meta = parse_recording_metadata(write(tmp_path, text))
    assert meta.events[0].type == "solar_flare"

def test_duplicate_footer_last_wins_with_warning(tmp_path):
    second = FOOTER.replace("reason=user", "reason=destroy")
    meta = parse_recording_metadata(write(tmp_path, V3_PREAMBLE + HEADER + ROWS + FOOTER + second))
    assert meta.footer["reason"] == "destroy" and meta.footer_count == 2
    assert any("end" in w.lower() for w in meta.warnings)

def test_battery_unavailable_minus_one(tmp_path):
    text = (V3_PREAMBLE.replace("battery_start_pct=87", "battery_start_pct=-1")
            + HEADER + ROWS + FOOTER.replace("battery_end_pct=85", "battery_end_pct=-1"))
    meta = parse_recording_metadata(write(tmp_path, text))
    assert meta.preamble["battery_start_pct"] == "-1"
    assert meta.footer["battery_end_pct"] == "-1"

def test_incident_count_excludes_accuracy_changed(tmp_path):
    text = (V3_PREAMBLE + HEADER
            + "# event: t=1753796576100, type=accuracy_changed, sensor=accel, accuracy=3\n"
            + "# event: t=1753796576400, type=gps_lost, age_s=11\n" + ROWS)
    meta = parse_recording_metadata(write(tmp_path, text))
    assert len(meta.events) == 2 and meta.incident_count == 1

def test_garbage_comment_line_warns_and_continues(tmp_path):
    text = V3_PREAMBLE + "# what is this line\n" + HEADER + ROWS + FOOTER
    meta = parse_recording_metadata(write(tmp_path, text))
    assert meta.clean_stop and any("line" in w.lower() for w in meta.warnings)
```

- [ ] **Step 2: Run to verify failure** — `.venv/Scripts/python.exe -m pytest analyzer/tests/test_metadata.py -q` → ImportError (`parse_recording_metadata` not defined).

- [ ] **Step 3: Implement `io/metadata.py`:**

```python
"""
Parser for the CSV comment layer of the recorder contract (v2 preamble,
v2.1 `# event:` / `# end:`, v3 `# vehicle_*`).

Canonical contract: RoadSensorRecorder/README.md. Parsing is tolerant by
design — every irregularity becomes a warning, never an exception: the data
pipeline must not depend on the comment layer.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

BATTERY_UNAVAILABLE = -1

# Machine-token tables shared with the recorder (contract v3) — do not rename
VEHICLE_ENUM_TOKENS = {
    'vehicle_type': {'sedan', 'hatchback', 'crossover', 'suv', 'van', 'truck'},
    'vehicle_suspension_type': {'independent', 'torsion_beam', 'leaf_spring', 'air'},
    'vehicle_suspension_condition': {'new', 'good', 'worn'},
    'vehicle_tire_type': {'summer', 'winter', 'all_season'},
    'vehicle_load': {'driver_only', 'two_people', 'half_load', 'full_load'},
    'vehicle_mount': {'windshield', 'dashboard', 'console', 'other'},
    'vehicle_mount_rigid': {'true', 'false'},
}

# Preamble lines of the form '# <section>: <payload>' — stored raw
_SECTION_KEYS = ('units', 'anchor', 'device')

# The UI "Incidents" counter excludes accuracy_changed (fires on every listener
# registration); keep the report aligned with what the operator saw
_NON_INCIDENT_EVENT_TYPES = {'accuracy_changed'}


@dataclass
class RecordingEvent:
    t_ms: int              # anchored epoch ms; -1 when the t= field was unparsable
    type: str              # token; unknown tokens are preserved as-is
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass
class RecordingMetadata:
    schema: Optional[int] = None
    preamble: Dict[str, str] = field(default_factory=dict)
    vehicle: Dict[str, str] = field(default_factory=dict)
    events: List[RecordingEvent] = field(default_factory=list)
    footer: Optional[Dict[str, str]] = None
    footer_count: int = 0
    warnings: List[str] = field(default_factory=list)

    @property
    def clean_stop(self) -> bool:
        return self.footer is not None

    @property
    def incident_count(self) -> int:
        return sum(1 for e in self.events if e.type not in _NON_INCIDENT_EVENT_TYPES)


def _parse_kv_list(payload: str) -> Dict[str, str]:
    """Parse 'k=v, k=v' payloads of event/footer lines (machine tokens only)."""
    attrs = {}
    for part in payload.split(', '):
        if '=' in part:
            key, value = part.split('=', 1)
            attrs[key.strip()] = value
    return attrs


def parse_recording_metadata(filepath: str) -> RecordingMetadata:
    """
    One streaming pass over the file, collecting every '#' line.

    Events and the footer are written into the data stream, so the whole file
    is scanned line by line (recordings run to hundreds of MB — never read the
    file into memory at once).
    """
    meta = RecordingMetadata()

    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        for line_no, raw in enumerate(f, start=1):
            if not raw.startswith('#'):
                continue
            line = raw.rstrip('\r\n')
            body = line[1:].lstrip()

            if body.startswith('event:'):
                attrs = _parse_kv_list(body[len('event:'):].lstrip())
                try:
                    t_ms = int(attrs.pop('t'))
                except (KeyError, ValueError):
                    t_ms = -1
                    meta.warnings.append(
                        f"line {line_no}: event without a parsable t= field")
                event_type = attrs.pop('type', '')
                if not event_type:
                    meta.warnings.append(
                        f"line {line_no}: event without a type= field")
                meta.events.append(RecordingEvent(t_ms, event_type, attrs))
            elif body.startswith('end:'):
                meta.footer = _parse_kv_list(body[len('end:'):].lstrip())
                meta.footer_count += 1
                if meta.footer_count > 1:
                    meta.warnings.append(
                        f"line {line_no}: duplicate '# end:' footer — keeping the last one")
            elif any(body.startswith(k + ':') for k in _SECTION_KEYS):
                key, payload = body.split(':', 1)
                meta.preamble[key] = payload.strip()
            elif '=' in body:
                key, value = body.split('=', 1)
                key = key.strip()
                if key == 'schema':
                    try:
                        meta.schema = int(value)
                    except ValueError:
                        meta.warnings.append(f"line {line_no}: unparsable schema={value!r}")
                elif key.startswith('vehicle_'):
                    meta.vehicle[key] = value
                    allowed = VEHICLE_ENUM_TOKENS.get(key)
                    if allowed is not None and value not in allowed:
                        meta.warnings.append(
                            f"line {line_no}: {key}={value!r} is not a known contract token")
                else:
                    meta.preamble[key] = value
            else:
                meta.warnings.append(f"line {line_no}: unrecognized comment line {line!r}")

    # Contract: sensor batching makes file order non-monotonic — sort by t,
    # never trust line order
    meta.events.sort(key=lambda e: e.t_ms)
    return meta
```

- [ ] **Step 4: Export** — in `io/__init__.py`:

```python
from .ingestion import load_sensor_csv, SensorData
from .metadata import (
    parse_recording_metadata, RecordingMetadata, RecordingEvent, BATTERY_UNAVAILABLE
)

__all__ = ["load_sensor_csv", "SensorData", "parse_recording_metadata",
           "RecordingMetadata", "RecordingEvent", "BATTERY_UNAVAILABLE"]
```

- [ ] **Step 5: Run tests** — `.venv/Scripts/python.exe -m pytest analyzer/tests/test_metadata.py -q` → all pass.

- [ ] **Step 6: Commit** — `git add analyzer/src/road_quality_analyzer/io/metadata.py analyzer/src/road_quality_analyzer/io/__init__.py analyzer/tests/test_metadata.py && git commit -m "feat: parse the CSV v2.1/v3 comment layer into RecordingMetadata"`

### Task 2: Report sections + `recording_meta.json` in `analyze()`

**Files:**
- Modify: `analyzer/src/road_quality_analyzer/cli.py` (step [1/9] block; report writing after "Summary")
- Test: `analyzer/tests/test_cli.py` (new tests at the end)

**Interfaces:**
- Consumes: `parse_recording_metadata`, `RecordingMetadata`, `BATTERY_UNAVAILABLE` from `road_quality_analyzer.io`.
- Produces: `report.md` sections `## Recording Metadata`, `## Vehicle Profile`, `## Recording Events`; artifact `recording_meta.json` (keys: `source_file, schema, preamble, vehicle, events, footer, footer_count, clean_stop, warnings`).

- [ ] **Step 1: Write failing tests** (append to `test_cli.py`; reuse `run_analyze` + conftest builders):

```python
V3_COMMENT_TAIL_EVENTS = (
    "# event: t=1753796581000, type=gps_lost, age_s=12\n"
    "# event: t=1753796576100, type=accuracy_changed, sensor=accel, accuracy=3\n"
)
V3_FOOTER = ("# end: duration_ms=40000, rows_accel=4000, rows_gyro=0, rows_gps=40, "
             "events=2, battery_end_pct=-1, reason=user\n")
V3_VEHICLE_BLOCK = (
    "# vehicle_type=sedan\n# vehicle_make_model=Skoda Octavia\n# vehicle_year=2019\n"
    "# vehicle_suspension_type=independent\n# vehicle_suspension_condition=good\n"
    "# vehicle_tire_size=205/55 R16\n# vehicle_tire_type=summer\n"
    "# vehicle_tire_pressure_bar=2.3\n# vehicle_load=driver_only\n"
    "# vehicle_mount=windshield\n# vehicle_mount_rigid=true\n"
)

def _append_v3_layer(csv_path):
    """Inject the vehicle block after the preamble and events+footer at EOF."""
    text = Path(csv_path).read_text(encoding='utf-8')
    text = text.replace("Time,Type,", V3_VEHICLE_BLOCK + "Time,Type,", 1)
    text += V3_COMMENT_TAIL_EVENTS + V3_FOOTER
    Path(csv_path).write_text(text, encoding='utf-8')

def test_analyze_surfaces_v3_metadata(tmp_path, drive_csv):
    csv_path = drive_csv('v3.csv', duration_s=40.0, a_vert=_baseline_excitation)
    _append_v3_layer(csv_path)
    out = tmp_path / 'out'
    run_analyze(csv_path, out)

    report = (out / 'report.md').read_text(encoding='utf-8')
    assert '## Recording Metadata' in report
    assert 'reason=user' in report            # clean stop verdict
    assert 'недоступно' in report             # battery_end_pct=-1 rendered as unavailable
    assert '## Vehicle Profile' in report and 'Skoda Octavia' in report
    assert '## Recording Events' in report and 'gps_lost' in report
    assert 'accuracy_changed' in report       # counted but flagged as non-incident

    meta = json.loads((out / 'recording_meta.json').read_text(encoding='utf-8'))
    assert meta['clean_stop'] is True
    assert meta['vehicle']['vehicle_type'] == 'sedan'
    assert len(meta['events']) == 2
    assert meta['footer']['reason'] == 'user'

def test_analyze_pre_v21_file_reports_absence(tmp_path, drive_csv):
    csv_path = drive_csv('v2.csv', duration_s=40.0, a_vert=_baseline_excitation,
                         preamble=False)
    out = tmp_path / 'out'
    run_analyze(csv_path, out)
    report = (out / 'report.md').read_text(encoding='utf-8')
    assert '## Recording Metadata' in report
    assert 'обірваний або записаний до контракту v2.1' in report
    meta = json.loads((out / 'recording_meta.json').read_text(encoding='utf-8'))
    assert meta['clean_stop'] is False and meta['vehicle'] == {}
```

- [ ] **Step 2: Run to verify failure** — the two new tests fail (no sections, no JSON).

- [ ] **Step 3: Implement in `cli.py`.** In step [1/9], after `load_sensor_csv`:

```python
from road_quality_analyzer.io import parse_recording_metadata, RecordingMetadata

try:
    recording_meta = parse_recording_metadata(input_path)
except Exception as exc:  # the comment layer must never fail the analysis
    recording_meta = RecordingMetadata()
    recording_meta.warnings.append(f"metadata parsing failed: {exc}")
verdict = ('clean stop' if recording_meta.clean_stop
           else 'truncated or pre-v2.1')
print(f"  Metadata: schema={recording_meta.schema}, "
      f"vehicle={'yes' if recording_meta.vehicle else 'no'}, "
      f"events={len(recording_meta.events)}, {verdict}")
```

After writing `road_segments.csv`, write the JSON artifact:

```python
import dataclasses, json
meta_json = output_path / "recording_meta.json"
meta_payload = dataclasses.asdict(recording_meta)
meta_payload.update(source_file=str(input_path),
                    clean_stop=recording_meta.clean_stop)
with open(meta_json, 'w', encoding='utf-8') as jf:
    json.dump(meta_payload, jf, ensure_ascii=False, indent=2)
print(f"  ✓ {meta_json}")
```

In `report.md` directly after the "## Summary" block, write the three sections
(render helper `_pct(value)` returns `"недоступно"` for `-1`/missing, else `f"{value}%"`):

```python
f.write("## Recording Metadata\n\n")
if recording_meta.schema is None and not recording_meta.preamble:
    f.write("- Преамбули немає: файл обірваний або записаний до контракту v2.1\n")
else:
    f.write(f"- Schema: {recording_meta.schema}\n")
    for key in ('device', 'app_version', 'nominal_rate_hz', 'anchor', 'units'):
        if key in recording_meta.preamble:
            f.write(f"- {key}: {recording_meta.preamble[key]}\n")
    f.write(f"- Battery: {_pct(recording_meta.preamble.get('battery_start_pct'))}"
            f" → {_pct((recording_meta.footer or {}).get('battery_end_pct'))}\n")
if recording_meta.clean_stop:
    footer = recording_meta.footer
    f.write(f"- Зупинка: чиста (reason={footer.get('reason', '?')}), "
            f"duration_ms={footer.get('duration_ms', '?')}\n")
    f.write(f"- Футер rows (queue-time, верхня межа): "
            f"accel={footer.get('rows_accel')}, gyro={footer.get('rows_gyro')}, "
            f"gps={footer.get('rows_gps')}; фактично розпарсено: "
            f"accel={len(sensor_data.accel_time)}, "
            f"gyro={0 if sensor_data.gyro_time is None else len(sensor_data.gyro_time)}, "
            f"gps={0 if sensor_data.gps_time is None else len(sensor_data.gps_time)}\n")
else:
    f.write("- Зупинка: футера `# end:` немає — запис обірваний або записаний до "
            "контракту v2.1; файл валідний до останнього рядка, але неповний\n")
for w in recording_meta.warnings:
    f.write(f"- ⚠ {w}\n")
f.write("\n## Vehicle Profile\n\n")
if recording_meta.vehicle:
    f.write("| Параметр | Значення |\n|---|---|\n")
    for key, value in recording_meta.vehicle.items():
        f.write(f"| `{key}` | {value} |\n")
    f.write("\nПараметри записані як контекст для порівняння заїздів. Обчислення "
            "IRI_multi (Eq.4/5/6) використовують GENERIC-коефіцієнти незалежно від "
            "профілю: довідник калібрує лише тестові класи LEV/DSD/GENERIC.\n")
else:
    f.write("Немає блоку профілю (запис до v3 або без активного профілю).\n")
f.write("\n## Recording Events\n\n")
if recording_meta.events:
    counts = Counter(e.type for e in recording_meta.events)
    f.write("| Тип | Кількість |\n|---|---|\n")
    for etype, count in sorted(counts.items()):
        f.write(f"| `{etype}` | {count} |\n")
    f.write(f"\n- Інцидентів (без `accuracy_changed`, як лічильник у застосунку): "
            f"{recording_meta.incident_count}\n")
    if recording_meta.footer and 'events' in recording_meta.footer:
        f.write(f"- Футер events={recording_meta.footer['events']} "
                f"(queue-time, верхня межа; розпарсено {len(recording_meta.events)})\n")
    if recording_meta.events:
        f.write("\n| t, с від старту даних | Тип | Атрибути |\n|---|---|---|\n")
        shown = recording_meta.events[:50]
        for e in shown:
            t_rel = '?' if e.t_ms < 0 or t0_data_ms is None \
                else f"{(e.t_ms - t0_data_ms) / 1000.0:.1f}"
            attrs = ', '.join(f"{k}={v}" for k, v in e.attrs.items())
            f.write(f"| {t_rel} | `{e.type}` | {attrs} |\n")
        if len(recording_meta.events) > 50:
            f.write(f"\n…і ще {len(recording_meta.events) - 50} подій "
                    "(повний список у recording_meta.json)\n")
else:
    f.write("Рядків `# event:` немає.\n")
f.write("\n")
```

`t0_data_ms` is captured in step 1: for a numeric ms `Time` column it is
`int(df_time_min)` — expose it from the loading step as
`t0_data_ms = int(sensor_data_t0)` when `sensor_data.time_unit == 'ms'`, else
`None` (events use anchored epoch ms, comparable only to the ms time base).
Note: `load_sensor_csv` currently discards the absolute t0 — return it via a new
optional field `SensorData.t0_ms: Optional[int] = None` set only in the
numeric-ms branch (one-line change in `ingestion.py`, no behavior change).

- [ ] **Step 4: Update the artifacts list** in the report ("## Generated Artifacts") with `recording_meta.json - метадані запису: преамбула, профіль авто, події, футер (JSON)`.

- [ ] **Step 5: Run tests** — `.venv/Scripts/python.exe -m pytest analyzer/tests/test_cli.py -q` → all pass (old + 2 new).

- [ ] **Step 6: Commit** — `git add analyzer/src/road_quality_analyzer/cli.py analyzer/src/road_quality_analyzer/io/ingestion.py analyzer/tests/test_cli.py && git commit -m "feat: surface recording metadata, vehicle profile and events in the report and recording_meta.json"`

### Task 3: Docs drift closure + full regression

**Files:**
- Modify: `docs/04_experimental_design_and_reproducibility.md` (§CSV Structure), `docs/08_user_guide_and_cli_reference.md` (format section + artifacts list), `docs/00_index.md` (if it enumerates artifacts)

**Interfaces:** none (documentation).

- [ ] **Step 1:** In docs/04 §CSV Structure: after the preamble example add a short subsection "Коментарний шар v2.1/v3" — `# event:` lines (8 types), `# end:` footer (presence = clean stop), `# vehicle_*` block (11 keys, `vehicle_tire_pressure_bar` optional), with the canonical-contract pointer to `RoadSensorRecorder/README.md`; note the analyzer parses this layer into `report.md` and `recording_meta.json` since Stage C.
- [ ] **Step 2:** In docs/08: extend the format block with one example `# event:` and `# end:` line and the vehicle block; add `recording_meta.json` to the outputs list.
- [ ] **Step 3:** Check `docs/00_index.md` for an artifacts enumeration; update if present.
- [ ] **Step 4: Full regression** — `.venv/Scripts/python.exe -m pytest analyzer/tests -q` (expect 163 + ~14 new, all green).
- [ ] **Step 5: E2E regression** — `.venv/Scripts/python.exe -m road_quality_analyzer analyze --input storage/data/sensor_data_20250729_163334.csv --out <scratch>` → 152 segments, 19 low-speed; `report.md` shows the pre-v2.1 absence lines; `recording_meta.json` has `clean_stop=false`, empty vehicle.
- [ ] **Step 6: Hidden-character scan** over every changed/created file (git rule: no invisible Unicode).
- [ ] **Step 7: Commit** — `git add docs/04_experimental_design_and_reproducibility.md docs/08_user_guide_and_cli_reference.md docs/00_index.md && git commit -m "docs: describe the v2.1/v3 comment layer and the recording_meta.json artifact"`

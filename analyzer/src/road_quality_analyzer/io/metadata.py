"""
Parser for the CSV comment layer of the recorder contract (v2 preamble,
v2.1 `# event:` / `# end:` lines, v3 `# vehicle_*` block).

Canonical contract: RoadSensorRecorder/README.md. Parsing is tolerant by
design — every irregularity becomes a warning, never an exception: the data
pipeline must not depend on the comment layer.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# battery_start_pct / battery_end_pct value meaning "battery level unavailable"
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

# The UI "Incidents" counter excludes accuracy_changed (Android fires it on
# every listener registration); keep reports aligned with what the operator saw
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
        """Contract: footer presence = clean stop; absence = truncated recording."""
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
                # Value = everything after the FIRST '='; no unescaping. The
                # recorder replaced CR and LF with one space each, so free text
                # may hold double spaces — never normalise whitespace here.
                key, value = body.split('=', 1)
                key = key.strip()
                if key == 'schema':
                    try:
                        meta.schema = int(value)
                    except ValueError:
                        meta.warnings.append(
                            f"line {line_no}: unparsable schema={value!r}")
                elif key.startswith('vehicle_'):
                    meta.vehicle[key] = value
                    allowed = VEHICLE_ENUM_TOKENS.get(key)
                    if allowed is not None and value not in allowed:
                        meta.warnings.append(
                            f"line {line_no}: {key}={value!r} is not a known contract token")
                else:
                    meta.preamble[key] = value
            else:
                meta.warnings.append(
                    f"line {line_no}: unrecognized comment line {line!r}")

    # Contract: sensor batching makes event lines non-monotonic vs data rows —
    # sort by t, never trust file order
    meta.events.sort(key=lambda e: e.t_ms)
    return meta

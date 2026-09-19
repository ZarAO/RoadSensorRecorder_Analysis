#!/usr/bin/env python
"""
One-off retrofit tool: add contract v3.1 identity lines to a CSV recorded
under an earlier contract (v2.1/v3), for dissertation data provenance.

Recordings made before the recorder wrote its own identity carry no
`# device_id=` / `# vehicle_id=` lines, so the web-admin coefficient-set
resolution can only ever place them at the generic (vehicle_type) tier. This
tool retrofits the two identity lines by hand, from operator-supplied values,
so such a recording can instead be attributed to an exact phone-and-vehicle
identity (contract v3.1, tier 1) -- e.g. to reproduce a calibration result
that was in fact recorded with one known phone in one known vehicle.

Never mutates the source file: it always writes a new file at --out and
refuses to overwrite an existing one. A provenance comment line is appended
right after the vehicle block, marking the file as retrofitted (and letting a
second, accidental retrofit attempt over the same input refuse outright).
--retrofit-date pins that line's date (default: today) so the same command
line reproduces a byte-identical output on a later run, per the dissertation
project's reproducibility rule.

Contract v3.1 (pinned by analyzer/tests/test_metadata.py):
  - `# device_id=<token>` is inserted into the preamble immediately after the
    `# device: ...` line;
  - `# vehicle_id=<uuid>` is inserted as the FIRST line of the `# vehicle_*`
    block, immediately before the first `# vehicle_` line.
Both keys, and the provenance line's own `# retrofit=...` key, are read by the
parser's tolerant '#'-comment scanner (road_quality_analyzer.io.parse_
recording_metadata) without raising -- an unrecognized comment line only ever
produces a warning, never an exception. Everything else in the file
(including its own '\\n' vs '\\r\\n' line endings) is passed through
byte-identical.

Usage:
    python scripts/retrofit_v31.py --input src.csv --out dst.csv \\
        --device-id <token> --vehicle-id <uuid> [--retrofit-date 2026-09-19]
    python scripts/retrofit_v31.py --verify dst.csv
"""

import argparse
import datetime as dt
from pathlib import Path

DEVICE_LINE_PREFIX = '# device:'
DEVICE_ID_PREFIX = '# device_id='
VEHICLE_LINE_PREFIX = '# vehicle_'
VEHICLE_ID_PREFIX = '# vehicle_id='
PROVENANCE_PREFIX = '# retrofit='
TOOL_NAME = 'scripts/retrofit_v31.py'


def _detect_eol(raw: bytes) -> str:
    """The recorder writes one line-ending style per file; go with whichever
    this file actually uses instead of assuming."""
    return '\r\n' if b'\r\n' in raw else '\n'


def _read_lines(path: Path) -> tuple[list[str], str, bool]:
    """(lines without terminators, the file's own eol, had a trailing eol)."""
    raw = path.read_bytes()
    eol = _detect_eol(raw)
    text = raw.decode('utf-8')
    trailing = text.endswith(eol)
    body = text[:-len(eol)] if trailing else text
    return body.split(eol), eol, trailing


def _write_lines(path: Path, lines: list[str], eol: str, trailing: bool) -> None:
    text = eol.join(lines) + (eol if trailing else '')
    path.write_bytes(text.encode('utf-8'))


def _refuse_if_already_retrofitted(lines: list[str], input_path: Path) -> None:
    for line in lines:
        if line.startswith(DEVICE_ID_PREFIX) or line.startswith(VEHICLE_ID_PREFIX):
            raise SystemExit(
                f'{input_path}: already carries an identity line ({line!r}) '
                '-- refusing to retrofit twice')


def _insert_device_id(lines: list[str], device_id: str) -> list[str]:
    for i, line in enumerate(lines):
        if line.startswith(DEVICE_LINE_PREFIX):
            return lines[:i + 1] + [f'{DEVICE_ID_PREFIX}{device_id}'] + lines[i + 1:]
    raise SystemExit("no '# device:' preamble line found -- not a v2/v3 recording")


def _insert_vehicle_id_and_provenance(
        lines: list[str], vehicle_id: str, retrofit_date: dt.date) -> list[str]:
    start = next((i for i, line in enumerate(lines)
                 if line.startswith(VEHICLE_LINE_PREFIX)), None)
    if start is None:
        raise SystemExit("no '# vehicle_*' block found -- not a v3 recording")
    end = start
    while end < len(lines) and lines[end].startswith(VEHICLE_LINE_PREFIX):
        end += 1
    # A plain 'key=value' payload (single '=', no nested '='), same shape as
    # every other machine-readable comment line the parser already recognizes
    # -- it lands in preamble['retrofit'] instead of an unrecognized-line warning.
    provenance = f'{PROVENANCE_PREFIX}v3.1-identity {retrofit_date.isoformat()} {TOOL_NAME}'
    return (lines[:start] + [f'{VEHICLE_ID_PREFIX}{vehicle_id}'] + lines[start:end]
            + [provenance] + lines[end:])


def retrofit(input_path: Path, out_path: Path, device_id: str, vehicle_id: str,
            retrofit_date: dt.date | None = None) -> None:
    if out_path.exists():
        raise SystemExit(f'{out_path}: already exists -- refusing to overwrite')
    lines, eol, trailing = _read_lines(input_path)
    _refuse_if_already_retrofitted(lines, input_path)
    lines = _insert_device_id(lines, device_id)
    lines = _insert_vehicle_id_and_provenance(
        lines, vehicle_id, retrofit_date or dt.date.today())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_lines(out_path, lines, eol, trailing)


def verify(path: Path) -> None:
    """Self-check: parse the produced file with the real analyzer parser and
    print exactly what a consumer (the web-admin backend) would read off it."""
    from road_quality_analyzer.io import parse_recording_metadata

    meta = parse_recording_metadata(str(path))
    print(f'device_id: {meta.preamble.get("device_id")!r}')
    print(f'vehicle_id: {meta.vehicle.get("vehicle_id")!r}')
    print(f'vehicle_type: {meta.vehicle.get("vehicle_type")!r}')
    print(f'retrofit provenance: {meta.preamble.get("retrofit")!r}')
    print(f'warnings ({len(meta.warnings)}):')
    for warning in meta.warnings:
        print(f'  - {warning}')


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--input', type=Path, help='source CSV (v2.1/v3), never modified')
    parser.add_argument('--out', type=Path, help='retrofitted CSV to write (must not exist)')
    parser.add_argument('--device-id', help='contract v3.1 device_id token')
    parser.add_argument('--vehicle-id', help='contract v3.1 vehicle_id (uuid)')
    parser.add_argument('--retrofit-date', type=dt.date.fromisoformat, metavar='YYYY-MM-DD',
                        help='provenance line date (default: today); pin it to reproduce '
                             'a byte-identical output on a later run')
    parser.add_argument('--verify', type=Path, metavar='FILE.csv',
                        help='self-check mode: parse FILE and print its identity fields')
    args = parser.parse_args()

    if args.verify is not None:
        verify(args.verify)
        return

    missing = [name for name, value in (
        ('--input', args.input), ('--out', args.out),
        ('--device-id', args.device_id), ('--vehicle-id', args.vehicle_id),
    ) if value is None]
    if missing:
        parser.error(f'retrofit mode requires {", ".join(missing)} (or use --verify alone)')

    retrofit(args.input, args.out, args.device_id, args.vehicle_id, args.retrofit_date)
    print(f'{args.out}: retrofitted from {args.input}')


if __name__ == '__main__':
    main()

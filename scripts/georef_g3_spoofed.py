#!/usr/bin/env python
"""
One-off tool: re-georeference an ARRB Walking Profiler G3 survey whose tablet
GNSS was spoofed (electronic warfare), for dissertation data provenance.

The G3 measures distance with its own calibrated odometer and the profile/IRI
with its accelerometer; GNSS from the tablet is only a location tag. When the
tablet was spoofed, every coordinate in the survey is wrong while distance,
profile and IRI are fine. This tool rebuilds the location tags from a route
line supplied by the operator (GeoJSON LineString, drawn from trustworthy
fixes): each GNSS row's odometer distance is mapped proportionally onto the
route length, in the route's direction or reversed (--reverse).

Never mutates the source survey: it writes NEW copies of the three files that
carry coordinates into --out-dir and refuses to overwrite existing files:
  - `<survey> GNSS.csv`   lat/lon from the route, bearing from the route
                          tangent, altitude blanked (unknown), speed rewritten
                          with a decimal POINT (the device writes a decimal
                          comma inside a comma-separated file);
  - `<survey> Information.txt`  only the Start/End Location lines change;
  - `<survey>.ppf`        start/end lon, lat (float32) patched, altitude 0.0.
Outputs are UTF-8 without BOM, CRLF line endings like the device. A record of
the correction is appended to `georef_correction.json` in --out-dir;
--correction-date pins its date so the same command reproduces byte-identical
output.

PPF header offsets (little-endian float32), confirmed on surveys with good and
with spoofed GNSS from the same device (software 1.7.2): start lon 358, lat
382, alt 406; end lon 430, lat 454, alt 478.

Usage:
    python scripts/georef_g3_spoofed.py --survey-dir <...>/Surveys \\
        --survey "2026-11-14 10h08m29s Zao_1" --route route.geojson \\
        --out-dir <dir> [--reverse] [--correction-date 2026-11-15]
"""

import argparse
import datetime
import json
import math
import struct
import sys
from pathlib import Path

EARTH_RADIUS_M = 6371008.8
PPF_MAGIC = b'SPPF'
PPF_OFFSETS = {'start': (358, 382, 406), 'end': (430, 454, 478)}   # lon, lat, alt
GNSS_HEADER = 'Distance(m),Speed(km/h),Latitude,Longitude,Altitude(m),Bearing'


def haversine_m(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def bearing_deg(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    x = math.sin(lon2 - lon1) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return math.degrees(math.atan2(x, y)) % 360.0


def load_route(path: Path) -> list:
    """(lat, lon) vertices of the first LineString in a GeoJSON file ([lon, lat] order)."""
    data = json.loads(path.read_text(encoding='utf-8'))
    geometry = data['features'][0]['geometry'] if data.get('type') == 'FeatureCollection' else data
    if geometry.get('type') != 'LineString' or len(geometry['coordinates']) < 2:
        raise ValueError('route must be a LineString with at least two vertices')
    return [(float(lat), float(lon)) for lon, lat in geometry['coordinates']]


class Route:
    def __init__(self, vertices: list):
        self.vertices = vertices
        self.cum = [0.0]
        for a, b in zip(vertices, vertices[1:]):
            self.cum.append(self.cum[-1] + haversine_m(a, b))
        self.length = self.cum[-1]

    def at(self, s: float):
        """(lat, lon, bearing along the route) at arc length s, clamped to the ends."""
        s = min(max(s, 0.0), self.length)
        i = max(k for k in range(len(self.cum) - 1) if self.cum[k] <= s)
        a, b = self.vertices[i], self.vertices[i + 1]
        leg = self.cum[i + 1] - self.cum[i]
        f = (s - self.cum[i]) / leg if leg > 0 else 0.0
        return a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), bearing_deg(a, b)


def parse_gnss_line(line: str) -> tuple:
    """(distance, speed) of a device GNSS.csv data row; speed may carry a decimal comma."""
    fields = line.strip().split(',')
    if len(fields) == 7:                       # 0.300,2,04,lat,lon,alt,bearing
        return float(fields[0]), float(f'{fields[1]}.{fields[2]}')
    if len(fields) == 6:
        return float(fields[0]), float(fields[1])
    raise ValueError(f'unexpected GNSS row with {len(fields)} fields: {line!r}')


def _read_text(path: Path) -> str:
    return path.read_bytes().decode('utf-8-sig')


def rebuild_gnss(text: str, route: Route, reverse: bool):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    rows = [parse_gnss_line(ln) for ln in lines[1:]]
    total = max(d for d, _ in rows)
    if total <= 0:
        raise ValueError('GNSS distance never advances')
    out = [GNSS_HEADER]
    positions = []
    for distance, speed in rows:
        s = distance / total * route.length
        lat, lon, bearing = route.at(route.length - s if reverse else s)
        if reverse:
            bearing = (bearing + 180.0) % 360.0
        out.append(f'{distance:.3f},{speed:.2f},{lat:.8f},{lon:.8f},,{round(bearing) % 360}')
        positions.append((lat, lon))
    return '\r\n'.join(out) + '\r\n', positions[0], positions[-1], total


def rebuild_information(text: str, start, end) -> str:
    out = []
    for line in text.splitlines():
        if line.startswith('Start Location:'):
            line = f'Start Location: {start[0]:.8f},{start[1]:.8f}'
        elif line.startswith('End Location:'):
            line = f'End Location: {end[0]:.8f},{end[1]:.8f}'
        out.append(line)
    return '\r\n'.join(out) + '\r\n'


def patch_ppf(blob: bytes, start, end) -> bytes:
    if not blob.startswith(PPF_MAGIC):
        raise ValueError('not a PPF file (magic SPPF missing)')
    data = bytearray(blob)
    for key, (lat, lon) in (('start', start), ('end', end)):
        lon_off, lat_off, alt_off = PPF_OFFSETS[key]
        old_lon, old_lat = (struct.unpack_from('<f', data, o)[0] for o in (lon_off, lat_off))
        if not (abs(old_lat) <= 90 and abs(old_lon) <= 180):
            raise ValueError(f'PPF {key} location field does not hold a coordinate')
        struct.pack_into('<f', data, lon_off, lon)
        struct.pack_into('<f', data, lat_off, lat)
        struct.pack_into('<f', data, alt_off, 0.0)
    return bytes(data)


def _write_new(path: Path, payload: bytes) -> None:
    if path.exists():
        raise FileExistsError(f'refusing to overwrite {path}')
    path.write_bytes(payload)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--survey-dir', required=True, type=Path)
    parser.add_argument('--survey', required=True, help='file prefix, e.g. "2026-11-14 10h08m29s Zao_1"')
    parser.add_argument('--route', required=True, type=Path)
    parser.add_argument('--out-dir', required=True, type=Path)
    parser.add_argument('--reverse', action='store_true', help='survey ran against the route direction')
    parser.add_argument('--correction-date', default=datetime.date.today().isoformat())
    args = parser.parse_args(argv)

    route = Route(load_route(args.route))
    src = args.survey_dir / args.survey
    gnss, start, end, total = rebuild_gnss(_read_text(Path(f'{src} GNSS.csv')), route, args.reverse)
    info = rebuild_information(_read_text(Path(f'{src} Information.txt')), start, end)
    ppf = patch_ppf(Path(f'{src}.ppf').read_bytes(), start, end)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    dst = args.out_dir / args.survey
    _write_new(Path(f'{dst} GNSS.csv'), gnss.encode('utf-8'))
    _write_new(Path(f'{dst} Information.txt'), info.encode('utf-8'))
    _write_new(Path(f'{dst}.ppf'), ppf)

    record_path = args.out_dir / 'georef_correction.json'
    records = json.loads(record_path.read_text(encoding='utf-8')) if record_path.exists() else []
    records.append({
        'survey': args.survey,
        'correction_date': args.correction_date,
        'route_file': args.route.name,
        'direction': 'reverse' if args.reverse else 'forward',
        'route_length_m': round(route.length, 3),
        'odometer_length_m': round(total, 3),
        'scale_route_per_odometer': round(route.length / total, 6),
        'start': [round(start[0], 8), round(start[1], 8)],
        'end': [round(end[0], 8), round(end[1], 8)],
        'files': [f'{args.survey} GNSS.csv', f'{args.survey} Information.txt', f'{args.survey}.ppf'],
        'unchanged_and_not_copied': 'IRI, Profile, Speed, Events, .erd and raw files carry no coordinates',
    })
    record_path.write_text(json.dumps(records, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'{args.survey}: route {route.length:.1f} m, odometer {total:.1f} m, '
          f'start {start[0]:.6f},{start[1]:.6f} end {end[0]:.6f},{end[1]:.6f}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

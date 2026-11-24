#!/usr/bin/env python
"""
One-off tool: correct an ARRB Walking Profiler G3 survey recorded with a wrong
odometer calibration factor, for dissertation data provenance.

The G3 stores the odometer calibration factor it used in the survey's raw
settings file (`Surveys - Raw/<survey>.wp`, tag OdometerCalFactor). Distance is
proportional to that factor, so a survey recorded with a wrong factor has every
distance scaled by f_used / f_true. The profile is the integral of the measured
slope over the odometer distance (the field offset is a slope, in m/m), so the
elevations carry the same scale; the slopes themselves are correct. This tool
rescales distance (and, by default, elevation) by s = f_true / f_used, where
f_true comes from a later `.wp` of the same device after a correct calibration,
and recomputes IRI from the corrected profile with the standard quarter-car
(golden car, 80 km/h, 250 mm moving-average slope, 11 m initialisation; ASTM
E1926 / Sayers). Before writing, it recomputes IRI from the ORIGINAL profile and
refuses to continue unless that reproduces the device IRI.csv (mean absolute
difference of the 10 m means below --max-check-mae), so the recomputation is
proven to be the device's own algorithm.

Never mutates the source survey: it writes NEW copies into --out-dir and refuses
to overwrite existing files:
  - `<survey> Profile.csv`  corrected profile resampled to the device 25 mm grid;
  - `<survey> IRI.csv`      IRI recomputed at 1 m intervals of corrected distance;
  - `<survey> Speed.csv`, `<survey> Events.csv`  distances (and speed) x s;
  - `<survey> GNSS.csv`     distances and speed x s, coordinates unchanged, speed
                            with a decimal POINT (the device writes a comma);
  - `<survey> Information.txt`  unchanged plus one `Odometer Correction:` line.
The binary .erd/.ppf exports are NOT corrected and not copied. Outputs are UTF-8
without BOM, CRLF line endings like the device. A record is appended to
`odometer_correction.json` in --out-dir; --correction-date pins its date so the
same command reproduces byte-identical output.

Usage:
    python scripts/rescale_g3_odometer.py --survey-dir <...>/Surveys \\
        --survey "2026-11-22 06h02m15s B_l_1" \\
        --used-wp "<...>/Surveys - Raw/2026-11-22 06h02m15s B_l_1.wp" \\
        --true-wp "<...>/Surveys - Raw/2026-11-22 08h51m25s B_test.wp" \\
        --out-dir <dir> [--height-mode kept] [--correction-date 2026-11-22]
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

import numpy as np
from scipy.linalg import expm

PROFILE_DX_M = 0.025          # device profile spacing
IRI_INTERVAL_M = 1.0          # device IRI processing interval
BASE_M = 0.25                 # moving-average slope base length
INIT_M = 11.0                 # initialisation length
V_MS = 80.0 / 3.6             # simulation speed
GOLDEN_CAR = {'k1': 653.0, 'k2': 63.3, 'c': 6.0, 'mu': 0.15}
GNSS_HEADER = 'Distance(m),Speed(km/h),Latitude,Longitude,Altitude(m),Bearing'


def quarter_car_matrices():
    k1, k2, c, mu = (GOLDEN_CAR[k] for k in ('k1', 'k2', 'c', 'mu'))
    a = np.array([[0.0, 1.0, 0.0, 0.0],
                  [-k2, -c, k2, c],
                  [0.0, 0.0, 0.0, 1.0],
                  [k2 / mu, c / mu, -(k1 + k2) / mu, -c / mu]])
    b = np.array([0.0, 0.0, 0.0, k1 / mu])
    return a, b


def iri_rates(z_mm: np.ndarray, dx: float = PROFILE_DX_M) -> np.ndarray:
    """Rectified slope |z_s' - z_u'| (m/km) after each profile step; rate i
    belongs to distance (i + 1) * dx."""
    a, b = quarter_car_matrices()
    st = expm(a * dx / V_MS)
    pr = np.linalg.solve(a, (st - np.eye(4)) @ b)
    n_base = max(1, int(round(BASE_M / dx)))
    n_init = int(round(INIT_M / dx))
    if len(z_mm) <= max(n_base, n_init):
        raise ValueError('profile shorter than the 11 m initialisation length')
    slope = (z_mm[n_base:] - z_mm[:-n_base]) / (n_base * dx)    # mm/m = m/km
    s0 = (z_mm[n_init] - z_mm[0]) / INIT_M
    x = np.array([s0, 0.0, s0, 0.0])
    out = np.empty(len(slope))
    for i, s in enumerate(slope):
        x = st @ x + pr * s
        out[i] = abs(x[0] - x[2])
    return out


def iri_intervals(z_mm: np.ndarray, dx: float = PROFILE_DX_M,
                  interval: float = IRI_INTERVAL_M) -> tuple:
    """(interval end distances, IRI per interval) like the device IRI.csv: full
    intervals plus a final partial one up to the last rate."""
    rates = iri_rates(z_mm, dx)
    at = (np.arange(len(rates)) + 1) * dx
    end = float(at[-1])
    edges = np.r_[np.arange(0.0, end - 1e-9, interval), end]
    ends, values = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (at > lo + 1e-9) & (at <= hi + 1e-9)
        if m.any():
            ends.append(hi)
            values.append(float(rates[m].mean()))
    return np.array(ends), np.array(values)


def read_odometer_factor(wp_text: str) -> float:
    m = re.search(r'<OdometerCalFactor>([^<]+)</OdometerCalFactor>', wp_text)
    if not m:
        raise ValueError('no OdometerCalFactor in the .wp file')
    return float(m.group(1))


def _rows(text: str) -> list:
    return [ln for ln in text.splitlines() if ln.strip()]


def read_two_columns(text: str) -> tuple:
    rows = [ln.split(',') for ln in _rows(text)[1:]]
    return (np.array([float(r[0]) for r in rows]), np.array([float(r[1]) for r in rows]))


def rescale_profile(dist: np.ndarray, z_mm: np.ndarray, scale: float, scale_height: bool) -> np.ndarray:
    """Corrected profile on the device 25 mm grid starting at 0."""
    x = dist * scale
    zz = z_mm * (scale if scale_height else 1.0)
    n = int(np.floor(x[-1] / PROFILE_DX_M + 1e-9)) + 1
    grid = np.arange(n) * PROFILE_DX_M
    return np.interp(grid, x, zz)


def check_against_device(z_mm: np.ndarray, device_iri_text: str) -> dict:
    """Recompute IRI from the original profile and compare with the device IRI.csv."""
    dev_end, dev_iri = read_two_columns(device_iri_text)
    my_end, my_iri = iri_intervals(z_mm)
    n = min(len(dev_iri), len(my_iri))
    n10 = n // 10 * 10
    mae_10m = float(np.mean(np.abs(dev_iri[:n10].reshape(-1, 10).mean(axis=1)
                                   - my_iri[:n10].reshape(-1, 10).mean(axis=1))))
    return {'n_intervals': n, 'mae_1m': float(np.mean(np.abs(dev_iri[:n] - my_iri[:n]))),
            'mae_10m': mae_10m, 'mean_device': float(dev_iri.mean()), 'mean_recomputed': float(my_iri.mean())}


def _fmt_rows(header: str, rows: list) -> str:
    return '\r\n'.join([header] + rows) + '\r\n'


def rescale_two_column(text: str, scale: float, scale_value: bool) -> str:
    lines = _rows(text)
    out = []
    for ln in lines[1:]:
        f = ln.split(',')
        d = float(f[0]) * scale
        v = float(f[1]) * scale if scale_value else float(f[1])
        out.append(f'{d:.3f},{v:.1f}')
    return _fmt_rows(lines[0], out)


def rescale_events(text: str, scale: float) -> str:
    lines = _rows(text)
    out = []
    for ln in lines[1:]:
        f = ln.split(',', 1)
        out.append(f'{float(f[0]) * scale:.3f},{f[1]}')
    return _fmt_rows(lines[0], out)


def rescale_gnss(text: str, scale: float) -> str:
    out = []
    for ln in _rows(text)[1:]:
        f = ln.split(',')
        if len(f) == 7:                         # 0.300,2,04,lat,lon,alt,bearing
            speed, rest = float(f'{f[1]}.{f[2]}'), f[3:]
        elif len(f) == 6:
            speed, rest = float(f[1]), f[2:]
        else:
            raise ValueError(f'unexpected GNSS row with {len(f)} fields: {ln!r}')
        out.append(','.join([f'{float(f[0]) * scale:.3f}', f'{speed * scale:.2f}'] + rest))
    return _fmt_rows(GNSS_HEADER, out)


def rescale_information(text: str, scale: float, f_used: float, f_true: float, true_source: str) -> str:
    lines = [ln for ln in text.splitlines()]
    lines.append(f'Odometer Correction: distance x{scale:.6f} '
                 f'(factor {f_used:.6f} -> {f_true:.6f} from {true_source})')
    return '\r\n'.join(lines) + '\r\n'


def _read_text(path: Path) -> str:
    return path.read_bytes().decode('utf-8-sig')


def _write_new(path: Path, payload: bytes) -> None:
    if path.exists():
        raise FileExistsError(f'refusing to overwrite {path}')
    path.write_bytes(payload)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--survey-dir', required=True, type=Path)
    parser.add_argument('--survey', required=True, help='file prefix, e.g. "2026-11-22 06h02m15s B_l_1"')
    parser.add_argument('--used-wp', required=True, type=Path, help='the survey\'s own raw .wp settings')
    parser.add_argument('--true-wp', required=True, type=Path, help='a .wp recorded after a correct calibration')
    parser.add_argument('--out-dir', required=True, type=Path)
    parser.add_argument('--height-mode', choices=('scaled', 'kept'), default='scaled',
                        help='scaled: elevation x s (slope integrated over distance); kept: sensitivity variant')
    parser.add_argument('--max-check-mae', type=float, default=0.05,
                        help='max MAE (m/km) of 10 m means between device and recomputed IRI')
    parser.add_argument('--correction-date', default=datetime.date.today().isoformat())
    args = parser.parse_args(argv)

    f_used = read_odometer_factor(_read_text(args.used_wp))
    f_true = read_odometer_factor(_read_text(args.true_wp))
    scale = f_true / f_used
    src = args.survey_dir / args.survey
    dist, z = read_two_columns(_read_text(Path(f'{src} Profile.csv')))
    check = check_against_device(z, _read_text(Path(f'{src} IRI.csv')))
    if check['mae_10m'] > args.max_check_mae:
        raise ValueError(f'recomputed IRI does not reproduce the device IRI.csv '
                         f'(10 m MAE {check["mae_10m"]:.4f} > {args.max_check_mae})')

    z_corr = rescale_profile(dist, z, scale, args.height_mode == 'scaled')
    iri_end, iri = iri_intervals(z_corr)
    profile_rows = [f'{i * PROFILE_DX_M:.3f},{v:.3f}' for i, v in enumerate(z_corr)]
    iri_rows = [f'{e:.3f},{v:.3f}' for e, v in zip(iri_end, iri)]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    dst = args.out_dir / args.survey
    outputs = {
        f'{args.survey} Profile.csv': _fmt_rows('Distance(m),Profile(mm)', profile_rows),
        f'{args.survey} IRI.csv': _fmt_rows('Distance(m),IRI(m/km)', iri_rows),
        f'{args.survey} Speed.csv': rescale_two_column(_read_text(Path(f'{src} Speed.csv')), scale, True),
        f'{args.survey} Events.csv': rescale_events(_read_text(Path(f'{src} Events.csv')), scale),
        f'{args.survey} GNSS.csv': rescale_gnss(_read_text(Path(f'{src} GNSS.csv')), scale),
        f'{args.survey} Information.txt': rescale_information(
            _read_text(Path(f'{src} Information.txt')), scale, f_used, f_true, args.true_wp.name),
    }
    for name in outputs:
        if (args.out_dir / name).exists():
            raise FileExistsError(f'refusing to overwrite {args.out_dir / name}')
    for name, text in outputs.items():
        _write_new(args.out_dir / name, text.encode('utf-8'))

    record_path = args.out_dir / 'odometer_correction.json'
    records = json.loads(record_path.read_text(encoding='utf-8')) if record_path.exists() else []
    records.append({
        'survey': args.survey,
        'correction_date': args.correction_date,
        'factor_used': f_used,
        'factor_used_source': args.used_wp.name,
        'factor_true': f_true,
        'factor_true_source': args.true_wp.name,
        'distance_scale': round(scale, 6),
        'height_mode': args.height_mode,
        'length_device_m': round(float(dist[-1]), 3),
        'length_corrected_m': round(float((len(z_corr) - 1) * PROFILE_DX_M), 3),
        'iri_mean_device': round(check['mean_device'], 3),
        'iri_mean_corrected': round(float(iri.mean()), 3),
        'device_reproduction_check': {k: round(v, 4) if isinstance(v, float) else v for k, v in check.items()},
        'files': sorted(outputs),
        'not_corrected_and_not_copied': '.erd and .ppf exports, raw files',
    })
    record_path.write_text(json.dumps(records, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'{args.survey}: scale {scale:.6f}, length {dist[-1]:.1f} -> {(len(z_corr) - 1) * PROFILE_DX_M:.1f} m, '
          f'IRI {check["mean_device"]:.2f} -> {iri.mean():.2f} m/km (check 10 m MAE {check["mae_10m"]:.4f})')
    return 0


if __name__ == '__main__':
    sys.exit(main())

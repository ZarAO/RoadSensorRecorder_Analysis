"""
ARRB Walking Profiler G3 surveys as a section reference
(spec docs/superpowers/specs/2026-11-15-g3-section-reference-design.md).

A section reference is built from one or more G3 passes over the same road
section; every pass becomes one channel of the profilometer-form layout
(`iri_ch1..`), so the stored table feeds `match.load_form_10m` unchanged and
pass-to-pass disagreement shows up exactly like channel disagreement does for
the 8-channel profilometer.

All functions are pure: device file TEXT in, DataFrame/dict out.
"""

import dataclasses
import math

import numpy as np
import pandas as pd
from scipy import signal

PROFILE_DX_M = 0.025            # Profile.csv spacing of the G3
STEP_M = 10.0
MAX_CHANNELS = 8
ALIGN_BAND_M = (0.5, 30.0)      # wavelengths kept for profile alignment
ALIGN_MAX_LAG_M = 50.0
ALIGN_MIN_OVERLAP_M = 100.0
ALIGN_MIN_R = 0.4
MIN_COVERAGE = 0.9              # share of a 10 m interval a pass must cover
REFERENCE_SPEED_WARN_KMH = 1.1  # G3 manual: Reference Profiling warning threshold
DAILY_CALIBRATION_KEYS = ('Odometer Calibration Date/Time', 'Field Offset Calibration Date/Time')
CHANNEL_COUNT_IN_FORMAT = 10    # iri_ch1..iri_ch10 of the stored derived CSV
_EARTH_R = 6371008.8


def _lines(text: str) -> list:
    return [ln for ln in text.lstrip(chr(0xFEFF)).splitlines() if ln.strip()]


def parse_information(text: str) -> dict:
    """`Key: value` lines of `<survey> Information.txt` (keys stripped)."""
    info = {}
    for line in _lines(text):
        if ':' in line:
            key, value = line.split(':', 1)
            info[key.strip()] = value.strip()
    return info


def parse_iri_csv(text: str) -> pd.DataFrame:
    """1 m IRI rows as intervals [d_start, d_end) with their IRI (m/km)."""
    rows = [ln.split(',') for ln in _lines(text)[1:]]
    d_end = np.array([float(r[0]) for r in rows])
    iri = np.array([float(r[1]) for r in rows])
    if len(d_end) == 0 or np.any(np.diff(d_end) <= 0):
        raise ValueError('IRI.csv: distances must be present and strictly increasing')
    return pd.DataFrame({'d_start': np.r_[0.0, d_end[:-1]], 'd_end': d_end, 'iri': iri})


def parse_gnss_csv(text: str) -> pd.DataFrame:
    """distance/speed/lat/lon; reads the device format (speed with a decimal
    comma -> 7 fields) and the corrected 6-field format alike."""
    out = []
    for line in _lines(text)[1:]:
        f = line.split(',')
        if len(f) == 7:
            speed = float(f'{f[1]}.{f[2]}')
            lat, lon = float(f[3]), float(f[4])
        elif len(f) == 6:
            speed = float(f[1])
            lat, lon = float(f[2]), float(f[3])
        else:
            raise ValueError(f'GNSS.csv: unexpected row with {len(f)} fields')
        out.append((float(f[0]), speed, lat, lon))
    df = pd.DataFrame(out, columns=['distance', 'speed_kmh', 'lat', 'lon'])
    # (0, 0) is the device's "no fix yet" placeholder (e.g. Start Location 0,0)
    df = df[~((df['lat'] == 0.0) & (df['lon'] == 0.0))]
    if df.empty:
        raise ValueError('GNSS.csv: no rows with a position fix')
    # np.interp needs increasing x: keep the last fix per distance, in order
    return (df.drop_duplicates('distance', keep='last')
              .sort_values('distance', kind='mergesort').reset_index(drop=True))


def parse_profile_csv(text: str) -> np.ndarray:
    values = [float(ln.split(',')[1]) for ln in _lines(text)[1:]]
    if len(values) < 2:
        raise ValueError('Profile.csv: no profile data')
    return np.asarray(values)


@dataclasses.dataclass
class G3Pass:
    title: str
    info: dict
    iri: pd.DataFrame
    gnss: pd.DataFrame
    profile: np.ndarray

    @classmethod
    def from_texts(cls, title, iri_text, gnss_text, profile_text, info_text=None):
        info = parse_information(info_text) if info_text else {}
        return cls(title=info.get('Title') or title, info=info,
                   iri=parse_iri_csv(iri_text), gnss=parse_gnss_csv(gnss_text),
                   profile=parse_profile_csv(profile_text))

    @property
    def length_m(self) -> float:
        return float(self.iri['d_end'].iloc[-1])

    @property
    def date_time(self) -> str | None:
        return self.info.get('Date/Time')


def _band(z: np.ndarray) -> np.ndarray:
    lo, hi = ALIGN_BAND_M
    b, a = signal.butter(2, [1.0 / hi, 1.0 / lo], btype='band', fs=1.0 / PROFILE_DX_M)
    return signal.filtfilt(b, a, z - z.mean())


def align_by_profile(master: np.ndarray, other: np.ndarray) -> dict:
    """
    Best direction and lag of `other` against `master`: master index =
    (other index, after reversal for 'reverse') + lag/dx. Returns r of the best
    candidate even when it is below ALIGN_MIN_R (caller decides).
    """
    a = _band(master)
    a = (a - a.mean()) / a.std()
    best = None
    for direction in ('forward', 'reverse'):
        b = _band(other if direction == 'forward' else other[::-1])
        b = (b - b.mean()) / b.std()
        corr = signal.correlate(a, b, mode='full', method='fft')
        lags = signal.correlation_lags(len(a), len(b), mode='full')
        overlap = np.minimum(len(a), len(b) + lags) - np.maximum(0, lags)
        valid = (np.abs(lags) * PROFILE_DX_M <= ALIGN_MAX_LAG_M) & \
                (overlap * PROFILE_DX_M >= ALIGN_MIN_OVERLAP_M)
        if not valid.any():
            continue
        r = np.where(valid, corr / np.maximum(overlap, 1), -np.inf)
        k = int(np.argmax(r))
        cand = {'direction': direction, 'lag_m': float(lags[k] * PROFILE_DX_M),
                'r': float(r[k])}
        if best is None or cand['r'] > best['r']:
            best = cand
    if best is None:
        raise ValueError('passes too short for profile alignment')
    return best


def _haversine(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    h = (np.sin((p2 - p1) / 2) ** 2
         + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2)
    return 2 * _EARTH_R * np.arctan2(np.sqrt(h), np.sqrt(1 - h))


def _master_chainage_of(m: pd.DataFrame, lat: float, lon: float, half_window: int = 50) -> float:
    """Chainage of a point on the master track: nearest fix plus the signed
    projection onto the local track tangent, so a point a few metres beyond a
    master end is not clamped to that end."""
    lats, lons = m['lat'].to_numpy(), m['lon'].to_numpy()
    i = int(np.argmin(_haversine(lat, lon, lats, lons)))
    j0, j1 = max(0, i - half_window), min(len(m) - 1, i + half_window)
    ky = _EARTH_R * math.pi / 180.0
    kx = ky * math.cos(math.radians(lats[i]))
    tangent = np.array([(lons[j1] - lons[j0]) * kx, (lats[j1] - lats[j0]) * ky])
    norm = float(np.linalg.norm(tangent))
    if norm == 0.0:
        return float(m['distance'].iloc[i])
    offset = np.array([(lon - lons[i]) * kx, (lat - lats[i]) * ky])
    return float(m['distance'].iloc[i]) + float(offset @ (tangent / norm))


def align_by_gnss(master: G3Pass, other: G3Pass) -> dict:
    """Direction from which master end the other pass starts at; lag from the
    projection of its start onto the master track."""
    m, o = master.gnss, other.gnss
    d_start = _haversine(o['lat'].iloc[0], o['lon'].iloc[0], m['lat'].iloc[0], m['lon'].iloc[0])
    d_end = _haversine(o['lat'].iloc[0], o['lon'].iloc[0], m['lat'].iloc[-1], m['lon'].iloc[-1])
    x_start = _master_chainage_of(m, float(o['lat'].iloc[0]), float(o['lon'].iloc[0]))
    if d_end < d_start:
        return {'direction': 'reverse', 'lag_m': x_start - _profile_length(other), 'r': None}
    return {'direction': 'forward', 'lag_m': x_start, 'r': None}


def _profile_length(p: G3Pass) -> float:
    return (len(p.profile) - 1) * PROFILE_DX_M


def _to_master(p: G3Pass, alignment: dict) -> tuple:
    """The pass's 1 m intervals expressed in master chainage."""
    lo, hi = p.iri['d_start'].to_numpy(), p.iri['d_end'].to_numpy()
    if alignment['direction'] == 'reverse':
        length = _profile_length(p)
        lo, hi = length - hi, length - lo
    return lo + alignment['lag_m'], hi + alignment['lag_m'], p.iri['iri'].to_numpy()


def _resample(m_lo, m_hi, iri, grid_lo, grid_hi) -> np.ndarray:
    overlap = np.clip(np.minimum(m_hi[None, :], grid_hi[:, None])
                      - np.maximum(m_lo[None, :], grid_lo[:, None]), 0.0, None)
    covered = overlap.sum(axis=1)
    with np.errstate(invalid='ignore', divide='ignore'):
        mean = (overlap * iri[None, :]).sum(axis=1) / covered
    return np.where(covered >= MIN_COVERAGE * (grid_hi - grid_lo), mean, np.nan)


def _calibration_warning(p: G3Pass) -> str | None:
    survey_day = (p.date_time or '')[:10]
    if not survey_day:
        return None
    # only the daily calibrations; the accelerometer sensitivity calibration
    # ('Accelerometer Calibration Date/Time') is a factory one and must not be redone
    keys = [k for k in DAILY_CALIBRATION_KEYS if k in p.info]
    stale = sorted({p.info[k][:10] for k in keys if p.info[k][:10] < survey_day})
    if not stale:
        return None
    return (f'Прохід {p.title}: калібрування приладу від {stale[0]}, не в день зйомки '
            f'{survey_day} (інструкція G3 радить калібрувати зміщення акселерометра щодня)')


def _speed_warning(p: G3Pass) -> str | None:
    if p.info.get('Quality Setting') != 'Reference Profiling':
        return None
    share = float((p.gnss['speed_kmh'] > REFERENCE_SPEED_WARN_KMH).mean())
    if share <= 0:
        return None
    return (f'Прохід {p.title}: режим Reference Profiling, швидкість вища за '
            f'{REFERENCE_SPEED_WARN_KMH:g} км/год на {share:.0%} довжини')


@dataclasses.dataclass
class SectionReference:
    intervals: pd.DataFrame
    channels: list
    warnings: list
    step_m: float
    chainage_span_m: float
    bbox: list
    survey_date: str | None
    label: str


def build_section_reference(passes: list) -> SectionReference:
    if not passes:
        raise ValueError('немає жодного проходу G3')
    if len(passes) > MAX_CHANNELS:
        raise ValueError(f'забагато проходів: {len(passes)} > {MAX_CHANNELS}')
    order = sorted(range(len(passes)), key=lambda i: (passes[i].date_time or '', i))
    passes = [passes[i] for i in order]
    master = passes[0]

    n_full = int(math.floor(master.length_m / STEP_M + 1e-9))
    if n_full < 1:
        raise ValueError(f'основний прохід {master.title} коротший за {STEP_M:g} м')
    grid_lo = np.arange(n_full) * STEP_M
    grid_hi = grid_lo + STEP_M

    channels, warnings, values = [], [], []
    for index, p in enumerate(passes, start=1):
        if index == 1:
            alignment = {'direction': 'forward', 'lag_m': 0.0, 'r': 1.0, 'method': 'master'}
        else:
            alignment = align_by_profile(master.profile, p.profile)
            alignment['method'] = 'profile'
            if alignment['r'] < ALIGN_MIN_R:
                rejected = alignment['r']
                alignment = align_by_gnss(master, p)
                alignment['method'] = 'gnss'
                warnings.append(
                    f'Прохід {p.title}: профіль не вирівнюється з основним '
                    f'(r = {rejected:.2f} < {ALIGN_MIN_R}), прив\'язка за GNSS; '
                    'ймовірно інша колія або смуга')
        values.append(_resample(*_to_master(p, alignment), grid_lo, grid_hi))
        for message in (_calibration_warning(p), _speed_warning(p)):
            if message:
                warnings.append(message)
        channels.append({
            'channel': index, 'survey': p.title, 'date_time': p.date_time,
            'quality': p.info.get('Quality Setting'), 'surface': p.info.get('Surface'),
            'serial': p.info.get('Serial Number'), 'length_m': round(p.length_m, 3),
            'direction': alignment['direction'], 'alignment': alignment['method'],
            'r': None if alignment['r'] is None else round(alignment['r'], 3),
            'lag_m': round(alignment['lag_m'], 3),
        })

    for index in range(2, len(values) + 1):
        both = ~np.isnan(values[0]) & ~np.isnan(values[index - 1])
        if both.any():
            mad = float(np.mean(np.abs(values[index - 1][both] - values[0][both])))
            channels[index - 1]['mean_abs_diff_vs_ch1'] = round(mad, 3)
            warnings.append(f'Прохід {passes[index - 1].title} проти {master.title}: '
                            f'середня абсолютна різниця на 10 м {mad:.2f} м/км '
                            f'({int(both.sum())} інтервалів)')
        else:
            warnings.append(f'Прохід {passes[index - 1].title} не перекриває основний')

    g = master.gnss
    lat_lo = np.interp(grid_lo, g['distance'], g['lat'])
    lon_lo = np.interp(grid_lo, g['distance'], g['lon'])
    lat_hi = np.interp(grid_hi, g['distance'], g['lat'])
    lon_hi = np.interp(grid_hi, g['distance'], g['lon'])
    table = {'km_start': 0, 'm_start': grid_lo, 'km_end': 0, 'm_end': grid_hi}
    for ch in range(1, CHANNEL_COUNT_IN_FORMAT + 1):
        table[f'iri_ch{ch}'] = values[ch - 1] if ch <= len(values) else np.nan
    table.update({'lat_start': lat_lo, 'lon_start': lon_lo, 'alt_start': np.nan,
                  'lat_end': lat_hi, 'lon_end': lon_hi, 'alt_end': np.nan})
    intervals = pd.DataFrame(table)

    lats = np.r_[lat_lo, lat_hi]
    lons = np.r_[lon_lo, lon_hi]
    survey_date = (master.date_time or '')[:10] or None
    label = f"G3 {survey_date or ''} {'+'.join(p.title for p in passes)}".replace('  ', ' ')
    return SectionReference(
        intervals=intervals, channels=channels, warnings=warnings, step_m=STEP_M,
        chainage_span_m=float(grid_hi[-1] - grid_lo[0]),
        bbox=[float(lats.min()), float(lons.min()), float(lats.max()), float(lons.max())],
        survey_date=survey_date, label=label)

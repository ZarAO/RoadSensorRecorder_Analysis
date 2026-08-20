"""
Geo-matching of smartphone 100 m segments to profilometer form intervals.

Matching is geometric (haversine between midpoints), never by chainage: the
smartphone's s=0 is arbitrary. The study stays decoupled from the analyzer
package — only its CSV artifacts are consumed.
"""

import numpy as np
import pandas as pd

# Same Earth radius as the analyzer's compute_gps_distance, so distances stay comparable
EARTH_RADIUS_M = 6371000.0
METERS_PER_DEG_LAT = EARTH_RADIUS_M * np.pi / 180.0

# Channels 9 and 10 are byte-identical duplicates of channel 8 in every form
# file (recon 2026-08-20) — only ch1..ch8 carry independent information (D1).
REFERENCE_CHANNELS = [f'iri_ch{c}' for c in range(1, 9)]


def haversine_m(lat1, lon1, lat2, lon2):
    """Vectorized haversine distance in meters."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (np.sin((lat2 - lat1) / 2.0) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2.0) ** 2)
    return 2.0 * EARTH_RADIUS_M * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))


def load_form_intervals(csv_path: str) -> pd.DataFrame:
    """
    Read a derived form CSV (one row per 100 m interval) into the reference
    table: iri_ref = mean(ch1..ch8), midpoint coordinate, chainage midpoint.
    """
    df = pd.read_csv(csv_path, encoding='utf-8')
    out = pd.DataFrame({
        'iri_ref': df[REFERENCE_CHANNELS].mean(axis=1),
        'lat_mid': (df['lat_start'] + df['lat_end']) / 2.0,
        'lon_mid': (df['lon_start'] + df['lon_end']) / 2.0,
        'chainage_m': ((df['km_start'] * 1000.0 + df['m_start'])
                       + (df['km_end'] * 1000.0 + df['m_end'])) / 2.0,
    })
    out.index.name = 'interval_id'
    return out.reset_index()


def build_gps_track(csv_path: str) -> pd.DataFrame:
    """
    Extract the Location rows of a recording into time_s/lat/lon/s, where s is
    the haversine cumulative distance (m) from the first fix.
    """
    df = pd.read_csv(csv_path, comment='#', index_col=False)
    loc = df[df['Type'].astype(str).str.lower() == 'location'].copy()
    loc = loc.sort_values('Time', kind='mergesort').dropna(subset=['Latitude', 'Longitude'])
    lat = loc['Latitude'].to_numpy(float)
    lon = loc['Longitude'].to_numpy(float)
    step = np.zeros(len(loc))
    if len(loc) > 1:
        step[1:] = haversine_m(lat[:-1], lon[:-1], lat[1:], lon[1:])
    return pd.DataFrame({
        'time_s': (loc['Time'].to_numpy(float) - float(loc['Time'].iloc[0])) / 1000.0,
        'lat': lat,
        'lon': lon,
        's': np.cumsum(step),
    })


def segment_midpoints(segments_df: pd.DataFrame, gps_track: pd.DataFrame) -> pd.DataFrame:
    """
    Midpoint coordinate for every usable segment: interpolate lat/lon along
    the GPS track at the segment's mid-chainage. Partial and class-1/2-survey
    segments are excluded up front (spec §3).

    Note: the analyzer's s starts after the GPS-coverage/edge trims while the
    raw track's s starts at the first fix. The offset between the two grids is
    bounded by the trim (~3 s of driving); at 100 m granularity with a 60 m
    match tolerance this is acceptable and is measured by match_dist_m.
    """
    usable = segments_df[
        (~segments_df['partial'].astype(bool))
        & (~segments_df['needs_class12_survey'].astype(bool))
    ].copy()
    s_mid = (usable['s_start'].to_numpy(float) + usable['s_end'].to_numpy(float)) / 2.0
    usable['lat_mid'] = np.interp(s_mid, gps_track['s'], gps_track['lat'])
    usable['lon_mid'] = np.interp(s_mid, gps_track['s'], gps_track['lon'])
    return usable.sort_values('seg_id', kind='mergesort').reset_index(drop=True)


def match_segments(seg_mid_df: pd.DataFrame, intervals_df: pd.DataFrame,
                   tolerance_m: float = 60.0) -> pd.DataFrame:
    """
    One-to-one nearest matching within tolerance_m.

    Greedy by ascending distance over the full candidate matrix: the globally
    nearest (segment, interval) pair is fixed first, both are removed, repeat.
    Deterministic: ties broken by (seg_id, interval_id).
    """
    if len(seg_mid_df) == 0 or len(intervals_df) == 0:
        return pd.DataFrame()

    seg = seg_mid_df.sort_values('seg_id', kind='mergesort').reset_index(drop=True)
    dist = haversine_m(
        seg['lat_mid'].to_numpy(float)[:, None],
        seg['lon_mid'].to_numpy(float)[:, None],
        intervals_df['lat_mid'].to_numpy(float)[None, :],
        intervals_df['lon_mid'].to_numpy(float)[None, :],
    )

    candidates = [
        (dist[i, j], int(seg['seg_id'].iloc[i]), int(intervals_df['interval_id'].iloc[j]), i, j)
        for i, j in zip(*np.nonzero(dist <= tolerance_m))
    ]
    candidates.sort(key=lambda c: (c[0], c[1], c[2]))

    used_segments, used_intervals, picks = set(), set(), []
    for d, seg_id, interval_id, i, j in candidates:
        if i in used_segments or j in used_intervals:
            continue
        used_segments.add(i)
        used_intervals.add(j)
        picks.append((i, j, d))

    if not picks:
        return pd.DataFrame()

    picks.sort(key=lambda p: int(seg['seg_id'].iloc[p[0]]))
    rows = []
    for i, j, d in picks:
        row = seg.iloc[i].to_dict()
        row.update(intervals_df.iloc[j][['interval_id', 'iri_ref', 'chainage_m']].to_dict())
        row['match_dist_m'] = d
        rows.append(row)
    return pd.DataFrame(rows)

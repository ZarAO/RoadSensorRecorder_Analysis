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


def segment_midpoints_from_geojson(segments_df: pd.DataFrame,
                                   geojson_path: str) -> pd.DataFrame:
    """
    Segment midpoints from the run's own roughness.geojson: its LineStrings are
    built on the exact s-grid the metrics used, so no re-derived distance drift
    is introduced (a raw-track cumsum drifts by tens of meters over ~15 km,
    smearing 100 m matches — observed in the first study iteration).

    GeoJSON order is [lon, lat]. Midpoint = middle vertex of the LineString.
    The geojson carries no seg_id property, but its features are written from
    the SAME DataFrame (same order) as road_segments.csv — the alignment is
    positional and is guarded by a feature-count == row-count check.
    """
    import json

    with open(geojson_path, encoding='utf-8') as f:
        collection = json.load(f)
    features = collection.get('features', [])
    if len(features) != len(segments_df):
        raise ValueError(
            f'geojson features ({len(features)}) != segment rows '
            f'({len(segments_df)}): positional alignment is not safe')

    segments = segments_df.reset_index(drop=True).copy()
    mids, starts, ends = [], [], []
    for feature in features:
        coords = feature.get('geometry', {}).get('coordinates') or []
        if not coords:
            mids.append((np.nan, np.nan))
            starts.append((np.nan, np.nan))
            ends.append((np.nan, np.nan))
            continue
        lon, lat = coords[len(coords) // 2]
        mids.append((lat, lon))
        starts.append((coords[0][1], coords[0][0]))
        ends.append((coords[-1][1], coords[-1][0]))
    segments['lat_mid'] = [m[0] for m in mids]
    segments['lon_mid'] = [m[1] for m in mids]
    segments['lat_a'] = [s[0] for s in starts]
    segments['lon_a'] = [s[1] for s in starts]
    segments['lat_b'] = [e[0] for e in ends]
    segments['lon_b'] = [e[1] for e in ends]

    usable = segments[
        (~segments['partial'].astype(bool))
        & (~segments['needs_class12_survey'].astype(bool))
        & segments['lat_mid'].notna()
    ]
    return usable.sort_values('seg_id', kind='mergesort').reset_index(drop=True)


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


def load_form_10m(csv_path: str) -> pd.DataFrame:
    """
    The 10 m form table as a chainage-indexed reference profile:
    iri_ref_10 = mean(ch1..ch8), midpoint coordinate and chainage per 10 m row.
    """
    df = pd.read_csv(csv_path, encoding='utf-8')
    return pd.DataFrame({
        'iri_ref_10': df[REFERENCE_CHANNELS].mean(axis=1),
        'lat_mid': (df['lat_start'] + df['lat_end']) / 2.0,
        'lon_mid': (df['lon_start'] + df['lon_end']) / 2.0,
        'chainage_m': ((df['km_start'] * 1000.0 + df['m_start'])
                       + (df['km_end'] * 1000.0 + df['m_end'])) / 2.0,
    })


def windowed_reference(seg_df: pd.DataFrame, form_10m: pd.DataFrame,
                       endpoint_tolerance_m: float = 60.0,
                       min_rows_in_window: int = 6,
                       max_window_m: float = 160.0) -> pd.DataFrame:
    """
    Grid-phase-free reference: for every smartphone segment, project its two
    geographic endpoints onto the profilometer chainage (nearest 10 m row) and
    average the 10 m reference IRI over that chainage window.

    Two independent 100 m partitions of one road are offset by an arbitrary,
    road-constant phase (observed: ~41 m on Т1016) — nearest-interval matching
    then mixes ~40% of a neighboring interval into every pair. Averaging the
    10 m profile over the segment's own span removes that phase error entirely.

    Output columns: everything from seg_df plus iri_ref, chainage_m,
    match_dist_m (worst endpoint projection distance), n_ref_rows.
    Segments whose endpoints project farther than endpoint_tolerance_m, whose
    window is degenerate (loop/detour) or thinner than min_rows_in_window are
    dropped.
    """
    ref_lat = form_10m['lat_mid'].to_numpy(float)
    ref_lon = form_10m['lon_mid'].to_numpy(float)
    ref_chain = form_10m['chainage_m'].to_numpy(float)
    ref_iri = form_10m['iri_ref_10'].to_numpy(float)

    rows = []
    for _, seg in seg_df.iterrows():
        d_a = haversine_m(seg['lat_a'], seg['lon_a'], ref_lat, ref_lon)
        d_b = haversine_m(seg['lat_b'], seg['lon_b'], ref_lat, ref_lon)
        i_a, i_b = int(np.argmin(d_a)), int(np.argmin(d_b))
        worst = float(max(d_a[i_a], d_b[i_b]))
        if worst > endpoint_tolerance_m:
            continue
        chain_lo = min(ref_chain[i_a], ref_chain[i_b])
        chain_hi = max(ref_chain[i_a], ref_chain[i_b])
        if chain_hi - chain_lo > max_window_m:
            continue  # endpoints projected onto distant parts (loop/ambiguity)
        in_window = (ref_chain >= chain_lo) & (ref_chain <= chain_hi)
        if int(np.sum(in_window)) < min_rows_in_window:
            continue
        row = seg.to_dict()
        row.update({
            'iri_ref': float(np.mean(ref_iri[in_window])),
            'chainage_m': (chain_lo + chain_hi) / 2.0,
            'match_dist_m': worst,
            'n_ref_rows': int(np.sum(in_window)),
        })
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return (pd.DataFrame(rows)
            .sort_values('seg_id', kind='mergesort')
            .reset_index(drop=True))


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

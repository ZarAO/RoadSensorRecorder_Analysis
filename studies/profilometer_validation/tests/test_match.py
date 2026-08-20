"""
Unit tests for geo-matching on synthetic geometry: a straight road running due
north, profilometer intervals every 100 m, GPS fixes every second.
"""

import numpy as np
import pandas as pd
import pytest

from match import (
    METERS_PER_DEG_LAT, build_gps_track, load_form_intervals, match_segments,
    segment_midpoints,
)

LAT0, LON0 = 50.4, 30.5


def _form_csv(tmp_path, n_intervals=5, lat0=LAT0, step_m=100.0):
    """Synthetic derived-form CSV in the exact schema of derived/*.csv."""
    rows = []
    for i in range(n_intervals):
        lat_s = lat0 + i * step_m / METERS_PER_DEG_LAT
        lat_e = lat0 + (i + 1) * step_m / METERS_PER_DEG_LAT
        rows.append({
            'km_start': 19, 'm_start': i * 100, 'km_end': 19, 'm_end': (i + 1) * 100,
            **{f'iri_ch{c}': 1.0 + 0.1 * c + i for c in range(1, 9)},
            'iri_ch9': 99.0, 'iri_ch10': 99.0,   # duplicates of ch8 in real data; must be IGNORED
            'lat_start': lat_s, 'lon_start': LON0, 'alt_start': 100.0,
            'lat_end': lat_e, 'lon_end': LON0, 'alt_end': 100.0,
        })
    p = tmp_path / 'form_100.csv'
    pd.DataFrame(rows).to_csv(p, index=False, encoding='utf-8')
    return str(p)


def _recording_csv(tmp_path, duration_s=60, speed_mps=10.0, lat0=LAT0):
    """Minimal contract CSV with only Location rows (enough for a GPS track)."""
    t = np.arange(0, duration_s + 1)
    df = pd.DataFrame({
        'Time': 1787220000000 + t * 1000,
        'Type': 'Location',
        'X': np.nan, 'Y': np.nan, 'Z': np.nan,
        'Latitude': lat0 + speed_mps * t / METERS_PER_DEG_LAT,
        'Longitude': LON0,
    })
    p = tmp_path / 'rec.csv'
    df.to_csv(p, index=False, encoding='utf-8')
    return str(p)


def _segments(seg_ids, s_starts, partial=False, survey=False):
    return pd.DataFrame({
        'seg_id': seg_ids,
        's_start': s_starts,
        's_end': [s + 100.0 for s in s_starts],
        'partial': partial,
        'needs_class12_survey': survey,
        'psd_sqrt_scalar': 0.5,
        'grms': 0.01,
        'mean_speed_kmh': 36.0,
        'iri_multi': 2.0,
    })


def test_load_form_intervals_averages_ch1_to_ch8_only(tmp_path):
    intervals = load_form_intervals(_form_csv(tmp_path))
    # i=0: mean over ch1..ch8 of (1.0 + 0.1*c) = 1.0 + 0.1*4.5 = 1.45; ch9/10=99 ignored
    assert intervals['iri_ref'].iloc[0] == pytest.approx(1.45)
    assert len(intervals) == 5
    assert intervals['chainage_m'].iloc[0] == pytest.approx(19 * 1000 + 50)
    # midpoint lies between the endpoint latitudes
    assert LAT0 < intervals['lat_mid'].iloc[0] < LAT0 + 100 / METERS_PER_DEG_LAT


def test_build_gps_track_cumulative_distance(tmp_path):
    track = build_gps_track(_recording_csv(tmp_path, duration_s=60, speed_mps=10.0))
    assert list(track.columns) == ['time_s', 'lat', 'lon', 's']
    assert track['s'].iloc[0] == 0.0
    assert track['s'].iloc[-1] == pytest.approx(600.0, rel=0.01)


def test_segment_midpoints_interpolate_on_track(tmp_path):
    track = build_gps_track(_recording_csv(tmp_path))
    mids = segment_midpoints(_segments([0, 1], [0.0, 100.0]), track)
    # segment 0 midpoint at s=50 -> 50 m north of LAT0
    assert mids['lat_mid'].iloc[0] == pytest.approx(LAT0 + 50 / METERS_PER_DEG_LAT, abs=1e-6)
    assert len(mids) == 2


def test_partial_and_survey_segments_are_dropped(tmp_path):
    track = build_gps_track(_recording_csv(tmp_path))
    segments = pd.concat([
        _segments([0], [0.0]),
        _segments([1], [100.0], partial=True),
        _segments([2], [200.0], survey=True),
    ])
    mids = segment_midpoints(segments, track)
    assert list(mids['seg_id']) == [0]


def test_match_one_to_one_nearest_wins(tmp_path):
    intervals = load_form_intervals(_form_csv(tmp_path, n_intervals=1))
    # Two candidate segments: one 10 m from the interval midpoint, one 40 m away
    seg_mid = pd.DataFrame({
        'seg_id': [7, 8],
        'lat_mid': [intervals['lat_mid'].iloc[0] + 10 / METERS_PER_DEG_LAT,
                    intervals['lat_mid'].iloc[0] + 40 / METERS_PER_DEG_LAT],
        'lon_mid': [LON0, LON0],
        'psd_sqrt_scalar': [0.5, 0.6], 'grms': [0.01, 0.02],
        'mean_speed_kmh': [36.0, 36.0], 'iri_multi': [2.0, 2.1],
    })
    matched = match_segments(seg_mid, intervals, tolerance_m=60.0)
    assert len(matched) == 1
    assert matched['seg_id'].iloc[0] == 7
    assert matched['match_dist_m'].iloc[0] == pytest.approx(10.0, abs=1.0)
    assert matched['iri_ref'].iloc[0] == pytest.approx(1.45)


def test_match_tolerance_excludes_far_segments(tmp_path):
    intervals = load_form_intervals(_form_csv(tmp_path, n_intervals=1))
    seg_mid = pd.DataFrame({
        'seg_id': [1],
        'lat_mid': [intervals['lat_mid'].iloc[0] + 200 / METERS_PER_DEG_LAT],
        'lon_mid': [LON0],
        'psd_sqrt_scalar': [0.5], 'grms': [0.01],
        'mean_speed_kmh': [36.0], 'iri_multi': [2.0],
    })
    assert len(match_segments(seg_mid, intervals, tolerance_m=60.0)) == 0


def test_match_is_deterministic_under_row_shuffle(tmp_path):
    intervals = load_form_intervals(_form_csv(tmp_path, n_intervals=5))
    rng = np.random.default_rng(20260101)
    lat_noise = rng.uniform(-5, 5, size=5) / METERS_PER_DEG_LAT
    seg_mid = pd.DataFrame({
        'seg_id': [0, 1, 2, 3, 4],
        'lat_mid': intervals['lat_mid'].values + lat_noise,
        'lon_mid': LON0,
        'psd_sqrt_scalar': 0.5, 'grms': 0.01, 'mean_speed_kmh': 36.0, 'iri_multi': 2.0,
    })
    a = match_segments(seg_mid, intervals, tolerance_m=60.0)
    b = match_segments(seg_mid.sample(frac=1, random_state=7), intervals, tolerance_m=60.0)
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))

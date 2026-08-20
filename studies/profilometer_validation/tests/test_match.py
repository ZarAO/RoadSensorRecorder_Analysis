"""
Unit tests for geo-matching on synthetic geometry: a straight road running due
north, profilometer intervals every 100 m, GPS fixes every second.
"""

import numpy as np
import pandas as pd
import pytest

from profilometer_validation.match import (
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


def test_segment_midpoints_from_geojson_positional(tmp_path):
    import json
    from profilometer_validation.match import segment_midpoints_from_geojson

    segments = _segments([0, 1, 2], [0.0, 100.0, 200.0])
    segments.loc[1, 'partial'] = True
    features = []
    for i in range(3):
        features.append({
            'type': 'Feature', 'properties': {},
            'geometry': {'type': 'LineString',
                         'coordinates': [[30.5, 50.4 + i * 0.001],
                                         [30.5, 50.4005 + i * 0.001],
                                         [30.5, 50.401 + i * 0.001]]},
        })
    p = tmp_path / 'roughness.geojson'
    p.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}),
                 encoding='utf-8')

    mids = segment_midpoints_from_geojson(segments, str(p))
    assert list(mids['seg_id']) == [0, 2]            # partial row dropped
    assert mids['lat_mid'].iloc[0] == pytest.approx(50.4005)  # middle vertex
    assert mids['lon_mid'].iloc[0] == 30.5


def test_segment_midpoints_from_geojson_count_mismatch_raises(tmp_path):
    import json
    from profilometer_validation.match import segment_midpoints_from_geojson

    p = tmp_path / 'roughness.geojson'
    p.write_text(json.dumps({'type': 'FeatureCollection', 'features': []}),
                 encoding='utf-8')
    with pytest.raises(ValueError, match='positional alignment'):
        segment_midpoints_from_geojson(_segments([0], [0.0]), str(p))


def _form10_csv(tmp_path, n=30, lat0=LAT0):
    """10 m step synthetic form along the same northbound road."""
    rows = []
    for i in range(n):
        lat_s = lat0 + i * 10.0 / METERS_PER_DEG_LAT
        lat_e = lat0 + (i + 1) * 10.0 / METERS_PER_DEG_LAT
        rows.append({
            'km_start': 0, 'm_start': i * 10, 'km_end': 0, 'm_end': (i + 1) * 10,
            **{f'iri_ch{c}': float(i) for c in range(1, 9)},   # iri == row index
            'iri_ch9': 0.0, 'iri_ch10': 0.0,
            'lat_start': lat_s, 'lon_start': LON0, 'alt_start': 100.0,
            'lat_end': lat_e, 'lon_end': LON0, 'alt_end': 100.0,
        })
    p = tmp_path / 'form_10.csv'
    pd.DataFrame(rows).to_csv(p, index=False, encoding='utf-8')
    return str(p)


def _seg_with_endpoints(seg_id, s_a, s_b, lat0=LAT0):
    return pd.DataFrame({
        'seg_id': [seg_id], 's_start': [s_a], 's_end': [s_b],
        'partial': False, 'needs_class12_survey': False,
        'psd_sqrt_scalar': 0.5, 'grms': 0.01, 'mean_speed_kmh': 36.0,
        'iri_multi': 2.0, 'iri_psd_raw': -0.5,
        'lat_a': lat0 + s_a / METERS_PER_DEG_LAT, 'lon_a': LON0,
        'lat_b': lat0 + s_b / METERS_PER_DEG_LAT, 'lon_b': LON0,
        'lat_mid': lat0 + (s_a + s_b) / 2 / METERS_PER_DEG_LAT, 'lon_mid': LON0,
    })


def test_windowed_reference_averages_the_span(tmp_path):
    from profilometer_validation.match import load_form_10m, windowed_reference
    form10 = load_form_10m(_form10_csv(tmp_path))
    # Segment spanning s=50..150: nearest 10m midpoints are rows 5..14
    # (midpoint of row i sits at 10*i+5)
    seg = _seg_with_endpoints(0, 50.0, 150.0)
    out = windowed_reference(seg, form10)
    assert len(out) == 1
    row_lo, row_hi = 4, 14        # chainage 45..145 inclusive window
    expected = np.mean(np.arange(row_lo, row_hi + 1))
    assert out['iri_ref'].iloc[0] == pytest.approx(expected, abs=0.51)
    assert out['n_ref_rows'].iloc[0] >= 9


def test_windowed_reference_drops_far_and_degenerate(tmp_path):
    from profilometer_validation.match import load_form_10m, windowed_reference
    form10 = load_form_10m(_form10_csv(tmp_path))
    far = _seg_with_endpoints(1, 50.0, 150.0)
    far['lon_a'] = far['lon_b'] = LON0 + 0.01          # ~700 m east
    degenerate = _seg_with_endpoints(2, 100.0, 101.0)  # window of ~1 row
    out = windowed_reference(pd.concat([far, degenerate]), form10)
    assert len(out) == 0

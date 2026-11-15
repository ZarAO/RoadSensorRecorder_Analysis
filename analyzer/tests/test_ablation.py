"""
Tests for the experimental ablation switches of analyze()
(spec 2026-11-15-calibration-model-and-ablation-design.md, section 4).

Every switch is opt-in. The default path is pinned byte for byte: the digests in
DEFAULT_RUN_DIGESTS were captured from the pipeline BEFORE the switches existed,
on the drives built below. A deliberate change to the default pipeline must
re-pin them; an accidental one fails here.

Each switch is then checked to move its result in the expected direction on a
drive built to expose it: a phone tilted 30 deg (orientation), a speed that
changes along the drive (time windows) and a stretch below 20 km/h (speed gate).
"""

import contextlib
import hashlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import road_quality_analyzer.cli as cli
from road_quality_analyzer.cli import analyze
from road_quality_analyzer.metrics.iri import (
    IRI_MULTI_DEFAULT_PARAMS, VehicleType, compute_iri_multi
)
from road_quality_analyzer.orientation import naive_device_vertical
from road_quality_analyzer.segmentation.segment_100m import (
    aggregate_segment_metrics, create_time_segments
)
from tests.conftest import G0, METERS_PER_DEG_LAT, write_drive_csv
from tests.test_cli import BASELINE_SPEED_MPS, _baseline_excitation

FS = 100.0
LAT0 = 50.4  # write_drive_csv default
ROLL_DEG = 30.0

ARTIFACTS = ('road_segments.csv', 'roughness.geojson', 'recording_meta.json', 'report.md')


def _ablation_distance(t):
    """Metres north: 4 m/s (14.4 km/h) to 20 s, 10 m/s to 50 s, then 20 m/s."""
    t = np.asarray(t, float)
    return np.where(t < 20.0, 4.0 * t,
                    np.where(t < 50.0, 80.0 + 10.0 * (t - 20.0), 380.0 + 20.0 * (t - 50.0)))


# name -> (CSV file name, write_drive_csv kwargs); the file name is part of
# report.md, so it is fixed
DRIVES = {
    # The baseline_run drive of test_cli.py
    'baseline': ('drive.csv', dict(duration_s=40.0, speed_mps=BASELINE_SPEED_MPS,
                                   a_vert=_baseline_excitation)),
    # Tilted phone, varying speed, a low-speed stretch
    'ablation': ('ablation_drive.csv', dict(duration_s=70.0, distance_m=_ablation_distance,
                                            roll_deg=ROLL_DEG, a_vert=_baseline_excitation)),
}

# sha256 of the default-run artifacts, input path replaced by '<input>' (see
# _normalized_digests), captured from the pre-ablation pipeline
DEFAULT_RUN_DIGESTS = {
    'baseline': {
        'road_segments.csv': 'a709c219602fd89a5946ba4baf3b39d9607c277b90329b6c9a793bca5de789ef',
        'roughness.geojson': '3d4e6e97342c06efd21d6bcf73240c49bdb87468e7ed1510ccc2bf714205eccc',
        'recording_meta.json': 'bda856f0f7edd52f9363bfeb68ec63c90541ecb111ddb5426da9caaa15080e94',
        'report.md': '596c27d11a420a2f173854b96b3bd7b1540513ab5f0d93bfbb988ba131ab2e1a',
    },
    'ablation': {
        'road_segments.csv': '7c23f7d420e933879c58084b5e040e5999881a147d329ae95887368a52fe6678',
        'roughness.geojson': '850248a89d39cc89d8f5ead4a8d9709933b347c9a2252795512a53cf766cb444',
        'recording_meta.json': 'bda856f0f7edd52f9363bfeb68ec63c90541ecb111ddb5426da9caaa15080e94',
        'report.md': '41e30a2c5434d27a60d49d88c76e44211ca896e0b21e8cf718b7e70bf8a68264',
    },
}


def _normalized_digests(out_dir, csv_path) -> dict:
    """
    sha256 per artifact. report.md and recording_meta.json carry the input path
    (tmp_path differs per run), so it is replaced by '<input>' first - as written
    raw in the report and JSON-escaped in the metadata.
    """
    csv_path = str(csv_path)
    digests = {}
    for name in ARTIFACTS:
        data = (Path(out_dir) / name).read_bytes()
        if name == 'report.md':
            data = data.replace(csv_path.encode('utf-8'), b'<input>')
        elif name == 'recording_meta.json':
            data = data.replace(json.dumps(csv_path, ensure_ascii=False)[1:-1].encode('utf-8'),
                                b'<input>')
        digests[name] = hashlib.sha256(data).hexdigest()
    return digests


def run_analyze(input_path, output_dir, **kwargs) -> str:
    """analyze() with the Cyrillic progress log captured in memory."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        analyze(str(input_path), str(output_dir), **kwargs)
    return buffer.getvalue()


def _load(out_dir) -> dict:
    out_dir = Path(out_dir)
    return {
        'segments': pd.read_csv(out_dir / 'road_segments.csv'),
        'geojson': json.loads((out_dir / 'roughness.geojson').read_text(encoding='utf-8')),
        'meta': json.loads((out_dir / 'recording_meta.json').read_text(encoding='utf-8')),
        'report': (out_dir / 'report.md').read_text(encoding='utf-8'),
    }


VARIANTS = {
    'default': {},
    'orientation': {'ablate_orientation': True},
    'time': {'ablate_segmentation_time': True},
    'gate': {'ablate_speed_gate': True},
    'all': {'ablate_orientation': True, 'ablate_segmentation_time': True,
            'ablate_speed_gate': True},
}


@pytest.fixture(scope='module')
def ablation_runs(tmp_path_factory):
    """Every variant once over the same tilted, variable-speed drive."""
    base = tmp_path_factory.mktemp('ablation')
    name, kwargs = DRIVES['ablation']
    csv_path = write_drive_csv(base / name, **kwargs)
    runs = {'csv': csv_path}
    for variant, switches in VARIANTS.items():
        out_dir = base / variant
        log = run_analyze(csv_path, out_dir, **switches)
        runs[variant] = {'out': out_dir, 'log': log, **_load(out_dir)}
    return runs


# --- Default path: byte-identical to the pipeline before the switches ---------

@pytest.mark.parametrize('drive', sorted(DRIVES))
def test_default_run_is_byte_identical_to_the_pre_ablation_pipeline(drive, tmp_path):
    name, kwargs = DRIVES[drive]
    csv_path = write_drive_csv(tmp_path / name, **kwargs)
    run_analyze(csv_path, tmp_path / 'out')

    assert _normalized_digests(tmp_path / 'out', csv_path) == DEFAULT_RUN_DIGESTS[drive]


def test_explicit_off_switches_equal_the_default(ablation_runs, tmp_path):
    run_analyze(ablation_runs['csv'], tmp_path / 'off', ablate_orientation=False,
                ablate_segmentation_time=False, ablate_speed_gate=False)

    assert (_normalized_digests(tmp_path / 'off', ablation_runs['csv'])
            == DEFAULT_RUN_DIGESTS['ablation'])


def test_default_run_records_no_ablation(ablation_runs):
    run = ablation_runs['default']
    assert 'ablations' not in run['meta']
    assert 'ABLATION' not in run['report']
    assert 'ABLATION' not in run['log']


# --- CLI flags ----------------------------------------------------------------

@pytest.mark.parametrize('argv, expected', [
    ([], dict(ablate_orientation=False, ablate_segmentation_time=False,
              ablate_speed_gate=False)),
    (['--ablate-orientation', '--ablate-segmentation-time', '--ablate-speed-gate'],
     dict(ablate_orientation=True, ablate_segmentation_time=True, ablate_speed_gate=True)),
    (['--ablate-speed-gate'], dict(ablate_orientation=False, ablate_segmentation_time=False,
                                   ablate_speed_gate=True)),
])
def test_cli_flags_reach_analyze(monkeypatch, argv, expected):
    calls = []
    monkeypatch.setattr(cli, 'analyze', lambda *args, **kwargs: calls.append(kwargs))
    monkeypatch.setattr(sys, 'argv', ['road_quality_analyzer', 'analyze',
                                      '--input', 'in.csv', '--out', 'out', *argv])
    cli.main()

    assert len(calls) == 1
    assert {k: calls[0][k] for k in expected} == expected


# --- Orientation ablation -----------------------------------------------------

def test_naive_vertical_of_a_flat_phone_matches_the_world_frame_sign():
    """Flat phone: z carries gravity; the vertical is -(z - mean), as transform_to_world."""
    t = np.arange(2000) / FS
    bump = 0.5 * np.sin(2 * np.pi * 2.0 * t)
    zeros = np.zeros_like(t)

    a_vertical, axis, axis_mean = naive_device_vertical(zeros, zeros, G0 + bump)

    assert axis == 'z'
    assert axis_mean == pytest.approx(G0 + bump.mean())
    np.testing.assert_allclose(a_vertical, -(bump - bump.mean()), atol=1e-12)


def test_naive_vertical_picks_the_axis_with_the_largest_absolute_mean():
    """Rolled 60 deg, gravity sits mostly on -y: y is taken, at sin(60) of the bump."""
    t = np.arange(2000) / FS
    bump = 0.5 * np.sin(2 * np.pi * 2.0 * t)
    roll = np.deg2rad(60.0)
    a_y = -np.sin(roll) * (G0 + bump)
    a_z = np.cos(roll) * (G0 + bump)

    a_vertical, axis, axis_mean = naive_device_vertical(np.zeros_like(t), a_y, a_z)

    assert axis == 'y'
    assert axis_mean < 0
    assert np.std(a_vertical) == pytest.approx(np.sin(roll) * np.std(bump), rel=1e-9)


def test_orientation_ablation_loses_the_tilted_share_of_grms(ablation_runs):
    """
    The full chain recovers the vertical on a phone rolled 30 deg; the device z
    axis sees only cos(30 deg) of it, so Grms drops by that factor.
    """
    full = ablation_runs['default']['segments']
    naive = ablation_runs['orientation']['segments']

    assert list(naive['seg_id']) == list(full['seg_id'])  # same 100 m segments
    expected_grms = np.sqrt((0.4**2 + 0.15**2) / 2) / G0
    assert full['grms'][~full['partial']].to_numpy() == pytest.approx(expected_grms, rel=0.02)
    ratio = (naive['grms'] / full['grms'])[~full['partial']].to_numpy()
    assert ratio == pytest.approx(np.cos(np.deg2rad(ROLL_DEG)), rel=0.01)


def test_orientation_ablation_is_recorded(ablation_runs):
    run = ablation_runs['orientation']
    details = run['meta']['ablations']['orientation']

    assert set(run['meta']['ablations']) == {'orientation'}
    assert details['vertical_axis'] == 'z'
    assert details['axis_mean_ms2'] == pytest.approx(np.cos(np.deg2rad(ROLL_DEG)) * G0,
                                                     rel=1e-3)
    assert details['tilt_deg'] == pytest.approx(ROLL_DEG, abs=0.5)
    assert 'ABLATION RUN' in run['report']
    assert '`--ablate-orientation`' in run['report']
    assert 'Gravity alignment: OFF (ABLATION)' in run['report']
    assert 'Gravity alignment: lowpass filter' not in run['report']


# --- Time-segmentation ablation -----------------------------------------------

def test_create_time_segments_cuts_consecutive_fixed_windows():
    segments = create_time_segments(np.arange(25.0), window_samples=10)

    assert list(segments) == [0, 1, 2]
    np.testing.assert_array_equal(segments[0], np.arange(10))
    np.testing.assert_array_equal(segments[2], np.arange(20, 25))


@pytest.mark.parametrize('s_grid, window', [(np.array([0.0, np.nan, 2.0]), 2),
                                            (np.arange(5.0), 0)])
def test_create_time_segments_rejects_bad_input(s_grid, window):
    with pytest.raises(ValueError):
        create_time_segments(s_grid, window)


def test_time_windows_have_speed_dependent_length(ablation_runs):
    """
    Median moving speed is 10 m/s, so the windows last 10 s: 40 m at 4 m/s,
    100 m at 10 m/s, 200 m at 20 m/s - while 100 m segments stay ~100 m.
    """
    run = ablation_runs['time']
    details = run['meta']['ablations']['segmentation_time']
    windows = run['segments']

    assert details['median_moving_speed_mps'] == pytest.approx(10.0, rel=0.01)
    assert details['window_samples'] == round(100.0 / details['median_moving_speed_mps'] * FS)
    assert details['window_s'] == pytest.approx(details['window_samples'] / FS)

    assert list(windows['seg_id']) == list(range(len(windows)))
    full = windows[~windows['partial']]
    assert (full['n_samples'] == details['window_samples']).all()
    # Only the tail window is partial, however short a slow window is in metres
    assert list(windows['partial']) == [False] * (len(windows) - 1) + [True]
    assert full['length_m'].min() == pytest.approx(40.0, abs=1.0)
    assert full['length_m'].max() == pytest.approx(200.0, abs=1.0)

    distance = ablation_runs['default']['segments']
    interior = distance[~distance['partial']]['length_m']
    assert interior.min() > 99.0 and interior.max() <= 100.0


def test_time_window_geometry_follows_the_window_extent(ablation_runs):
    """The drive is due north, so a vertex latitude maps straight back to s."""
    run = ablation_runs['time']
    windows = run['segments']
    features = run['geojson']['features']

    assert len(features) == len(windows)
    for (_, row), feature in zip(windows.iterrows(), features):
        assert feature['properties']['seg_id'] == row['seg_id']
        assert feature['properties']['length_m'] == pytest.approx(row['length_m'])
        coords = feature['geometry']['coordinates']
        assert feature['geometry']['type'] == 'LineString'
        s_first = (coords[0][1] - LAT0) * METERS_PER_DEG_LAT
        s_last = (coords[-1][1] - LAT0) * METERS_PER_DEG_LAT
        assert s_first == pytest.approx(row['s_start'], abs=0.01)
        # The exporter stops one sample before s_end (s < s_end)
        assert row['s_end'] - 0.25 <= s_last < row['s_end']


def test_time_segmentation_ablation_is_recorded(ablation_runs):
    report = ablation_runs['time']['report']

    assert set(ablation_runs['time']['meta']['ablations']) == {'segmentation_time'}
    assert '`--ablate-segmentation-time`' in report
    assert 'ABLATION: fixed time windows of 1000 samples (10.000 s)' in report
    assert 'Segments (ABLATION, 10.000 s time windows)' in report
    assert '- Segment length: 100 m' not in report


def test_time_segmentation_without_motion_fails_loud(drive_csv, tmp_path):
    """No moving samples -> no window length can be derived; nothing is written."""
    csv_path = drive_csv('parked.csv', duration_s=20.0, speed_mps=0.0)
    out_dir = tmp_path / 'out'

    with pytest.raises(ValueError, match='moving samples'):
        run_analyze(csv_path, out_dir, ablate_segmentation_time=True)
    assert not out_dir.exists()


# --- Speed-gate ablation ------------------------------------------------------

@pytest.mark.parametrize('speed_mps', [4.0, 30.0])  # 14.4 and 108 km/h
def test_speed_gate_off_evaluates_iri_multi_outside_the_survey_range(speed_mps):
    n = 2000
    s_grid = speed_mps * np.arange(n) / FS
    signal = 0.01 * np.sin(2 * np.pi * 2.0 * np.arange(n) / FS)
    common = dict(seg_id=0, indices=np.arange(n), a_vertical_g=signal,
                  a_vertical_g_psd=signal, v_grid=np.full(n, speed_mps),
                  s_grid=s_grid, fs=FS)

    gated = aggregate_segment_metrics(**common)
    ungated = aggregate_segment_metrics(**common, speed_gate=False)

    assert gated['speed_valid'] is False and ungated['speed_valid'] is False
    for column in ('iri_multi', 'iri_multi_vehicle', 'iri_multi_raw'):
        assert np.isnan(gated[column])
        assert np.isfinite(ungated[column])
    assert ungated['iri_multi'] == compute_iri_multi(
        ungated['grms'], ungated['mean_speed_kmh'], vehicle_type=VehicleType.GENERIC,
        **IRI_MULTI_DEFAULT_PARAMS)
    assert ungated['low_speed_class'] == gated['low_speed_class']
    assert ungated['needs_class12_survey'] == gated['needs_class12_survey']


def test_speed_gate_ablation_fills_only_the_gated_segments(ablation_runs):
    default = ablation_runs['default']['segments']
    gate = ablation_runs['gate']['segments']
    outside = ~default['speed_valid']

    assert outside.any(), 'the drive must hold a segment below 20 km/h'
    # The validity and low-speed columns keep their true values
    for column in ('seg_id', 'speed_valid', 'low_speed_class', 'needs_class12_survey', 'grms'):
        pd.testing.assert_series_equal(gate[column], default[column])
    for column in ('iri_multi', 'iri_multi_vehicle', 'iri_multi_raw'):
        assert default.loc[outside, column].isna().all()
        assert gate.loc[outside, column].notna().all()
        pd.testing.assert_series_equal(gate.loc[~outside, column], default.loc[~outside, column])

    # The GeoJSON carries the numbers too (null only where the gate is on)
    by_id = {f['properties']['seg_id']: f['properties'] for f in
             ablation_runs['gate']['geojson']['features']}
    for seg_id in default.loc[outside, 'seg_id']:
        assert by_id[seg_id]['iri_multi'] is not None


def test_speed_gate_ablation_is_recorded(ablation_runs):
    run = ablation_runs['gate']
    outside = int((~run['segments']['speed_valid']).sum())

    assert run['meta']['ablations'] == {
        'speed_gate': {'n_segments_outside_speed_valid': outside}}
    assert '`--ablate-speed-gate`' in run['report']
    assert 'ABLATION: `iri_multi` is computed outside it too' in run['report']
    assert "`iri_multi` is NaN outside it" not in run['report']


# --- All switches together ----------------------------------------------------

def test_all_ablations_are_recorded_together_as_strict_json(ablation_runs):
    run = ablation_runs['all']

    assert list(run['meta']['ablations']) == ['orientation', 'segmentation_time', 'speed_gate']
    for flag in ('--ablate-orientation', '--ablate-segmentation-time', '--ablate-speed-gate'):
        assert f'`{flag}`' in run['report']
    # Strict JSON: no bare NaN token anywhere (null-not-NaN)
    text = (run['out'] / 'recording_meta.json').read_text(encoding='utf-8')
    json.loads(text, parse_constant=lambda token: pytest.fail(f'non-finite JSON: {token}'))


def test_speed_gate_ablation_rejects_the_ignore_policy(tmp_path):
    """'ignore' would delete the very segments the gate ablation gives numbers to."""
    from road_quality_analyzer.cli import analyze
    with pytest.raises(ValueError, match='ignore'):
        analyze(str(tmp_path / 'missing.csv'), str(tmp_path / 'out'),
                low_speed_policy='ignore', ablate_speed_gate=True)
    assert not (tmp_path / 'out').exists()

"""
Tests for the low-speed segment policy.

A road so bad that it cannot be driven faster than ~20 km/h produces the LEAST
valid accelerometer IRI exactly where the road is worst: the excitation frequency
v/wavelength drops out of the 0.5-6 Hz band and Eq.4/5/6 are calibrated at
30/50/80 km/h only. The policy therefore labels such segments instead of
reporting a number, and the invariant pinned everywhere below is that no policy
ever turns a low-speed segment into a numeric IRI_multi.
"""

import contextlib
import io
import json

import numpy as np
import pandas as pd
import pytest

from road_quality_analyzer.artifacts import LOW_SPEED_COLOR, LOW_SPEED_LEGEND_LABEL
from road_quality_analyzer.cli import analyze
from road_quality_analyzer.segmentation.segment_100m import (
    LOW_SPEED_CLASS_BY_POLICY,
    LOW_SPEED_MAX_KMH,
    NORMAL_SPEED_CLASS,
    aggregate_segment_metrics,
    create_segments_dataframe,
)
from tests.conftest import write_drive_csv

FS = 100.0

# 3 m/s = 10.8 km/h: a road that cannot be driven faster than walking pace
LOW_SPEED_MPS = 3.0
NORMAL_SPEED_MPS = 15.0  # 54 km/h, inside the 20-100 km/h survey range

POLICIES = ('very-poor', 'poor', 'invalid', 'ignore')


def segment_metrics(
    *,
    speed_mps: float,
    n: int = 1000,
    anomaly_mask: np.ndarray = None,
    low_speed_policy: str = 'invalid',
    n_indices: int = None,
):
    """Metrics of one synthetic constant-speed segment."""
    t_grid = np.arange(n) / FS
    s_grid = speed_mps * t_grid
    v_grid = np.full(n, speed_mps)
    a_vertical_g = np.zeros(n)

    return aggregate_segment_metrics(
        seg_id=0,
        indices=np.arange(n if n_indices is None else n_indices),
        a_vertical_g=a_vertical_g,
        a_vertical_g_psd=a_vertical_g,
        v_grid=v_grid,
        s_grid=s_grid,
        fs=FS,
        anomaly_mask=anomaly_mask,
        low_speed_policy=low_speed_policy,
    )


# --- Detection ----------------------------------------------------------------

def test_low_speed_is_detected_below_20_kmh():
    metrics = segment_metrics(speed_mps=LOW_SPEED_MPS)

    assert metrics['mean_speed_kmh'] == pytest.approx(10.8)
    assert metrics['needs_class12_survey'] is True
    assert metrics['low_speed_class'] == 'invalid'


def test_normal_survey_speed_is_not_low_speed():
    metrics = segment_metrics(speed_mps=NORMAL_SPEED_MPS)

    assert metrics['speed_valid'] is True
    assert metrics['needs_class12_survey'] is False
    assert metrics['low_speed_class'] == NORMAL_SPEED_CLASS


def test_above_the_survey_range_is_speed_invalid_but_not_low_speed():
    """> 100 km/h is plain speed-invalid: it is fast, not a Class 1/2 candidate."""
    metrics = segment_metrics(speed_mps=30.0)  # 108 km/h

    assert metrics['speed_valid'] is False
    assert metrics['needs_class12_survey'] is False
    assert metrics['low_speed_class'] == NORMAL_SPEED_CLASS
    assert np.isnan(metrics['iri_multi'])


def test_threshold_sits_at_20_kmh():
    """19.8 km/h is low-speed, 20.16 km/h is not."""
    assert LOW_SPEED_MAX_KMH == 20.0

    below = segment_metrics(speed_mps=5.5)   # 19.8 km/h
    above = segment_metrics(speed_mps=5.6)   # 20.16 km/h

    assert below['needs_class12_survey'] is True
    assert above['needs_class12_survey'] is False


def test_exactly_the_threshold_speed_is_not_low_speed():
    """The boundary is strict: 20.00 km/h is the first speed inside the survey range."""
    metrics = segment_metrics(speed_mps=LOW_SPEED_MAX_KMH / 3.6)

    assert metrics['mean_speed_kmh'] == LOW_SPEED_MAX_KMH
    assert metrics['speed_valid'] is True
    assert metrics['needs_class12_survey'] is False
    assert metrics['low_speed_class'] == NORMAL_SPEED_CLASS


# --- Policy matrix ------------------------------------------------------------

@pytest.mark.parametrize('policy', POLICIES)
def test_policy_labels_the_low_speed_segment(policy):
    metrics = segment_metrics(speed_mps=LOW_SPEED_MPS, low_speed_policy=policy)

    assert metrics['low_speed_class'] == LOW_SPEED_CLASS_BY_POLICY[policy]
    assert metrics['needs_class12_survey'] is True


@pytest.mark.parametrize('policy', POLICIES)
def test_no_policy_fabricates_a_numeric_iri_multi(policy):
    """Labels only: Eq.4/5/6 stay uncalibrated below 20 km/h under every policy."""
    metrics = segment_metrics(speed_mps=LOW_SPEED_MPS, low_speed_policy=policy)

    assert np.isnan(metrics['iri_multi'])


@pytest.mark.parametrize('policy', POLICIES)
def test_policy_never_relabels_a_normal_segment(policy):
    metrics = segment_metrics(speed_mps=NORMAL_SPEED_MPS, low_speed_policy=policy)

    assert metrics['low_speed_class'] == NORMAL_SPEED_CLASS
    assert metrics['needs_class12_survey'] is False


def test_unknown_policy_is_rejected():
    with pytest.raises(ValueError, match='low_speed_policy'):
        segment_metrics(speed_mps=LOW_SPEED_MPS, low_speed_policy='optimistic')


# --- events_per_km ------------------------------------------------------------

def test_events_per_km_over_a_known_length():
    """5 events on exactly 100 m -> 50 events/km."""
    n = 1001  # 10 m/s * 10.00 s = exactly 100.0 m
    anomaly_mask = np.zeros(n, dtype=bool)
    anomaly_mask[[10, 200, 400, 600, 800]] = True

    metrics = segment_metrics(speed_mps=10.0, n=n, anomaly_mask=anomaly_mask)

    assert metrics['length_m'] == pytest.approx(100.0)
    assert metrics['anomaly_count'] == 5
    assert metrics['events_per_km'] == pytest.approx(50.0)


def test_events_per_km_is_zero_on_a_clean_segment():
    metrics = segment_metrics(speed_mps=NORMAL_SPEED_MPS)

    assert metrics['events_per_km'] == pytest.approx(0.0)


def test_events_per_km_is_reported_for_low_speed_segments_too():
    """The threshold detector still works below 20 km/h: events replace IRI there."""
    n = 1001
    anomaly_mask = np.zeros(n, dtype=bool)
    anomaly_mask[[100, 500]] = True

    metrics = segment_metrics(speed_mps=LOW_SPEED_MPS, n=n, anomaly_mask=anomaly_mask)

    assert metrics['needs_class12_survey'] is True
    assert np.isnan(metrics['iri_multi'])
    # 3 m/s * 10.00 s = 30.0 m -> 2 / 0.030 km
    assert metrics['length_m'] == pytest.approx(30.0)
    assert metrics['events_per_km'] == pytest.approx(2 / 0.030)


def test_events_per_km_guards_a_zero_length_segment():
    """
    A one-sample segment has no length: NaN, never a division by zero.

    The sample carries an anomaly on purpose - with a zero event count the
    unguarded 0/0 would land on NaN by accident and hide a missing guard, while
    1/0 lands on +inf, which would then be serialized as null and silently read
    back as 'no measurement' instead of 'no length'.
    """
    anomaly_mask = np.zeros(400, dtype=bool)
    anomaly_mask[0] = True

    metrics = segment_metrics(speed_mps=LOW_SPEED_MPS, n=400, n_indices=1,
                              anomaly_mask=anomaly_mask)

    assert metrics['length_m'] == pytest.approx(0.0)
    assert metrics['anomaly_count'] == 1
    assert np.isnan(metrics['events_per_km'])
    assert not np.isinf(metrics['events_per_km'])


# --- DataFrame assembly -------------------------------------------------------

def test_dataframe_threads_the_policy_into_every_segment():
    n = 2500
    speed_mps = 4.0  # 14.4 km/h
    s_grid = speed_mps * np.arange(n) / FS
    v_grid = np.full(n, speed_mps)
    a_vertical_g = np.zeros(n)

    df = create_segments_dataframe(
        s_grid, a_vertical_g, a_vertical_g, v_grid, FS,
        low_speed_policy='very-poor',
    )

    assert (df['low_speed_class'] == 'very_poor').all()
    assert df['needs_class12_survey'].all()
    assert df['iri_multi'].isna().all()
    assert 'events_per_km' in df.columns


# --- End to end ---------------------------------------------------------------

def run_analyze(input_path: str, output_dir, **kwargs) -> str:
    """analyze() with the Cyrillic progress log captured in memory."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        analyze(input_path, str(output_dir), **kwargs)
    return buffer.getvalue()


@pytest.fixture(scope='module')
def low_speed_csv(tmp_path_factory):
    """60 s at 3 m/s = 180 m of road nobody can drive faster than 10.8 km/h."""
    base = tmp_path_factory.mktemp('low_speed')
    return write_drive_csv(
        base / 'crawl.csv',
        duration_s=60.0,
        speed_mps=LOW_SPEED_MPS,
        a_vert=lambda t: 0.4 * np.sin(2 * np.pi * 2.3 * t),
    )


@pytest.fixture(scope='module')
def runs_by_policy(low_speed_csv, tmp_path_factory):
    """One analyze() pass per policy over the same low-speed recording."""
    base = tmp_path_factory.mktemp('policies')
    runs = {}
    for policy in POLICIES:
        out_dir = base / policy
        log = run_analyze(low_speed_csv, out_dir, low_speed_policy=policy)
        runs[policy] = {
            'out': out_dir,
            'log': log,
            'segments': pd.read_csv(out_dir / 'road_segments.csv'),
            'report': (out_dir / 'report.md').read_text(encoding='utf-8'),
            'geojson': json.loads(
                (out_dir / 'roughness.geojson').read_text(encoding='utf-8')
            ),
        }
    return runs


@pytest.mark.parametrize('policy', ('very-poor', 'poor', 'invalid'))
def test_labelling_policies_keep_the_rows_with_their_label(runs_by_policy, policy):
    df = runs_by_policy[policy]['segments']

    assert len(df) > 0
    assert df['needs_class12_survey'].all()
    assert (df['low_speed_class'] == LOW_SPEED_CLASS_BY_POLICY[policy]).all()


@pytest.mark.parametrize('policy', ('very-poor', 'poor', 'invalid'))
def test_no_policy_writes_a_numeric_iri_multi_for_a_low_speed_segment(
        runs_by_policy, policy):
    df = runs_by_policy[policy]['segments']
    assert df['iri_multi'].isna().all()

    for feature in runs_by_policy[policy]['geojson']['features']:
        assert feature['properties']['iri_multi'] is None
        assert feature['properties']['needs_class12_survey'] is True
        assert feature['properties']['low_speed_class'] == LOW_SPEED_CLASS_BY_POLICY[policy]
        assert feature['properties']['events_per_km'] is not None


def test_default_policy_is_invalid(low_speed_csv, tmp_path):
    """analyze() called without a policy must behave like --low-speed-policy invalid."""
    run_analyze(low_speed_csv, tmp_path / 'default')
    df = pd.read_csv(tmp_path / 'default' / 'road_segments.csv')

    assert (df['low_speed_class'] == 'invalid').all()


def test_ignore_policy_drops_the_rows_from_csv_and_geojson(runs_by_policy):
    run = runs_by_policy['ignore']

    assert len(run['segments']) == 0
    assert run['geojson']['features'] == []


def test_ignore_policy_still_counts_the_segments_in_the_report(runs_by_policy):
    """Excluded from the artifacts, never from the accounting."""
    excluded = runs_by_policy['ignore']['report']
    kept = runs_by_policy['invalid']['segments']

    assert 'ignore' in excluded
    assert f'{len(kept)}' in excluded
    assert 'виключено' in excluded


@pytest.mark.parametrize('policy', POLICIES)
def test_report_documents_the_low_speed_section(runs_by_policy, policy):
    report = runs_by_policy[policy]['report']

    assert 'Сегменти з низькою швидкістю' in report
    assert f'{policy}' in report
    # The rationale: frequency band, calibration range, Class 1/2 survey
    assert '0.5' in report and '6' in report
    assert '20' in report and '100' in report
    assert 'клас 1/2' in report
    assert 'events_per_km' in report


def test_report_lists_each_low_speed_segment(runs_by_policy):
    report = runs_by_policy['invalid']['report']
    df = runs_by_policy['invalid']['segments']

    for seg_id in df['seg_id']:
        assert f'| {seg_id} |' in report


def test_a_wholly_low_speed_recording_still_produces_every_artifact(runs_by_policy):
    """
    The worst-road case: nothing in the drive ever cleared 20 km/h. Every segment
    is a Class 1/2 candidate, and the run must still yield a full artifact set -
    an empty or missing map here would hide exactly the road that matters most.
    """
    run = runs_by_policy['invalid']
    df = run['segments']

    assert len(df) > 0
    assert df['needs_class12_survey'].all()
    assert df['iri_multi'].isna().all()
    assert df['events_per_km'].notna().all()

    for name in ('road_segments.csv', 'roughness.geojson', 'events.geojson',
                 'segments_map.html', 'report.md'):
        assert (run['out'] / name).stat().st_size > 0
    assert list((run['out'] / 'plots').glob('*.png'))

    assert len(run['geojson']['features']) == len(df)

    html = (run['out'] / 'segments_map.html').read_text(encoding='utf-8')
    assert LOW_SPEED_COLOR in html
    assert LOW_SPEED_LEGEND_LABEL in html


def test_ignore_policy_leaves_a_valid_empty_featurecollection(runs_by_policy):
    """Excluding every row must not degrade the GeoJSON into unparsable output."""
    path = runs_by_policy['ignore']['out'] / 'roughness.geojson'

    def reject_constant(token):
        raise AssertionError(f'GeoJSON contains the non-standard JSON constant {token!r}')

    document = json.loads(path.read_text(encoding='utf-8'),
                          parse_constant=reject_constant)

    assert document['type'] == 'FeatureCollection'
    assert document['features'] == []


def test_ignore_policy_keeps_the_csv_columns(runs_by_policy):
    """A zero-row export still has to carry the schema, header included."""
    columns = runs_by_policy['ignore']['segments'].columns

    assert list(columns) == list(runs_by_policy['invalid']['segments'].columns)
    for column in ('low_speed_class', 'needs_class12_survey', 'events_per_km'):
        assert column in columns


def test_ignore_policy_draws_neither_magenta_nor_the_legend(runs_by_policy):
    """No excluded row reaches the map, so its colour and legend must be absent."""
    html = (runs_by_policy['ignore']['out'] / 'segments_map.html').read_text(
        encoding='utf-8')

    assert LOW_SPEED_COLOR not in html
    assert LOW_SPEED_LEGEND_LABEL not in html


def test_normal_recording_reports_no_low_speed_segments(drive_csv, tmp_path):
    csv_path = drive_csv(duration_s=40.0, speed_mps=NORMAL_SPEED_MPS)
    run_analyze(csv_path, tmp_path / 'out')
    df = pd.read_csv(tmp_path / 'out' / 'road_segments.csv')

    assert not df['needs_class12_survey'].any()
    assert (df['low_speed_class'] == NORMAL_SPEED_CLASS).all()
    assert df['events_per_km'].notna().all()

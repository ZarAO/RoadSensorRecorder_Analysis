"""
Unit tests for distance-based 100 m segmentation.
"""

import numpy as np
import pandas as pd
import pytest

from road_quality_analyzer.metrics.grms import compute_grms
from road_quality_analyzer.metrics.iri import (
    IRI_MULTI_DEFAULT_PARAMS,
    VehicleType,
    compute_iri_multi,
)
from road_quality_analyzer.segmentation.segment_100m import (
    aggregate_segment_metrics,
    create_segments,
    create_segments_dataframe,
    longest_finite_run,
)

FS = 100.0


def uniform_drive(n: int, speed_mps: float = 15.0, signal: np.ndarray = None):
    """(t_grid, s_grid, v_grid, a_vertical_g) for a constant-speed drive."""
    t_grid = np.arange(n) / FS
    s_grid = speed_mps * t_grid
    v_grid = np.full(n, speed_mps)
    a_vertical_g = np.zeros(n) if signal is None else signal
    return t_grid, s_grid, v_grid, a_vertical_g


def metrics_for(indices, n, speed_mps=15.0, signal=None, signal_psd=None):
    _, s_grid, v_grid, a = uniform_drive(n, speed_mps, signal)
    return aggregate_segment_metrics(
        seg_id=0, indices=indices, a_vertical_g=a,
        a_vertical_g_psd=a if signal_psd is None else signal_psd,
        v_grid=v_grid, s_grid=s_grid, fs=FS,
    )


# --- seg_id boundaries --------------------------------------------------------

def test_seg_id_boundary_floor_s_over_100():
    """seg_id = floor(s/100): s = 100.0 belongs to segment 1, not 0."""
    s_grid = np.array([0.0, 99.999, 100.0, 199.9])

    segments = create_segments(s_grid, segment_length_m=100.0)

    assert sorted(segments) == [0, 1]
    np.testing.assert_array_equal(segments[0], [0, 1])
    np.testing.assert_array_equal(segments[1], [2, 3])


def test_segments_are_distance_based_not_time_based():
    """Halving the speed halves the segment count over the same duration."""
    n = 2000
    fast = create_segments(uniform_drive(n, speed_mps=20.0)[1])
    slow = create_segments(uniform_drive(n, speed_mps=10.0)[1])

    assert len(fast) == 4   # 400 m
    assert len(slow) == 2   # 200 m


def test_non_finite_distance_is_rejected_instead_of_becoming_a_phantom_segment():
    """floor(NaN).astype(int) yields INT_MIN: fail loud, never emit a garbage seg_id."""
    s_grid = np.array([0.0, 50.0, np.nan, 150.0])

    with pytest.raises(ValueError, match='non-finite'):
        create_segments(s_grid)


# --- Welch guard: n >= fs*2 ---------------------------------------------------

def test_short_segment_below_fs_times_two_yields_nan_iri():
    """Under 2 s of signal the PSD is not computable: NaN, never a fabricated 0."""
    metrics = metrics_for(np.arange(100), n=400)

    assert np.isnan(metrics['iri_psd_raw'])
    assert np.isnan(metrics['iri_psd'])
    assert np.isnan(metrics['psd_band_power'])
    assert metrics['psd_n_samples_used'] == 100


def test_segment_at_or_above_fs_times_two_yields_finite_iri():
    """Exactly fs*2 samples is enough for Welch."""
    n = 400
    t = np.arange(n) / FS
    signal = 0.02 * np.sin(2 * np.pi * 2.0 * t)

    metrics = metrics_for(np.arange(200), n=n, signal=signal)

    assert np.isfinite(metrics['iri_psd_raw'])
    assert np.isfinite(metrics['psd_band_power'])
    assert metrics['psd_n_samples_used'] == 200


# --- Distress removal: no splicing across the removed windows -----------------

def test_longest_finite_run_picks_the_longest_clean_block():
    signal = np.array([1.0, 2.0, np.nan, 3.0, 4.0, 5.0, np.nan, 6.0])

    np.testing.assert_array_equal(longest_finite_run(signal), [3.0, 4.0, 5.0])


def test_psd_uses_the_clean_run_while_grms_keeps_the_whole_segment():
    """The distress mask belongs to the PSD input only; Grms sees the raw segment."""
    n = 700
    t = np.arange(n) / FS
    signal = 0.02 * np.sin(2 * np.pi * 2.0 * t)
    # 100 masked samples at the head: the clean run is the remaining 600
    psd_input = signal.copy()
    psd_input[:100] = np.nan

    metrics = metrics_for(np.arange(n), n=n, signal=signal, signal_psd=psd_input)

    assert metrics['psd_n_samples_used'] == 600
    assert np.isfinite(metrics['iri_psd_raw'])
    assert metrics['grms'] == pytest.approx(compute_grms(signal))


def test_welch_runs_on_one_clean_run_not_on_spliced_chunks():
    """Two short clean runs must not be butted together to clear the fs*2 guard."""
    n = 400
    t = np.arange(n) / FS
    signal = 0.02 * np.sin(2 * np.pi * 2.0 * t)
    # 150 clean + NaN + 150 clean: spliced that is 300 samples (>= fs*2), the
    # longest single run is only 150
    psd_input = signal.copy()
    psd_input[150:250] = np.nan

    metrics = metrics_for(np.arange(n), n=n, signal=signal, signal_psd=psd_input)

    assert metrics['psd_n_samples_used'] == 150
    assert np.isnan(metrics['iri_psd_raw'])


# --- Metric wiring ------------------------------------------------------------

def test_grms_and_iri_multi_consistent_for_known_signal():
    """Grms feeds Eq.6 in g, and the speed argument is km/h, not m/s."""
    n = 1000
    t = np.arange(n) / FS
    signal = 0.02 * np.sin(2 * np.pi * 2.0 * t)

    metrics = metrics_for(np.arange(n), n=n, speed_mps=15.0, signal=signal)

    assert metrics['grms'] == pytest.approx(0.02 / np.sqrt(2), rel=0.01)
    assert metrics['grms'] == pytest.approx(compute_grms(signal))
    assert metrics['mean_speed_kmh'] == pytest.approx(54.0)
    assert metrics['iri_multi'] == pytest.approx(compute_iri_multi(
        metrics['grms'], 54.0,
        vehicle_type=VehicleType.GENERIC, **IRI_MULTI_DEFAULT_PARAMS
    ))


def test_iri_multi_is_nan_outside_the_survey_speed_range():
    """Eq.4-6 carry a speed term and are not calibrated below 20 km/h: NaN, not 0."""
    metrics = metrics_for(np.arange(400), n=400, speed_mps=2.0)

    assert metrics['mean_speed_kmh'] == pytest.approx(7.2)
    assert not metrics['speed_valid']
    assert np.isnan(metrics['iri_multi'])


def test_iri_psd_is_not_gated_by_the_survey_speed_range():
    """Eq.3 has no speed term: iri_psd == max(0, iri_psd_raw) whatever the speed."""
    metrics = metrics_for(np.arange(400), n=400, speed_mps=2.0)

    assert not metrics['speed_valid']
    assert np.isfinite(metrics['iri_psd_raw'])
    assert metrics['iri_psd'] == pytest.approx(max(0.0, metrics['iri_psd_raw']))


def test_dx_le_03_share_reflects_spatial_sampling():
    """dx = v/fs; at 40 m/s and 100 Hz every sample is 0.4 m apart (non-compliant)."""
    compliant = metrics_for(np.arange(400), n=400, speed_mps=15.0)
    coarse = metrics_for(np.arange(400), n=400, speed_mps=40.0)

    assert compliant['dx_le_03_share'] == pytest.approx(1.0)
    assert coarse['dx_le_03_share'] == pytest.approx(0.0)


# --- DataFrame assembly -------------------------------------------------------

def test_create_segments_dataframe_flags_partial_tail():
    """250 m -> two full segments and a 50 m tail flagged partial."""
    n = 2500
    _, s_grid, v_grid, a = uniform_drive(n, speed_mps=10.0)

    df = create_segments_dataframe(s_grid, a, a, v_grid, FS)

    assert list(df['seg_id']) == [0, 1, 2]
    assert list(df['partial']) == [False, False, True]
    assert df['s_start'].iloc[1] == pytest.approx(100.0, abs=0.2)


def test_create_segments_dataframe_is_ordered_by_seg_id():
    """np.unique ordering keeps two runs on the same CSV byte-identical."""
    n = 2500
    _, s_grid, v_grid, a = uniform_drive(n, speed_mps=10.0)

    df = create_segments_dataframe(s_grid, a, a, v_grid, FS)

    assert df['seg_id'].is_monotonic_increasing

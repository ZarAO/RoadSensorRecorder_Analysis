"""
Unit tests for threshold anomaly detection and distress-window removal.
"""

import numpy as np
import pytest

from road_quality_analyzer.anomaly.threshold import (
    detect_threshold_anomalies,
    remove_distress_windows,
)

FS = 100.0


# --- Threshold ----------------------------------------------------------------

def test_threshold_uses_absolute_value():
    """A pothole shows up as a negative excursion just as often as a positive one."""
    a_vertical = np.array([-12.0, 12.0, -8.0, 8.0])

    np.testing.assert_array_equal(
        detect_threshold_anomalies(a_vertical, threshold_ms2=10.0),
        [True, True, False, False],
    )


def test_threshold_is_strictly_greater():
    a_vertical = np.array([9.999, 10.0, 10.001])

    np.testing.assert_array_equal(
        detect_threshold_anomalies(a_vertical, threshold_ms2=10.0),
        [False, False, True],
    )


def test_threshold_operates_in_ms2_not_g():
    """The unit contract: thresholds are m/s^2, so a signal in g never trips 10."""
    a_vertical_g = np.array([1.5, -2.0, 0.5])

    assert not detect_threshold_anomalies(a_vertical_g, threshold_ms2=10.0).any()


# --- Distress-window removal --------------------------------------------------

def test_remove_distress_windows_masks_plus_minus_half_second():
    signal = np.ones(1000)
    anomaly_mask = np.zeros(1000, dtype=bool)
    anomaly_mask[500] = True

    cleaned = remove_distress_windows(signal, anomaly_mask, FS, window_sec=0.5)

    assert np.all(np.isnan(cleaned[450:551]))       # +-50 samples, inclusive
    assert np.isfinite(cleaned[449])
    assert np.isfinite(cleaned[551])
    assert int(np.sum(~np.isfinite(cleaned))) == 101


def test_remove_distress_windows_clips_at_array_edges():
    n = 300
    signal = np.ones(n)
    anomaly_mask = np.zeros(n, dtype=bool)
    anomaly_mask[[0, n - 1]] = True

    cleaned = remove_distress_windows(signal, anomaly_mask, FS, window_sec=0.5)

    assert len(cleaned) == n
    assert np.all(np.isnan(cleaned[:51]))
    assert np.all(np.isnan(cleaned[n - 51:]))
    assert np.all(np.isfinite(cleaned[51:n - 51]))


def test_remove_distress_windows_does_not_mutate_input():
    signal = np.ones(500)
    anomaly_mask = np.zeros(500, dtype=bool)
    anomaly_mask[250] = True

    remove_distress_windows(signal, anomaly_mask, FS, window_sec=0.5)

    assert np.all(np.isfinite(signal))


def test_remove_distress_windows_is_a_no_op_without_anomalies():
    signal = np.linspace(0.0, 1.0, 200)

    cleaned = remove_distress_windows(signal, np.zeros(200, dtype=bool), FS)

    np.testing.assert_array_equal(cleaned, signal)


def test_overlapping_distress_windows_merge():
    signal = np.ones(1000)
    anomaly_mask = np.zeros(1000, dtype=bool)
    anomaly_mask[[500, 520]] = True

    cleaned = remove_distress_windows(signal, anomaly_mask, FS, window_sec=0.5)

    assert np.all(np.isnan(cleaned[450:571]))
    assert np.isfinite(cleaned[449])
    assert np.isfinite(cleaned[571])


def test_masked_samples_must_be_dropped_before_welch():
    """
    The NaN windows propagate: a single NaN turns Grms and Welch into NaN.

    Documents why segmentation filters with np.isfinite before computing the PSD.
    """
    from road_quality_analyzer.metrics.grms import compute_grms
    from road_quality_analyzer.metrics.iri import compute_psd_band_power

    signal = np.ones(1000) * 0.01
    anomaly_mask = np.zeros(1000, dtype=bool)
    anomaly_mask[500] = True
    cleaned = remove_distress_windows(signal, anomaly_mask, FS, window_sec=0.5)

    assert np.isnan(compute_grms(cleaned))
    assert np.isnan(compute_psd_band_power(cleaned, FS)[0])

    kept = cleaned[np.isfinite(cleaned)]
    assert np.isfinite(compute_grms(kept))
    assert np.isfinite(compute_psd_band_power(kept, FS)[0])

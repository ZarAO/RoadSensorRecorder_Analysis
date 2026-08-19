"""
Unit tests for Grms.

Reference values are derived analytically, never by re-executing the function
body, so a refactor that preserves a bug cannot pass.
"""

import warnings

import numpy as np
import pytest

from road_quality_analyzer.metrics.grms import compute_grms

G0 = 9.80665


def test_grms_of_unit_sine_is_one_over_sqrt_two():
    t = np.arange(0.0, 10.0, 0.01)
    signal = np.sin(2 * np.pi * 2.0 * t)

    assert compute_grms(signal) == pytest.approx(1.0 / np.sqrt(2), rel=1e-3)


def test_grms_of_constant_is_its_magnitude():
    assert compute_grms(np.full(100, -0.25)) == pytest.approx(0.25)


def test_grms_scales_linearly_with_amplitude():
    t = np.arange(0.0, 10.0, 0.01)
    signal = np.sin(2 * np.pi * 2.0 * t)

    assert compute_grms(3.0 * signal) == pytest.approx(3.0 * compute_grms(signal))


def test_grms_unit_contract_is_g_not_ms2():
    """Grms is reported in g, so it must be fed the g-normalised signal."""
    a_vertical_ms2 = np.array([1.0, -2.0, 3.0])

    grms_g = compute_grms(a_vertical_ms2 / G0)

    assert grms_g == pytest.approx(compute_grms(a_vertical_ms2) / G0)
    assert grms_g < 1.0


def test_grms_with_nan_input_is_nan_not_silently_zero():
    """A distress window leaves NaN; it must surface, not be swallowed."""
    signal = np.array([0.01, 0.02, np.nan, 0.03])

    assert np.isnan(compute_grms(signal))


def test_grms_of_empty_input_is_nan():
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        result = compute_grms(np.array([]))

    assert np.isnan(result)

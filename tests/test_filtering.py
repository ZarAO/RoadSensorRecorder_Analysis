"""
Unit tests for the 0.5-6 Hz band-pass.

Reference values are analytic properties of a zero-phase Butterworth: filtfilt
runs the filter forwards and backwards, so the band edges come out at half
amplitude (the -3 dB point squared) and the pass band carries no group delay.
"""

import numpy as np
import pytest
from scipy.signal import butter, lfilter

from road_quality_analyzer.filtering import apply_bandpass

FS = 100.0
F_LOW, F_HIGH = 0.5, 6.0
# Ignore the filtfilt start-up region when measuring a steady-state gain
SETTLED = slice(500, -500)


def sine(freq_hz: float, duration_s: float = 20.0, amplitude: float = 1.0):
    t = np.arange(0.0, duration_s, 1.0 / FS)
    return amplitude * np.sin(2 * np.pi * freq_hz * t)


def gain_at(freq_hz: float) -> float:
    """Steady-state amplitude ratio of the filter at one frequency."""
    signal = sine(freq_hz)
    filtered = apply_bandpass(signal, FS, F_LOW, F_HIGH)
    return float(np.std(filtered[SETTLED]) / np.std(signal[SETTLED]))


# --- Band shape ---------------------------------------------------------------

def test_pass_band_component_survives_with_unit_gain():
    """A 2 Hz road component sits in the middle of the band and must come out intact."""
    signal = sine(2.0)

    filtered = apply_bandpass(signal, FS, F_LOW, F_HIGH)

    assert filtered[SETTLED] == pytest.approx(signal[SETTLED], abs=0.01)
    assert gain_at(2.0) == pytest.approx(1.0, rel=0.01)


def test_band_edges_are_at_half_amplitude():
    """
    filtfilt applies the filter twice, so the -3 dB edge becomes -6 dB (0.5).

    This pins both edges: moving f_low or f_high would shift these two gains.
    """
    assert gain_at(F_LOW) == pytest.approx(0.5, rel=0.01)
    assert gain_at(F_HIGH) == pytest.approx(0.5, rel=0.01)


def test_drift_below_the_band_is_rejected():
    """0.1 Hz is residual gravity / tilt drift, not road roughness."""
    assert gain_at(0.1) < 0.01


def test_vibration_above_the_band_is_rejected():
    """15 Hz is engine and tire vibration; it must not reach Grms or the PSD."""
    assert gain_at(15.0) < 0.01


def test_output_length_is_preserved():
    signal = sine(2.0, duration_s=7.3)

    assert len(apply_bandpass(signal, FS, F_LOW, F_HIGH)) == len(signal)


# --- Zero phase ---------------------------------------------------------------

def test_filter_is_zero_phase():
    """
    filtfilt introduces no group delay; the single-pass causal filter does.

    A delayed vertical acceleration would misplace every event against the
    distance grid, so the phase property is part of the contract.
    """
    signal = sine(2.0)

    zero_phase = apply_bandpass(signal, FS, F_LOW, F_HIGH)
    b, a = butter(4, [F_LOW / (0.5 * FS), F_HIGH / (0.5 * FS)], btype='band')
    causal = lfilter(b, a, signal)

    def best_lag(filtered):
        corr = np.correlate(filtered[SETTLED], signal[SETTLED], mode='full')
        return int(np.argmax(corr)) - (len(signal[SETTLED]) - 1)

    assert best_lag(zero_phase) == 0
    assert best_lag(causal) > 0


# --- Guards -------------------------------------------------------------------

@pytest.mark.parametrize('f_low, f_high', [
    (0.5, 50.0),    # f_high at Nyquist
    (0.5, 60.0),    # f_high above Nyquist
    (6.0, 0.5),     # inverted band
    (0.0, 6.0),     # zero low edge
    (-1.0, 6.0),    # negative low edge
])
def test_invalid_band_raises_instead_of_producing_garbage(f_low, f_high):
    with pytest.raises(ValueError, match='is not valid for fs'):
        apply_bandpass(sine(2.0), FS, f_low, f_high)


def test_input_shorter_than_the_filtfilt_padlen_raises():
    """
    padlen = 3 * (order * 2 + 1) = 27 for the 4th-order band-pass.

    cli.analyze refuses any covered window below 28 samples for exactly this
    reason, so the boundary is pinned here rather than left to SciPy.
    """
    with pytest.raises(ValueError, match='padlen'):
        apply_bandpass(np.zeros(27), FS, F_LOW, F_HIGH)

    assert len(apply_bandpass(np.zeros(28), FS, F_LOW, F_HIGH)) == 28

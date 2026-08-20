"""
Unit tests for the published IRI equations.

The coefficients are book values and must never be retuned to fit a dataset, so
they are pinned literally here rather than read back from the module under test.
"""

import numpy as np
import pytest

from road_quality_analyzer.metrics.iri import (
    IRI_MULTI_COEFFICIENTS,
    IRI_PSD_COEFFICIENTS,
    VehicleType,
    compute_iri_multi,
    compute_iri_psd,
    compute_psd_band_power,
)

FS = 100.0
G0 = 9.80665


def sine_signal(amplitude_g: float, freq_hz: float = 3.0, duration_s: float = 10.0):
    t = np.arange(0.0, duration_s, 1.0 / FS)
    return amplitude_g * np.sin(2 * np.pi * freq_hz * t)


# --- Coefficient tables -------------------------------------------------------

def test_eq3_coefficient_table_matches_published_values():
    assert IRI_PSD_COEFFICIENTS == {'A_sqrt_psd': 0.774, 'B_const': -0.825}


def test_eq4_to_eq6_coefficient_tables_match_published_values():
    assert IRI_MULTI_COEFFICIENTS[VehicleType.LEV] == {
        'grms': 55.25, 'speed_kmh': -0.07, 'npeop': 0.19,
        'stif': -2.93, 'dampf': -1.09, 'tyres': -1.44, 'const': 7.66,
    }
    assert IRI_MULTI_COEFFICIENTS[VehicleType.DSD] == {
        'grms': 54.43, 'speed_kmh': -0.06, 'npeop': 0.18,
        'stif': -0.87, 'dampf': -0.89, 'tyres': -0.27, 'const': 5.75,
    }
    assert IRI_MULTI_COEFFICIENTS[VehicleType.GENERIC] == {
        'grms': 50.32, 'speed_kmh': -0.06, 'npeop': 0.17,
        'stif': -1.86, 'dampf': -0.90, 'tyres': -0.78, 'const': 6.68,
    }


# --- Eq.3 ---------------------------------------------------------------------

def test_iri_psd_applies_published_eq3_coefficients():
    """IRI_psd_raw = 0.774 * sqrt(PSD) - 0.825, evaluated on the reported scalar."""
    signal = sine_signal(0.05)

    iri_raw, iri, debug = compute_iri_psd(signal, FS, return_debug=True)

    assert iri_raw == pytest.approx(0.774 * debug['psd_sqrt_scalar'] - 0.825)
    assert iri == pytest.approx(max(0.0, iri_raw))


def test_negative_iri_psd_raw_is_preserved_and_clipped_separately():
    """A negative raw reading is a calibration signal, not a perfect road."""
    quiet = sine_signal(1e-6)

    iri_raw, iri, _ = compute_iri_psd(quiet, FS, return_debug=True)

    assert iri_raw < 0
    assert iri_raw == pytest.approx(-0.825, abs=1e-3)
    assert iri == 0.0


def test_iri_psd_scalar_scales_with_amplitude():
    """PSD is quadratic in amplitude, so sqrt(PSD) doubles when the signal doubles."""
    _, _, single = compute_iri_psd(sine_signal(0.05), FS, return_debug=True)
    _, _, double = compute_iri_psd(sine_signal(0.10), FS, return_debug=True)

    assert double['psd_sqrt_scalar'] == pytest.approx(
        2 * single['psd_sqrt_scalar'], rel=1e-6
    )


def test_iri_psd_is_nan_when_signal_is_shorter_than_two_seconds():
    short = np.zeros(int(FS * 2) - 1)

    iri_raw, iri, debug = compute_iri_psd(short, FS, return_debug=True)

    assert np.isnan(iri_raw)
    assert np.isnan(iri)          # NaN, not the 0.0 that max(0.0, nan) would give
    assert np.isnan(debug['psd_band_power'])


def test_psd_band_power_is_nan_for_an_empty_band():
    """A band above Nyquist selects no bin: NaN, never 0."""
    scalar, debug = compute_psd_band_power(np.zeros(1000), FS, f_low=60.0, f_high=80.0)

    assert np.isnan(scalar)
    assert np.isnan(debug['psd_band_power'])
    assert debug['psd_band_n'] == 0


def test_iri_psd_unit_contract_is_g_not_ms2():
    """Eq.3 is calibrated on a signal in g; feeding m/s^2 scales sqrt(PSD) by g0."""
    signal_g = sine_signal(0.05)

    _, _, in_g = compute_iri_psd(signal_g, FS, return_debug=True)
    _, _, in_ms2 = compute_iri_psd(signal_g * G0, FS, return_debug=True)

    assert in_g['psd_sqrt_scalar'] < 0.1     # g/sqrt(Hz), a small number
    assert in_ms2['psd_sqrt_scalar'] == pytest.approx(G0 * in_g['psd_sqrt_scalar'])


# --- PSD scalarisation --------------------------------------------------------

def test_band_power_matches_the_parseval_energy_of_the_tone():
    """A single tone of amplitude A carries A^2/2 of power inside the band."""
    amplitude = 0.05

    _, debug = compute_psd_band_power(sine_signal(amplitude), FS)

    assert debug['psd_band_power'] == pytest.approx(amplitude**2 / 2, rel=0.02)


def test_scalar_modes_differ_by_the_width_of_the_band():
    """
    band_power_sqrt = mean_psd_sqrt * sqrt(n_bins * df).

    The two carry different units (g vs g/sqrt(Hz)); Eq.3 wants the density, so
    the default is mean_psd_sqrt and the relation must stay exact.
    """
    signal = sine_signal(0.05)

    mean_sqrt, debug = compute_psd_band_power(signal, FS, scalar_mode='mean_psd_sqrt')
    power_sqrt, _ = compute_psd_band_power(signal, FS, scalar_mode='band_power_sqrt')
    peak_sqrt, _ = compute_psd_band_power(signal, FS, scalar_mode='peak_psd_sqrt')
    median_sqrt, _ = compute_psd_band_power(signal, FS, scalar_mode='median_psd_sqrt')

    band_width_hz = debug['psd_band_n'] * debug['psd_df_hz']
    assert power_sqrt == pytest.approx(mean_sqrt * np.sqrt(band_width_hz))
    # One tone in an otherwise empty band: the peak bin towers over the median
    assert peak_sqrt > mean_sqrt > median_sqrt


def test_unknown_scalar_mode_raises():
    with pytest.raises(ValueError, match='Unknown scalar_mode'):
        compute_psd_band_power(sine_signal(0.05), FS, scalar_mode='rms_of_hope')


# --- Eq.4 / Eq.5 / Eq.6 -------------------------------------------------------

@pytest.mark.parametrize('vehicle_type, expected', [
    # Grms = 0.1 g, speed = 50 km/h, npeop = stif = dampf = tyres = 1
    (VehicleType.LEV, 55.25 * 0.1 - 0.07 * 50 + 0.19 - 2.93 - 1.09 - 1.44 + 7.66),
    (VehicleType.DSD, 54.43 * 0.1 - 0.06 * 50 + 0.18 - 0.87 - 0.89 - 0.27 + 5.75),
    (VehicleType.GENERIC, 50.32 * 0.1 - 0.06 * 50 + 0.17 - 1.86 - 0.90 - 0.78 + 6.68),
])
def test_iri_multi_matches_hand_computed_equation(vehicle_type, expected):
    result = compute_iri_multi(0.1, 50.0, vehicle_type=vehicle_type)

    assert result == pytest.approx(expected)
    assert result > 0  # the fixture stays inside the non-clamped range


def test_iri_multi_generic_reference_value():
    """Eq.6 spelled out once, so a coefficient edit cannot pass silently."""
    assert compute_iri_multi(0.1, 50.0, vehicle_type=VehicleType.GENERIC) == \
        pytest.approx(5.342)


def test_iri_multi_is_clamped_at_zero():
    """A negative regression output is reported as 0, not as a negative roughness."""
    result = compute_iri_multi(0.0, 200.0, vehicle_type=VehicleType.GENERIC)

    assert result == 0.0


def test_iri_multi_responds_to_vehicle_parameters():
    baseline = compute_iri_multi(0.1, 50.0, vehicle_type=VehicleType.GENERIC)
    heavier = compute_iri_multi(0.1, 50.0, npeop=3.0, vehicle_type=VehicleType.GENERIC)

    assert heavier - baseline == pytest.approx(0.17 * 2.0)


# --- Calibrated-coefficient overrides (profilometer validation study) --------

def test_book_coefficients_are_pinned():
    """The published Eq.3 constants must never be retuned in place."""
    from road_quality_analyzer.metrics.iri import IRI_PSD_COEFFICIENTS
    assert IRI_PSD_COEFFICIENTS == {'A_sqrt_psd': 0.774, 'B_const': -0.825}


def test_compute_iri_psd_accepts_calibrated_overrides():
    import numpy as np
    from road_quality_analyzer.metrics.iri import compute_iri_psd

    rng = np.random.default_rng(20260820)
    fs = 100.0
    signal = 0.05 * np.sin(2 * np.pi * 2.0 * np.arange(0, 10, 1 / fs)) \
        + rng.normal(0, 0.005, 1000)

    raw_book, _, debug = compute_iri_psd(signal, fs, return_debug=True)
    raw_custom, clipped_custom, _ = compute_iri_psd(signal, fs, A=2.0, B=0.5)

    sqrt_psd = debug['psd_sqrt_scalar']
    assert raw_book == 0.774 * sqrt_psd - 0.825
    assert raw_custom == 2.0 * sqrt_psd + 0.5
    assert clipped_custom == max(0.0, raw_custom)


def test_partial_override_keeps_book_value_for_the_other():
    import numpy as np
    from road_quality_analyzer.metrics.iri import compute_iri_psd

    fs = 100.0
    signal = 0.05 * np.sin(2 * np.pi * 2.0 * np.arange(0, 10, 1 / fs))
    raw, _, debug = compute_iri_psd(signal, fs, A=1.0, return_debug=True)
    assert raw == 1.0 * debug['psd_sqrt_scalar'] - 0.825

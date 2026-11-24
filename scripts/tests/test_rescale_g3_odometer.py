"""Unit tests for the one-off G3 odometer-rescale tool (synthetic inputs only)."""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rescale_g3_odometer as r  # noqa: E402

DX = r.PROFILE_DX_M


def _sine(length_m: float, wavelength_m: float, amp_mm: float) -> np.ndarray:
    x = np.arange(int(round(length_m / DX)) + 1) * DX
    return amp_mm * np.sin(2 * math.pi * x / wavelength_m)


def _analytic_iri(wavelength_m: float, amp_mm: float) -> float:
    """Steady-state IRI of a sinusoid: (2/pi) |H(jw)| x slope amplitude x moving-average gain."""
    a, b = r.quarter_car_matrices()
    w = 2 * math.pi * r.V_MS / wavelength_m
    h = np.array([1.0, 0.0, -1.0, 0.0]) @ np.linalg.solve(1j * w * np.eye(4) - a, b)
    slope_amp = amp_mm * 2 * math.pi / wavelength_m
    u = math.pi * r.BASE_M / wavelength_m
    return 2 / math.pi * abs(h) * slope_amp * abs(math.sin(u) / u)


def test_read_odometer_factor():
    assert r.read_odometer_factor('<a>\n  <OdometerCalFactor>1.16176402249175</OdometerCalFactor>\n') \
        == pytest.approx(1.16176402249175)
    with pytest.raises(ValueError):
        r.read_odometer_factor('<OdometerCalDistance>50000</OdometerCalDistance>')


def test_constant_grade_has_zero_iri():
    z = -6.5 * np.arange(4001) * DX                     # 6.5 mm/m grade, 100 m
    assert np.max(r.iri_rates(z)) < 1e-9


@pytest.mark.parametrize('wavelength', [2.0, 5.0, 15.0])
def test_sinusoid_matches_quarter_car_frequency_response(wavelength):
    z = _sine(400.0, wavelength, 3.0)
    rates = r.iri_rates(z)
    steady = rates[int(100 / DX):int(100 / DX) + int(round(10 * wavelength / DX))]   # whole periods
    assert steady.mean() == pytest.approx(_analytic_iri(wavelength, 3.0), rel=1e-2)


def test_iri_intervals_layout_like_device():
    ends, values = r.iri_intervals(_sine(30.0, 5.0, 2.0))
    assert ends[0] == pytest.approx(1.0)
    assert np.allclose(np.diff(ends[:-1]), 1.0)
    assert ends[-1] == pytest.approx((len(_sine(30.0, 5.0, 2.0)) - 10) * DX)   # last rate, partial interval
    assert len(values) == len(ends)


def test_rescale_profile_keeps_slope_when_heights_scale():
    dist = np.arange(4001) * DX
    z = -6.5 * dist
    corr = r.rescale_profile(dist, z, 0.8, scale_height=True)
    assert (len(corr) - 1) * DX == pytest.approx(80.0, abs=DX)
    assert np.allclose(np.diff(corr) / DX, -6.5)
    kept = r.rescale_profile(dist, z, 0.8, scale_height=False)
    assert np.allclose(np.diff(kept) / DX, -6.5 / 0.8)


def test_rescaled_sinusoid_iri_is_that_of_the_stretched_wave():
    dist = np.arange(int(round(500 / DX)) + 1) * DX
    z = 3.0 * np.sin(2 * math.pi * dist / 6.0)
    corr = r.rescale_profile(dist, z, 0.85, scale_height=True)    # wavelength 5.1 m, amplitude 2.55 mm
    rates = r.iri_rates(corr)
    steady = rates[int(100 / DX):int(100 / DX) + int(round(10 * 5.1 / DX))]
    assert steady.mean() == pytest.approx(_analytic_iri(5.1, 2.55), rel=1e-2)


def test_rescale_gnss_speed_and_events():
    gnss = ('\ufeffDistance(m),Speed(km/h),Latitude,Longitude,Altitude(m),Bearing\r\n'
            '100.000,4,20,50.38,30.46,140,250\r\n'
            '200.000,4.0,50.37,30.45,141,251\r\n')
    out = r.rescale_gnss(gnss.lstrip('\ufeff'), 0.5).split('\r\n')
    assert out[0] == r.GNSS_HEADER
    assert out[1] == '50.000,2.10,50.38,30.46,140,250'
    assert out[2] == '100.000,2.00,50.37,30.45,141,251'
    ev = r.rescale_events('Distance(m),Latitude,Longitude,Event\r\n10.000,50.1,30.2,start\r\n', 0.5)
    assert ev == 'Distance(m),Latitude,Longitude,Event\r\n5.000,50.1,30.2,start\r\n'
    sp = r.rescale_two_column('Distance(m),Speed(km/h)\r\n10.000,4.2\r\n', 0.5, True)
    assert sp == 'Distance(m),Speed(km/h)\r\n5.000,2.1\r\n'


def _write_survey(tmp: Path, stem: str, z: np.ndarray, device_iri=None) -> None:
    d = np.arange(len(z)) * DX
    (tmp / f'{stem} Profile.csv').write_text(
        'Distance(m),Profile(mm)\n' + ''.join(f'{a:.3f},{b:.3f}\n' for a, b in zip(d, z)), encoding='utf-8')
    ends, vals = r.iri_intervals(np.round(z, 3))
    if device_iri is not None:
        vals = device_iri(vals)
    (tmp / f'{stem} IRI.csv').write_text(
        'Distance(m),IRI(m/km)\n' + ''.join(f'{a:.3f},{b:.3f}\n' for a, b in zip(ends, vals)), encoding='utf-8')
    (tmp / f'{stem} Speed.csv').write_text('Distance(m),Speed(km/h)\n0.000,4.0\n50.000,4.4\n', encoding='utf-8')
    (tmp / f'{stem} Events.csv').write_text('Distance(m),Latitude,Longitude,Event\n', encoding='utf-8')
    (tmp / f'{stem} GNSS.csv').write_text(
        'Distance(m),Speed(km/h),Latitude,Longitude,Altitude(m),Bearing\n0.000,4,00,50.0,30.0,140,90\n',
        encoding='utf-8')
    (tmp / f'{stem} Information.txt').write_text('Title: T\nQuality Setting: Fast Profiling\n', encoding='utf-8')


def test_main_end_to_end_record_and_refusals(tmp_path):
    stem = '2026-11-22 06h02m15s T'
    survey = tmp_path / 'Surveys'
    survey.mkdir()
    _write_survey(survey, stem, _sine(60.0, 4.0, 2.0))
    used, true = tmp_path / 'used.wp', tmp_path / 'true.wp'
    used.write_text('<OdometerCalFactor>1.2</OdometerCalFactor>', encoding='utf-8')
    true.write_text('<OdometerCalFactor>0.96</OdometerCalFactor>', encoding='utf-8')
    out = tmp_path / 'out'
    argv = ['--survey-dir', str(survey), '--survey', stem, '--used-wp', str(used), '--true-wp', str(true),
            '--out-dir', str(out), '--correction-date', '2026-11-22']
    assert r.main(argv) == 0

    rec = json.loads((out / 'odometer_correction.json').read_text(encoding='utf-8'))[0]
    assert rec['distance_scale'] == pytest.approx(0.8)
    assert rec['length_corrected_m'] == pytest.approx(48.0, abs=DX)
    assert rec['device_reproduction_check']['mae_10m'] < 0.01
    prof = (out / f'{stem} Profile.csv').read_bytes()
    assert not prof.startswith(b'\xef\xbb\xbf') and b'\r\n' in prof
    info = (out / f'{stem} Information.txt').read_text(encoding='utf-8')
    assert 'Odometer Correction: distance x0.800000 (factor 1.200000 -> 0.960000 from true.wp)' in info
    assert (out / f'{stem} Speed.csv').read_text(encoding='utf-8').splitlines()[2] == '40.000,3.5'

    with pytest.raises(FileExistsError):
        r.main(argv)


def test_main_refuses_when_recomputation_does_not_match_device(tmp_path):
    stem = 'S'
    _write_survey(tmp_path, stem, _sine(60.0, 4.0, 2.0), device_iri=lambda v: v * 1.1)
    wp = tmp_path / 'f.wp'
    wp.write_text('<OdometerCalFactor>1.0</OdometerCalFactor>', encoding='utf-8')
    with pytest.raises(ValueError, match='does not reproduce'):
        r.main(['--survey-dir', str(tmp_path), '--survey', stem, '--used-wp', str(wp), '--true-wp', str(wp),
                '--out-dir', str(tmp_path / 'out')])
    assert not (tmp_path / 'out').exists() or not any((tmp_path / 'out').iterdir())

"""
Unit tests for the G3 section-reference builder on synthetic passes with a
known ground truth: one road, a master pass and a second pass walked the other
way and shifted by a known lag (seeded rng — research determinism rule).
"""

import numpy as np
import pandas as pd
import pytest

from profilometer_validation import g3
from profilometer_validation.match import load_form_10m

SEED = 20261115
BOM = chr(0xFEFF)
DX = g3.PROFILE_DX_M
M_PER_DEG_LAT = 111195.0


def _road(length_m=420.0, seed=SEED):
    rng = np.random.default_rng(seed)
    n = int(round(length_m / DX)) + 1
    elevation = np.cumsum(rng.normal(0, 0.4, n))            # mm, broadband
    iri_per_m = rng.uniform(2.0, 9.0, int(length_m))       # m/km per base metre
    return elevation, iri_per_m


def _pass_texts(elevation, iri_per_m, base_from, base_to, title, info=None):
    """Device-format texts of a pass walked from base_from to base_to (m)."""
    sign = 1 if base_to > base_from else -1
    length = abs(base_to - base_from)
    n = int(round(length / DX)) + 1
    base_idx = (base_from / DX + sign * np.arange(n)).round().astype(int)
    z = elevation[base_idx] - elevation[base_idx[0]]
    profile = 'Distance(m),Profile(mm)\n' + '\n'.join(
        f'{i * DX:.3f},{v:.3f}' for i, v in enumerate(z))
    iri_rows = []
    for k in range(int(length)):
        base_m = int(base_from + k) if sign > 0 else int(base_from - k - 1)
        iri_rows.append(f'{k + 1:.3f},{iri_per_m[base_m]:.3f}')
    iri = 'Distance(m),IRI(m/km)\n' + '\n'.join(iri_rows)
    gnss_rows = []
    for k in range(int(length * 10) + 1):
        d = k / 10
        base_x = base_from + sign * d
        speed = '0,90' if k % 2 else '1,20'                # device decimal comma
        gnss_rows.append(f'{d:.3f},{speed},{50 + base_x / M_PER_DEG_LAT:.8f},30.00000000,150,0')
    gnss = BOM + 'Distance(m),Speed(km/h),Latitude,Longitude,Altitude(m),Bearing\r\n' + \
        '\r\n'.join(gnss_rows)
    info_text = None
    if info is not None:
        info_text = BOM + '\r\n'.join(f'{k}: {v}' for k, v in info.items())
    return g3.G3Pass.from_texts(title, iri, gnss, profile, info_text)


INFO_FAST = {'Title': 'P1', 'Date/Time': '2026-11-14 10:00:00', 'Quality Setting': 'Fast Profiling',
             'Surface': 'Concrete', 'Accelerometer Calibration Date/Time': '2026-11-14 09:00:00',
             'Odometer Calibration Date/Time': '2026-11-14 09:05:00',
             'Field Offset Calibration Date/Time': '2026-11-14 09:10:00'}


def test_parse_gnss_both_formats():
    device = (BOM + 'Distance(m),Speed(km/h),Latitude,Longitude,Altitude(m),Bearing\r\n'
              '0.000,1,23,-12.0,-77.0,989,138\r\n0.100,1,63,-12.1,-77.1,989,138\r\n')
    clean = ('Distance(m),Speed(km/h),Latitude,Longitude,Altitude(m),Bearing\r\n'
             '0.000,1.23,50.4,30.2,,90\r\n0.100,1.63,50.5,30.3,,90\r\n')
    a, b = g3.parse_gnss_csv(device), g3.parse_gnss_csv(clean)
    assert a['speed_kmh'].tolist() == [1.23, 1.63] and a['lat'].tolist() == [-12.0, -12.1]
    assert b['speed_kmh'].tolist() == [1.23, 1.63] and b['lon'].tolist() == [30.2, 30.3]


def test_parse_gnss_drops_no_fix_placeholder_rows():
    text = ('Distance(m),Speed(km/h),Latitude,Longitude,Altitude(m),Bearing\n'
            '0.000,0,00,0.00000000,0.00000000,0,0\n0.100,1,00,50.4,30.3,150,0\n')
    assert g3.parse_gnss_csv(text)['lat'].tolist() == [50.4]
    with pytest.raises(ValueError):
        g3.parse_gnss_csv('Distance(m),Speed(km/h),Latitude,Longitude,Altitude(m),Bearing\n'
                          '0.000,0,00,0.0,0.0,0,0\n')


def test_parse_iri_rejects_non_increasing():
    with pytest.raises(ValueError):
        g3.parse_iri_csv('Distance(m),IRI(m/km)\n1.0,2.0\n1.0,3.0\n')


def test_information_keys_with_space_before_colon():
    info = g3.parse_information(BOM + 'Title: Zao_1\r\nField Offset Calibration Date/Time : 2026-01-29 15:07:41\r\n')
    assert info['Title'] == 'Zao_1'
    assert info['Field Offset Calibration Date/Time'] == '2026-01-29 15:07:41'


def test_profile_alignment_recovers_reverse_direction_and_lag():
    elevation, iri = _road()
    master = _pass_texts(elevation, iri, 50, 350, 'M', INFO_FAST)
    back = _pass_texts(elevation, iri, 352, 52, 'B', {**INFO_FAST, 'Title': 'B',
                                                      'Date/Time': '2026-11-14 10:30:00'})
    alignment = g3.align_by_profile(master.profile, back.profile)
    assert alignment['direction'] == 'reverse'
    assert alignment['lag_m'] == pytest.approx(2.0, abs=DX)
    assert alignment['r'] > 0.95


def test_section_reference_channels_coverage_and_format():
    elevation, iri = _road()
    master = _pass_texts(elevation, iri, 50, 350, 'M', INFO_FAST)
    back = _pass_texts(elevation, iri, 352, 52, 'B', {**INFO_FAST, 'Title': 'B',
                                                      'Date/Time': '2026-11-14 10:30:00'})
    ref = g3.build_section_reference([back, master])        # master chosen by date, not order

    assert [c['survey'] for c in ref.channels] == ['P1', 'B']
    assert ref.channels[1]['alignment'] == 'profile' and ref.channels[1]['direction'] == 'reverse'
    table = ref.intervals
    assert len(table) == 30 and ref.step_m == 10.0 and ref.chainage_span_m == 300.0
    # channel 1 = length-weighted mean of the master's 1 m IRI
    assert table['iri_ch1'].iloc[0] == pytest.approx(iri[50:60].mean(), abs=1e-3)
    # the reversed pass reproduces the same road where it covers >= 90 %
    assert np.isnan(table['iri_ch2'].iloc[0])                # covers only 8 m of [0, 10)
    np.testing.assert_allclose(table['iri_ch2'].iloc[1:], table['iri_ch1'].iloc[1:], atol=1e-3)
    assert table[[f'iri_ch{c}' for c in range(3, 11)]].isna().all().all()
    assert ref.channels[1]['mean_abs_diff_vs_ch1'] == pytest.approx(0.0, abs=1e-3)
    assert ref.label == 'G3 2026-11-14 P1+B'
    assert not any('калібрування' in w for w in ref.warnings)


def test_stored_table_feeds_load_form_10m_unchanged(tmp_path):
    elevation, iri = _road()
    master = _pass_texts(elevation, iri, 50, 350, 'M', INFO_FAST)
    ref = g3.build_section_reference([master])
    path = tmp_path / 'intervals_10m.csv'
    ref.intervals.to_csv(path, index=False, encoding='utf-8', lineterminator='\n')
    loaded = load_form_10m(str(path))
    np.testing.assert_allclose(loaded['iri_ref_10'], ref.intervals['iri_ch1'], atol=1e-9)
    assert loaded['chainage_m'].iloc[0] == 5.0


def test_unrelated_pass_falls_back_to_gnss_with_warning():
    elevation, iri = _road()
    other_elevation, _ = _road(seed=SEED + 1)
    master = _pass_texts(elevation, iri, 50, 350, 'M', INFO_FAST)
    other = _pass_texts(other_elevation, iri, 352, 52, 'X', {**INFO_FAST, 'Title': 'X',
                                                             'Date/Time': '2026-11-14 11:00:00'})
    ref = g3.build_section_reference([master, other])
    ch2 = ref.channels[1]
    assert ch2['alignment'] == 'gnss' and ch2['direction'] == 'reverse'
    assert ch2['lag_m'] == pytest.approx(2.0, abs=0.2)
    assert any("прив'язка за GNSS" in w for w in ref.warnings)


def test_quality_warnings_calibration_and_reference_speed():
    elevation, iri = _road()
    info = {**INFO_FAST, 'Quality Setting': 'Reference Profiling',
            'Field Offset Calibration Date/Time': '2026-01-29 15:07:41'}
    ref = g3.build_section_reference([_pass_texts(elevation, iri, 50, 350, 'M', info)])
    assert any('калібрування приладу від 2026-01-29' in w for w in ref.warnings)
    assert any('Reference Profiling' in w and '50%' in w for w in ref.warnings)


def test_stale_factory_sensitivity_calibration_is_not_a_warning():
    elevation, iri = _road()
    info = {**INFO_FAST, 'Accelerometer Calibration Date/Time': '2026-01-29 14:36:21'}
    ref = g3.build_section_reference([_pass_texts(elevation, iri, 50, 350, 'M', info)])
    assert not any('калібрування приладу' in w for w in ref.warnings)


def test_limits_empty_and_too_many_passes():
    with pytest.raises(ValueError):
        g3.build_section_reference([])
    elevation, iri = _road(length_m=130.0)
    one = _pass_texts(elevation, iri, 0, 120, 'M', INFO_FAST)
    with pytest.raises(ValueError):
        g3.build_section_reference([one] * 9)

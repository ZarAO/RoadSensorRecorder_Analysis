"""Unit tests for the one-off G3 re-georeference tool (synthetic inputs only)."""

import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import georef_g3_spoofed as g  # noqa: E402

# Two vertices on one meridian, ~111.2 m apart (0.001 deg of latitude)
STRAIGHT = [(50.0, 30.0), (50.001, 30.0)]


def test_parse_gnss_line_decimal_comma_and_plain():
    assert g.parse_gnss_line('0.300,2,04,-12.0,-77.0,989,138') == (0.3, 2.04)
    assert g.parse_gnss_line('5.000,3.5,50.1,30.2,150,90') == (5.0, 3.5)
    with pytest.raises(ValueError):
        g.parse_gnss_line('1,2,3')


def test_route_at_ends_midpoint_and_clamp():
    route = g.Route(STRAIGHT)
    assert route.length == pytest.approx(111.19, abs=0.05)
    assert route.at(0)[:2] == pytest.approx(STRAIGHT[0])
    assert route.at(route.length)[:2] == pytest.approx(STRAIGHT[1])
    lat, lon, bearing = route.at(route.length / 2)
    assert (lat, lon) == pytest.approx((50.0005, 30.0))
    assert bearing == pytest.approx(0.0, abs=1e-6)          # due north
    assert route.at(-5)[:2] == pytest.approx(STRAIGHT[0])    # clamped


def test_rebuild_gnss_scales_odometer_onto_route_both_directions():
    text = ('\ufeffDistance(m),Speed(km/h),Latitude,Longitude,Altitude(m),Bearing\r\n'
            '0.000,1,20,-12.0,-77.0,989,138\r\n'
            '100.000,3,00,-12.1,-77.1,990,140\r\n'
            '200.000,0,00,-12.2,-77.2,991,141\r\n')
    route = g.Route(STRAIGHT)
    out, start, end, total = g.rebuild_gnss(text, route, reverse=False)
    lines = out.split('\r\n')
    assert lines[0] == g.GNSS_HEADER and not out.startswith('\ufeff')
    assert total == 200.0
    assert start == pytest.approx(STRAIGHT[0]) and end == pytest.approx(STRAIGHT[1])
    mid = lines[2].split(',')
    assert mid[1] == '3.00' and mid[4] == '' and mid[5] == '0'
    assert (float(mid[2]), float(mid[3])) == pytest.approx((50.0005, 30.0))

    _, r_start, r_end, _ = g.rebuild_gnss(text, route, reverse=True)
    assert r_start == pytest.approx(STRAIGHT[1]) and r_end == pytest.approx(STRAIGHT[0])
    assert g.rebuild_gnss(text, route, reverse=True)[0].split('\r\n')[2].endswith(',180')


def test_rebuild_information_changes_only_locations():
    text = ('Title: Zao_1\r\nStart Location: -12.03,-77.04\r\n'
            'End Location: -12.04,-77.05\r\nSurface: Concrete\r\n')
    out = g.rebuild_information(text, (50.1, 30.2), (50.3, 30.4))
    assert out == ('Title: Zao_1\r\nStart Location: 50.10000000,30.20000000\r\n'
                   'End Location: 50.30000000,30.40000000\r\nSurface: Concrete\r\n')


def _ppf_stub(lat=-12.0, lon=-77.0) -> bytes:
    data = bytearray(b'SPPF1.05' + b'\x00' * 600)
    for lon_off, lat_off, alt_off in g.PPF_OFFSETS.values():
        struct.pack_into('<f', data, lon_off, lon)
        struct.pack_into('<f', data, lat_off, lat)
        struct.pack_into('<f', data, alt_off, 991.0)
    return bytes(data)


def test_patch_ppf_writes_floats_and_guards_format():
    patched = g.patch_ppf(_ppf_stub(), (50.4, 30.2), (50.5, 30.3))
    read = lambda off: struct.unpack_from('<f', patched, off)[0]
    assert (read(382), read(358), read(406)) == pytest.approx((50.4, 30.2, 0.0), abs=1e-5)
    assert (read(454), read(430), read(478)) == pytest.approx((50.5, 30.3, 0.0), abs=1e-5)
    assert len(patched) == len(_ppf_stub())
    with pytest.raises(ValueError):
        g.patch_ppf(b'XXXX' + _ppf_stub()[4:], (50.4, 30.2), (50.5, 30.3))
    with pytest.raises(ValueError):
        g.patch_ppf(_ppf_stub(lat=500.0), (50.4, 30.2), (50.5, 30.3))


def test_main_writes_new_files_and_refuses_overwrite(tmp_path):
    survey_dir = tmp_path / 'Surveys'
    survey_dir.mkdir()
    name = '2026-01-01 10h00m00s T_1'
    (survey_dir / f'{name} GNSS.csv').write_text(
        '\ufeffDistance(m),Speed(km/h),Latitude,Longitude,Altitude(m),Bearing\r\n'
        '0.000,1,00,-12.0,-77.0,989,1\r\n50.000,2,00,-12.0,-77.0,989,1\r\n', encoding='utf-8')
    (survey_dir / f'{name} Information.txt').write_text(
        'Start Location: -12.0,-77.0\r\nEnd Location: -12.0,-77.0\r\n', encoding='utf-8')
    (survey_dir / f'{name}.ppf').write_bytes(_ppf_stub())
    route = tmp_path / 'route.geojson'
    route.write_text(json.dumps({'type': 'LineString',
                                 'coordinates': [[30.0, 50.0], [30.0, 50.001]]}), encoding='utf-8')
    out_dir = tmp_path / 'out'
    argv = ['--survey-dir', str(survey_dir), '--survey', name, '--route', str(route),
            '--out-dir', str(out_dir), '--correction-date', '2026-11-15']

    assert g.main(argv) == 0
    record = json.loads((out_dir / 'georef_correction.json').read_text(encoding='utf-8'))
    assert record[0]['correction_date'] == '2026-11-15' and record[0]['direction'] == 'forward'
    assert record[0]['odometer_length_m'] == 50.0
    assert (survey_dir / f'{name} GNSS.csv').read_text(encoding='utf-8').count('-77.0') == 2
    with pytest.raises(FileExistsError):
        g.main(argv)

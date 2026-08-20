import pytest

from tests.helpers import make_probe_csv


def test_probe_extracts_preview(tmp_path):
    from src.services.preview import probe_csv
    info = probe_csv(make_probe_csv(tmp_path))
    assert 1.9 < info['duration_s'] <= 2.1
    assert 90 < info['fs_hz'] < 110
    assert info['gps_coverage_ratio'] == pytest.approx(1.0, abs=0.1)
    assert info['recording_meta']['vehicle']['vehicle_type'] == 'sedan'
    assert info['recording_meta']['clean_stop'] is True


def test_probe_pre_v21_file_has_empty_metadata(tmp_path):
    from src.services.preview import probe_csv
    info = probe_csv(make_probe_csv(tmp_path, preamble=False))
    assert info['recording_meta']['vehicle'] == {}
    assert info['recording_meta']['clean_stop'] is False


def test_probe_rejects_wrong_header(tmp_path):
    from src.services.preview import probe_csv
    p = tmp_path / 'bad.csv'
    p.write_text("Time,Kind\n1,Accelerometer\n", encoding='utf-8')
    with pytest.raises(ValueError):
        probe_csv(str(p))

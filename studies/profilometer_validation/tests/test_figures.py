"""
Regression tests for the chainage-overlay file naming: a road label may carry
Cyrillic letters, a dash, a space or even a path separator, but the produced
file name must stay a plain ASCII slug inside out_dir (savefig would otherwise
fail or write outside it).
"""

from pathlib import Path

import matplotlib
matplotlib.use('Agg')

import pandas as pd

from profilometer_validation.figures import chainage_overlay


def _pairs(road: str, n: int = 8) -> pd.DataFrame:
    return pd.DataFrame({
        'road': [road] * n,
        'chainage_m': [i * 100.0 for i in range(n)],
        'iri_ref': [2.0 + 0.1 * i for i in range(n)],
        'iri_calibrated': [2.2 + 0.1 * i for i in range(n)],
    })


def _names(road: str, tmp_path: Path) -> list:
    """Render the figure and return the sorted base names actually written."""
    paths = [Path(p) for p in chainage_overlay(_pairs(road), road, tmp_path)]
    assert len(paths) == 2
    for path in paths:
        assert path.parent == tmp_path and path.exists() and path.stat().st_size > 0
    return sorted(path.name for path in paths)


def test_slug_transliterates_cyrillic_m_road(tmp_path):
    assert _names('М-03', tmp_path) == ['fig3_chainage_M03.pdf', 'fig3_chainage_M03.png']


def test_slug_transliterates_cyrillic_t_road(tmp_path):
    assert _names('Т1016', tmp_path) == ['fig3_chainage_T1016.pdf', 'fig3_chainage_T1016.png']


def test_slug_strips_separators_and_spaces(tmp_path):
    names = _names('М-03 Київ/Чернігів', tmp_path)
    for name in names:
        assert '/' not in name and '\\' not in name and ' ' not in name
        assert name.startswith('fig3_chainage_M03')
    assert names == ['fig3_chainage_M03.pdf', 'fig3_chainage_M03.png']


def test_slug_falls_back_when_nothing_survives(tmp_path):
    """An all-Cyrillic label leaves an empty slug — the fallback keeps a valid name."""
    assert _names('Дорога', tmp_path) == ['fig3_chainage_road.pdf',
                                          'fig3_chainage_road.png']

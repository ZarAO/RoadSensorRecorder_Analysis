"""
Unit tests for ranking_agreement(): does the smartphone reproduce the
reference ORDERING and the normative level of each segment?
"""

import numpy as np
import pandas as pd
import pytest

from profilometer_validation.calibrate import ranking_agreement

SEED = 20260920


def _pairs(n=60, shift=0.0, rng=None):
    rng = rng or np.random.default_rng(SEED)
    ref = rng.uniform(1.0, 9.0, n)
    return pd.DataFrame({
        'road': 'R1',
        'chainage_m': 50.0 + 100.0 * np.arange(n),
        'iri_ref': ref,
        'iri_multi_bias_corrected': ref + shift,
    })


def test_constant_shift_keeps_every_top_k_but_moves_every_value():
    out = ranking_agreement(_pairs(shift=-1.0))

    assert out['n'] == 60
    assert out['top_k_overlap']['10'] == {'k': 10, 'overlap': 10}
    assert out['top_k_overlap']['20'] == {'k': 20, 'overlap': 20}
    assert out['share_within']['0.5'] == 0.0
    assert out['share_within']['1'] == 1.0       # |diff| == 1.0 counts as within 1 m/km


def test_identical_values_agree_on_every_level():
    out = ranking_agreement(_pairs(shift=0.0))

    assert out['level_same_share'] == 1.0
    assert out['level_within_one_share'] == 1.0
    assert out['level_thresholds'] == [2.7, 3.1, 3.5, 4.1]


def test_levels_are_right_closed_like_the_standard_says_not_more_than():
    # 2.7 m/km still meets requirement level 1 ("не більше ніж 2,7"); 2.71 does not
    df = pd.DataFrame({
        'chainage_m': [50.0, 150.0],
        'iri_ref': [2.71, 2.71],
        'iri_multi_bias_corrected': [2.70, 2.71],
    })
    out = ranking_agreement(df)

    assert out['level_same_share'] == 0.5
    assert out['level_within_one_share'] == 1.0


def test_worst_and_rough_span_are_read_from_the_reference():
    df = _pairs()
    df.loc[7, 'iri_ref'] = 15.27
    df.loc[7, 'iri_multi_bias_corrected'] = 7.54
    df.loc[[12, 30], 'iri_ref'] = [6.5, 8.0]

    out = ranking_agreement(df, rough_threshold=6.0)

    assert out['worst'] == {'chainage_m': 750.0, 'iri_ref': 15.27, 'metric': 7.54}
    rough = df[df['iri_ref'] >= 6.0]
    assert out['rough']['threshold'] == 6.0
    assert out['rough']['n'] == len(rough)
    assert out['rough']['chainage_min_m'] == rough['chainage_m'].min()
    assert out['rough']['chainage_max_m'] == rough['chainage_m'].max()
    assert out['rough']['metric_to_ref_mean_ratio'] == pytest.approx(
        (rough['iri_multi_bias_corrected'] / rough['iri_ref']).mean())


def test_top_k_is_capped_by_the_sample_size():
    out = ranking_agreement(_pairs(n=5))
    assert out['top_k_overlap']['10'] == {'k': 5, 'overlap': 5}

"""Unit tests for the base-vs-improved metrics (synthetic pairs, known truth)."""

import numpy as np
import pandas as pd
import pytest

from profilometer_validation import ablation


def _pairs(vehicle, road, offset, n=10, speed=60.0, speed_valid=True):
    ref = np.linspace(1.0, 5.0, n)
    return pd.DataFrame({'vehicle': vehicle, 'road': road, 'iri_ref': ref,
                         'iri_multi': ref + offset, 'speed_valid': speed_valid,
                         'length_m': 100.0, 'mean_speed_kmh': speed})


def test_offset_comes_from_the_other_road_of_the_same_vehicle():
    pairs = pd.concat([_pairs('van', 'A', -1.0), _pairs('van', 'B', -2.0),
                       _pairs('car', 'A', -5.0), _pairs('car', 'B', -5.0)])
    out = ablation.variant_metrics(pairs)
    assert out['van|A']['k_other_road'] == pytest.approx(-2.0)
    assert out['van|A']['loro_bias_corrected_mae'] == pytest.approx(1.0)
    assert out['car|B']['loro_bias_corrected_mae'] == pytest.approx(0.0)
    assert out['van|A']['spearman_rho'] == pytest.approx(1.0)


def test_outside_corridor_split_and_single_road_vehicle():
    inside = _pairs('van', 'A', -1.0)
    outside = _pairs('van', 'A', -3.0, n=4, speed=12.0, speed_valid=False)
    pairs = pd.concat([inside, outside, _pairs('van', 'B', -1.0), _pairs('solo', 'A', 0.0)])
    out = ablation.variant_metrics(pairs)
    split = out['van|A']['outside_20_100_kmh']
    assert split['n'] == 4
    assert split['mae'] == pytest.approx(2.0) and split['mae_inside'] == pytest.approx(0.0)
    # a vehicle seen on one road has no other-road offset: reported, not invented
    assert out['solo|A']['k_other_road'] is None
    assert out['solo|A']['loro_bias_corrected_mae'] is None


def test_missing_speed_valid_fails_loud():
    pairs = _pairs('van', 'A', -1.0).astype({'speed_valid': object})
    pairs.loc[0, 'speed_valid'] = np.nan
    with pytest.raises(ValueError):
        ablation.variant_metrics(pairs)


def test_speed_regime_restriction_uses_both_bounds():
    pairs = pd.concat([_pairs('van', 'A', 0.0, speed=40.0), _pairs('van', 'A', 0.0, speed=60.0),
                       _pairs('van', 'A', 0.0, speed=90.0), _pairs('car', 'B', 0.0, speed=50.0)])
    variant = pairs[(pairs['mean_speed_kmh'] > 45) & (pairs['mean_speed_kmh'] < 80)]
    speed_range = ablation.speed_range_by_group(variant)
    kept = ablation.restrict_to_regime(pairs, speed_range)
    assert speed_range == {('car', 'B'): (50.0, 50.0), ('van', 'A'): (60.0, 60.0)}
    assert set(kept['mean_speed_kmh']) == {50.0, 60.0}          # 40 and 90 km/h both out
    assert ablation.restrict_to_regime(pairs, {}).empty

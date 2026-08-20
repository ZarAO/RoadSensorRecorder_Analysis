import numpy as np
import pandas as pd
import pytest

from profilometer_validation.aggregate import (
    bias_with_ci, bin_pairs, per_bin_stats, repeatability_sd, speed_effect)


def _passes(n_bins=20, passes=3, bias=-1.5, noise=0.0, speed_by_pass=None, seed=1):
    """Synthetic pairs: iri_ref rises linearly; each pass = ref + bias + noise."""
    rng = np.random.default_rng(seed)
    rows = []
    for p in range(passes):
        speed = (speed_by_pass or {}).get(p, 60.0)
        for b in range(n_bins):
            chain = b * 100.0 + 37.0          # arbitrary in-bin offset
            ref = 2.0 + 0.1 * b
            rows.append({'run_id': p, 'chainage_m': chain,
                         'iri_ref': ref,
                         'iri_multi': ref + bias + rng.normal(0, noise),
                         'mean_speed_kmh': speed})
    return pd.DataFrame(rows)


def test_bin_pairs_centers():
    binned = bin_pairs(_passes(n_bins=3, passes=1))
    assert sorted(binned['bin_center'].unique()) == [50.0, 150.0, 250.0]


def test_per_bin_stats_exact_no_noise():
    bins = per_bin_stats(bin_pairs(_passes(bias=-1.5, noise=0.0)))
    assert len(bins) == 20
    assert bins['n_passes'].eq(3).all()
    assert bins['diff'].round(9).eq(-1.5).all()
    assert bins['std_iri'].round(9).eq(0.0).all()
    assert bins['min_iri'].le(bins['max_iri']).all()


def test_std_nan_for_single_pass_bin():
    bins = per_bin_stats(bin_pairs(_passes(passes=1)))
    assert bins['n_passes'].eq(1).all()
    assert bins['std_iri'].isna().all()


def test_repeatability_recovers_noise():
    out = repeatability_sd(bin_pairs(_passes(passes=5, noise=0.3, n_bins=200)))
    assert out['n_bins_used'] == 200
    assert out['sd'] == pytest.approx(0.3, rel=0.15)


def test_bias_ci_covers_truth():
    bins = per_bin_stats(bin_pairs(_passes(bias=-1.5, noise=0.2, n_bins=50)))
    out = bias_with_ci(bins)
    assert out['ci_low'] < -1.5 < out['ci_high']
    assert out['n_bins'] == 50 and out['n_eff'] <= 50
    assert out['bias'] == pytest.approx(-1.5, abs=0.15)


def test_speed_effect_recovers_known_slope():
    # inject diff depending on speed: pass speeds 40/60/80, slope -0.05 IRI per km/h
    df = _passes(passes=3, noise=0.05, n_bins=100,
                 speed_by_pass={0: 40.0, 1: 60.0, 2: 80.0})
    df['iri_multi'] = df['iri_multi'] - 0.05 * (df['mean_speed_kmh'] - 60.0)
    out = speed_effect(bin_pairs(df))
    assert out is not None
    assert out['slope_iri_per_kmh'] == pytest.approx(-0.05, abs=0.01)
    assert out['n_bins'] == 100


def test_speed_effect_none_when_constant_speed():
    assert speed_effect(bin_pairs(_passes())) is None

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


# --- statistical-review fix coverage -----------------------------------

def test_bin_pairs_drops_non_finite_rows():
    df = _passes(n_bins=5, passes=3, bias=-1.5, noise=0.0)
    idx = df.index[(df['run_id'] == 0) & (df['chainage_m'] < 100)][0]
    df.loc[idx, 'iri_multi'] = np.nan
    binned = bin_pairs(df)
    assert not binned['iri_multi'].isna().any()
    assert len(binned) == len(df) - 1


def test_bias_unchanged_when_nan_pass_rows_injected():
    df = _passes(bias=-1.5, noise=0.0, n_bins=20)
    clean_bias = bias_with_ci(per_bin_stats(bin_pairs(df)))['bias']

    noisy = df.copy()
    noisy.loc[noisy.sample(5, random_state=0).index, 'iri_multi'] = np.nan
    noisy_bias = bias_with_ci(per_bin_stats(bin_pairs(noisy)))['bias']

    assert noisy_bias == pytest.approx(clean_bias, abs=1e-9)


def test_repeatability_none_when_single_pass_after_nan_drop():
    df = _passes(passes=2, n_bins=10, noise=0.0)
    df.loc[df['run_id'] == 1, 'iri_multi'] = np.nan
    out = repeatability_sd(bin_pairs(df))
    assert out == {'sd': None, 'n_bins_used': 0}


def test_speed_effect_none_when_bins_disjoint():
    # Two passes never share a bin -> no bin has >=2 passes.
    df1 = _passes(n_bins=10, passes=1, speed_by_pass={0: 40.0})
    df2 = _passes(n_bins=10, passes=1, speed_by_pass={0: 80.0})
    df2['run_id'] = 1
    df2['chainage_m'] = df2['chainage_m'] + 10_000.0
    df = pd.concat([df1, df2], ignore_index=True)
    assert speed_effect(bin_pairs(df)) is None


def test_speed_effect_none_when_within_bin_speeds_equal():
    # Pass-level speed spread clears the gate, but every bin's passes all
    # recorded the same speed for that bin -> demeaned x is 0 everywhere.
    rows = []
    for run_id in (0, 1):
        rows.append({'run_id': run_id, 'chainage_m': 50.0, 'iri_ref': 2.0,
                     'iri_multi': 1.0, 'mean_speed_kmh': 40.0})
    for run_id in (0, 1, 2):
        rows.append({'run_id': run_id, 'chainage_m': 150.0, 'iri_ref': 2.1,
                     'iri_multi': 1.1, 'mean_speed_kmh': 80.0})
    for run_id in (1, 2):
        rows.append({'run_id': run_id, 'chainage_m': 250.0, 'iri_ref': 2.2,
                     'iri_multi': 1.2, 'mean_speed_kmh': 100.0})
    df = pd.DataFrame(rows)
    assert speed_effect(bin_pairs(df)) is None


def test_per_bin_stats_empty_input_returns_documented_columns():
    empty = pd.DataFrame(columns=['run_id', 'chainage_m', 'iri_ref', 'iri_multi',
                                  'mean_speed_kmh', 'bin_center'])
    out = per_bin_stats(empty)
    assert out.empty
    assert list(out.columns) == [
        'bin_center', 'iri_ref', 'mean_iri', 'std_iri', 'min_iri', 'max_iri',
        'n_passes', 'mean_speed_kmh', 'diff',
    ]


def test_duplicate_rows_per_pass_per_bin_collapse_to_one():
    df = _passes(n_bins=5, passes=2, bias=-1.5, noise=0.0)
    dup_idx = df.index[(df['run_id'] == 0) & (df['chainage_m'] < 100)][0]
    extra = df.loc[[dup_idx]].copy()
    extra['iri_multi'] = extra['iri_multi'] + 0.4  # a second short window, same pass/bin
    df2 = pd.concat([df, extra], ignore_index=True)

    bins = per_bin_stats(bin_pairs(df2))
    row = bins[bins['bin_center'] == 50.0].iloc[0]
    assert row['n_passes'] == 2
    assert row['mean_iri'] == pytest.approx(0.6)
    assert row['std_iri'] == pytest.approx(0.14142135623730953, abs=1e-9)

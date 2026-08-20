"""
Multi-pass aggregation methodology (dissertation, spec Phase 2).

Every smartphone pass is binned onto the reference chainage (fixed 100 m
grid, so passes on the same road land on the same bins regardless of each
pass's own s=0). Repeatability is the pooled within-bin standard deviation
over bins that were driven more than once. The pass-to-pass bias against the
reference is reported with a t-distribution confidence interval whose degrees
of freedom use the Bartlett-style effective n (`calibrate.effective_n`),
because consecutive 100 m bins on one road are spatially autocorrelated and a
nominal-n interval would be overconfident. The speed effect on IRI is
estimated with a demeaned (within-bin fixed-effects) slope: subtracting the
per-bin mean from both the diff and the speed removes road-roughness as a
confound, so the slope reflects only speed variation at matched roughness,
not "rougher bins happen to be driven at a different average speed".

NaN hygiene: `iri_multi` is a legal output of the road-quality analyzer (a
window it could not score), so `bin_pairs` drops any row with a non-finite
iri_multi/iri_ref/chainage_m up front (mirrors `calibrate._clean`). Without
this, a single NaN silently turns its bin's `per_bin_stats` row NaN, disables
the Bartlett correction inside `bias_with_ci` (a NaN diff makes the
autocorrelation denominator NaN, so `effective_n` reports r1=0 and n_eff
collapses to the nominal n -- making the CI too NARROW, the opposite of
conservative), and makes `repeatability_sd` return NaN instead of a proper
`None`. `bias_with_ci` and `repeatability_sd` additionally filter defensively
(non-finite diffs / variances) and report the actual count they pooled over.

A pass can contribute more than one row to a bin when a short analysis
window's boundary falls inside the bin. `per_bin_stats`, `repeatability_sd`,
and `speed_effect` all first collapse rows to one per (run_id, bin_center)
by averaging, so a split pass is not over-weighted and sigma_r stays a pure
pass-to-pass quantity.

All functions are pure: DataFrame in, DataFrame/dict out. Dict values are
plain floats/ints/None (JSON-serializable), never pandas/numpy scalars.
"""

import numpy as np
import pandas as pd
from scipy import stats as sps

from .calibrate import effective_n

BIN_WIDTH_M = 100.0

_PER_BIN_COLUMNS = [
    'bin_center', 'iri_ref', 'mean_iri', 'std_iri', 'min_iri', 'max_iri',
    'n_passes', 'mean_speed_kmh', 'diff',
]


def bin_pairs(pairs: pd.DataFrame, bin_width_m: float = BIN_WIDTH_M) -> pd.DataFrame:
    """
    Assign each row to a fixed-width bin on the reference chainage.

    Rows with a non-finite iri_multi, iri_ref, or chainage_m are dropped
    first (mirrors `calibrate._clean`) -- see the module docstring for why
    this matters to every downstream statistic.
    """
    required = ['iri_multi', 'iri_ref', 'chainage_m']
    finite = np.isfinite(pairs[required].to_numpy(float)).all(axis=1)
    out = pairs.loc[finite].copy()
    out['bin_center'] = (
        np.floor(out['chainage_m'].to_numpy(float) / bin_width_m) * bin_width_m
        + bin_width_m / 2.0
    )
    return out


def _collapse_duplicate_passes(binned: pd.DataFrame) -> pd.DataFrame:
    """Average >1 row per (run_id, bin_center) down to one row per pass/bin."""
    value_cols = ['iri_multi', 'iri_ref', 'mean_speed_kmh']
    return binned.groupby(['run_id', 'bin_center'], as_index=False)[value_cols].mean()


def per_bin_stats(binned: pd.DataFrame) -> pd.DataFrame:
    """
    One row per bin_center (ascending), pooling all passes that hit it.

    Returns an empty DataFrame with the documented columns (no KeyError)
    when `binned` has no rows.
    """
    if binned.empty:
        return pd.DataFrame(columns=_PER_BIN_COLUMNS)

    collapsed = _collapse_duplicate_passes(binned)
    rows = []
    for bin_center, group in collapsed.groupby('bin_center'):
        iri_multi = group['iri_multi'].to_numpy(float)
        rows.append({
            'bin_center': float(bin_center),
            'iri_ref': float(group['iri_ref'].mean()),
            'mean_iri': float(iri_multi.mean()),
            'std_iri': float(np.std(iri_multi, ddof=1)) if len(iri_multi) >= 2 else float('nan'),
            'min_iri': float(iri_multi.min()),
            'max_iri': float(iri_multi.max()),
            'n_passes': int(group['run_id'].nunique()),
            'mean_speed_kmh': float(group['mean_speed_kmh'].mean()),
        })
    out = pd.DataFrame(rows, columns=_PER_BIN_COLUMNS[:-1]).sort_values(
        'bin_center', kind='mergesort').reset_index(drop=True)
    out['diff'] = out['mean_iri'] - out['iri_ref']
    return out


def repeatability_sd(binned: pd.DataFrame) -> dict:
    """
    Pooled within-bin std over bins driven more than once.

    `sd` is `None` both when no bin has >=2 passes and when every within-bin
    variance that would be pooled is non-finite (defensive: `bin_pairs`
    already drops non-finite iri_multi rows upstream).
    """
    if binned.empty:
        return {'sd': None, 'n_bins_used': 0}

    collapsed = _collapse_duplicate_passes(binned)
    variances = []
    for _, group in collapsed.groupby('bin_center'):
        if group['run_id'].nunique() >= 2:
            var = np.var(group['iri_multi'].to_numpy(float), ddof=1)
            if np.isfinite(var):
                variances.append(var)
    if not variances:
        return {'sd': None, 'n_bins_used': 0}
    return {'sd': float(np.sqrt(np.mean(variances))), 'n_bins_used': int(len(variances))}


def bias_with_ci(bins: pd.DataFrame, confidence: float = 0.95) -> dict:
    """
    Mean bias with a t-CI whose dof uses the Bartlett effective n.

    Non-finite diff rows are dropped before computing bias/se (defensive:
    `per_bin_stats` only emits a finite diff once its upstream `bin_pairs`
    has dropped non-finite rows), and `n_bins` reports the count actually
    used, not the row count of `bins`.

    `n_eff` is capped at `n_bins`: `effective_n`'s Bartlett formula
    `n*(1-r1)/(1+r1)` can exceed `n` when the lag-1 autocorrelation of the
    diff series is slightly negative (as happens when averaging several
    noisy passes leaves a near-white residual around the constant bias). An
    effective sample size larger than the nominal one is not meaningful, so
    capping is the conservative choice (an uncapped n_eff would make the CI
    too narrow).
    """
    ordered = bins.sort_values('bin_center', kind='mergesort')
    diff = ordered['diff']
    diff = diff[np.isfinite(diff.to_numpy(float))]
    n_bins = int(len(diff))
    bias = float(diff.mean())
    n_eff_info = effective_n(diff)
    n_eff = float(min(n_bins, n_eff_info['n_eff']))
    se = float(diff.std(ddof=1)) / np.sqrt(n_eff)
    dof = max(1, n_eff - 1)
    t_crit = float(sps.t.ppf(0.5 + confidence / 2.0, dof))
    return {
        'bias': bias,
        'se': float(se),
        'ci_low': bias - t_crit * se,
        'ci_high': bias + t_crit * se,
        'n_bins': n_bins,
        'n_eff': n_eff,
        'confidence': float(confidence),
    }


def speed_effect(binned: pd.DataFrame, min_speed_spread_kmh: float = 3.0) -> dict | None:
    """
    Demeaned (within-bin fixed-effects) slope of diff on speed, using only
    bins driven by >=2 passes.

    Deviation from the brief (Ruling A): `diff` is computed row-level, per
    pass against its OWN matched window's iri_ref
    (`diff_ib = iri_multi_ib - iri_ref_ib`), not against the bin's pooled
    iri_ref. This removes window-selection variance (which window inside the
    bin a given pass happened to match) from the estimator; when passes'
    matched windows coincide, the bin's constant iri_ref cancels out in the
    demeaning anyway, so this is never worse and is better whenever windows
    do not coincide exactly.

    Returns `None` when:
    - the fleet's per-pass mean speeds barely vary (spread below
      `min_speed_spread_kmh`) -- the slope would be unidentified/noise-dominated;
    - no bin is covered by >=2 passes -- there is nothing to demean (avoids
      `np.concatenate([])` raising);
    - every within-bin speed is identical, i.e. `sum(x*x) == 0` -- the
      slope's denominator would be 0, giving NaN/inf instead of a real
      "no information" signal.

    stderr's dof (Ruling B) is `n_rows - n_bins - 1`, clamped to >=1: each
    bin's fixed effect (the within-bin mean subtracted from y and x)
    consumes one degree of freedom, on top of the one the slope itself
    consumes; `n_rows - 1` alone over-counts the residual dof and
    understates stderr.
    """
    collapsed = _collapse_duplicate_passes(binned)
    pass_speeds = collapsed.groupby('run_id')['mean_speed_kmh'].mean()
    speed_spread = float(pass_speeds.std(ddof=1)) if len(pass_speeds) >= 2 else 0.0
    if speed_spread < min_speed_spread_kmh:
        return None

    multi_pass_bins = collapsed.groupby('bin_center').filter(lambda g: g['run_id'].nunique() >= 2)
    if multi_pass_bins.empty:
        return None

    x_parts, y_parts = [], []
    for _, group in multi_pass_bins.groupby('bin_center'):
        diff_ib = group['iri_multi'].to_numpy(float) - group['iri_ref'].to_numpy(float)
        speed_ib = group['mean_speed_kmh'].to_numpy(float)
        x_parts.append(speed_ib - speed_ib.mean())
        y_parts.append(diff_ib - diff_ib.mean())

    x = np.concatenate(x_parts)
    y = np.concatenate(y_parts)
    sum_xx = float(np.sum(x * x))
    if sum_xx == 0:
        return None

    n_rows = int(len(x))
    n_bins = int(multi_pass_bins['bin_center'].nunique())
    dof = max(1, n_rows - n_bins - 1)
    slope = float(np.sum(x * y) / sum_xx)
    stderr = float(np.sqrt(np.sum((y - slope * x) ** 2) / dof / sum_xx))
    return {
        'slope_iri_per_kmh': slope,
        'stderr': stderr,
        'n_rows': n_rows,
        'n_bins': n_bins,
        'speed_spread_kmh': speed_spread,
    }

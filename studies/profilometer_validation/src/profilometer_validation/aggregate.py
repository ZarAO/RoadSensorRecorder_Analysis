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

All functions are pure: DataFrame in, DataFrame/dict out. Dict values are
plain floats/ints/None (JSON-serializable), never pandas/numpy scalars.
"""

import numpy as np
import pandas as pd
from scipy import stats as sps

from .calibrate import effective_n

BIN_WIDTH_M = 100.0


def bin_pairs(pairs: pd.DataFrame, bin_width_m: float = BIN_WIDTH_M) -> pd.DataFrame:
    """Assign each row to a fixed-width bin on the reference chainage."""
    out = pairs.copy()
    out['bin_center'] = (
        np.floor(out['chainage_m'].to_numpy(float) / bin_width_m) * bin_width_m
        + bin_width_m / 2.0
    )
    return out


def per_bin_stats(binned: pd.DataFrame) -> pd.DataFrame:
    """One row per bin_center (ascending), pooling all passes that hit it."""
    rows = []
    for bin_center, group in binned.groupby('bin_center'):
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
    out = pd.DataFrame(rows).sort_values('bin_center', kind='mergesort').reset_index(drop=True)
    out['diff'] = out['mean_iri'] - out['iri_ref']
    return out


def repeatability_sd(binned: pd.DataFrame) -> dict:
    """Pooled within-bin std over bins driven more than once."""
    variances = []
    for _, group in binned.groupby('bin_center'):
        iri_multi = group['iri_multi'].to_numpy(float)
        if group['run_id'].nunique() >= 2:
            variances.append(np.var(iri_multi, ddof=1))
    if not variances:
        return {'sd': None, 'n_bins_used': 0}
    return {'sd': float(np.sqrt(np.mean(variances))), 'n_bins_used': int(len(variances))}


def bias_with_ci(bins: pd.DataFrame, confidence: float = 0.95) -> dict:
    """Mean bias with a t-CI whose dof uses the Bartlett effective n."""
    ordered = bins.sort_values('bin_center', kind='mergesort')
    diff = ordered['diff']
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
    bins driven by >=2 passes. None when the fleet's per-pass speeds barely
    vary (the slope would be unidentified/noise-dominated).
    """
    pass_speeds = binned.groupby('run_id')['mean_speed_kmh'].mean()
    speed_spread = float(pass_speeds.std(ddof=1)) if len(pass_speeds) >= 2 else 0.0
    if speed_spread < min_speed_spread_kmh:
        return None

    multi_pass_bins = binned.groupby('bin_center').filter(lambda g: g['run_id'].nunique() >= 2)
    x_parts, y_parts = [], []
    for _, group in multi_pass_bins.groupby('bin_center'):
        diff_ib = group['iri_multi'].to_numpy(float) - group['iri_ref'].to_numpy(float)
        speed_ib = group['mean_speed_kmh'].to_numpy(float)
        x_parts.append(speed_ib - speed_ib.mean())
        y_parts.append(diff_ib - diff_ib.mean())

    x = np.concatenate(x_parts)
    y = np.concatenate(y_parts)
    n_rows = int(len(x))
    slope = float(np.sum(x * y) / np.sum(x * x))
    stderr = float(np.sqrt(np.sum((y - slope * x) ** 2) / (n_rows - 1) / np.sum(x * x)))
    return {
        'slope_iri_per_kmh': slope,
        'stderr': stderr,
        'n_rows': n_rows,
        'n_bins': int(multi_pass_bins['bin_center'].nunique()),
        'speed_spread_kmh': speed_spread,
    }

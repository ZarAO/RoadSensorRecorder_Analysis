"""
Validation statistics and Eq.3 calibration fits (spec §4-§5).

All functions are pure: DataFrame in, plain dict out (JSON-serializable).
The Eq.3 input column is the pipeline's own scalar (`psd_sqrt_scalar`,
mean_psd_sqrt mode, band 0.5-6 Hz, post distress-removal).
"""

import numpy as np
import pandas as pd
from scipy import stats as sps

SQRT_PSD_COL = 'psd_sqrt_scalar'
REF_COL = 'iri_ref'


def _clean(pairs: pd.DataFrame, cols) -> pd.DataFrame:
    return pairs.dropna(subset=list(cols))


def validation_stats(pairs: pd.DataFrame, metric_col: str,
                     ref_col: str = REF_COL) -> dict:
    """Rank/linear agreement of a smartphone metric against the reference."""
    df = _clean(pairs, [metric_col, ref_col])
    metric = df[metric_col].to_numpy(float)
    ref = df[ref_col].to_numpy(float)
    spearman = sps.spearmanr(metric, ref)
    pearson = sps.pearsonr(metric, ref)
    err = metric - ref
    return {
        'n': int(len(df)),
        'spearman_rho': float(spearman.statistic),
        'spearman_p': float(spearman.pvalue),
        'pearson_r': float(pearson.statistic),
        'pearson_p': float(pearson.pvalue),
        'bias': float(np.mean(err)),
        'mae': float(np.mean(np.abs(err))),
        'rmse': float(np.sqrt(np.mean(err ** 2))),
    }


def bland_altman(pairs: pd.DataFrame, metric_col: str,
                 ref_col: str = REF_COL) -> dict:
    """Bias and 95% limits of agreement (metric - reference)."""
    df = _clean(pairs, [metric_col, ref_col])
    diff = df[metric_col].to_numpy(float) - df[ref_col].to_numpy(float)
    bias = float(np.mean(diff))
    sd = float(np.std(diff, ddof=1)) if len(diff) > 1 else 0.0
    return {
        'n': int(len(diff)),
        'bias': bias,
        'sd': sd,
        'loa_low': bias - 1.96 * sd,
        'loa_high': bias + 1.96 * sd,
    }


def _ols_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    err = y_pred - y_true
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    return {
        'r2': 1.0 - ss_res / ss_tot if ss_tot > 0 else float('nan'),
        'mae': float(np.mean(np.abs(err))),
        'rmse': float(np.sqrt(np.mean(err ** 2))),
    }


def fit_eq3(pairs: pd.DataFrame) -> dict:
    """
    IRI_ref = A * sqrtPSD + B: OLS (primary) + Theil-Sen (robustness check).
    """
    df = _clean(pairs, [SQRT_PSD_COL, REF_COL])
    x = df[SQRT_PSD_COL].to_numpy(float)
    y = df[REF_COL].to_numpy(float)

    ols = sps.linregress(x, y)
    ts = sps.theilslopes(y, x)
    result = {
        'A': float(ols.slope),
        'B': float(ols.intercept),
        'A_stderr': float(ols.stderr),
        'B_stderr': float(ols.intercept_stderr),
        'A_theil_sen': float(ts.slope),
        'B_theil_sen': float(ts.intercept),
        'n': int(len(df)),
    }
    result.update(_ols_metrics(y, ols.slope * x + ols.intercept))
    return result


def loro(pairs: pd.DataFrame, road_col: str = 'road') -> dict:
    """
    Leave-one-road-out: fit Eq.3 on the other road(s), evaluate on the held-out
    one. Returns {held_out_road: {A_train, B_train, r2, mae, rmse, n_test}}.
    """
    result = {}
    for road in sorted(pairs[road_col].unique()):
        train = pairs[pairs[road_col] != road]
        test = _clean(pairs[pairs[road_col] == road], [SQRT_PSD_COL, REF_COL])
        fit = fit_eq3(train)
        x = test[SQRT_PSD_COL].to_numpy(float)
        y = test[REF_COL].to_numpy(float)
        entry = {
            'A_train': fit['A'],
            'B_train': fit['B'],
            'n_train': fit['n'],
            'n_test': int(len(test)),
        }
        entry.update(_ols_metrics(y, fit['A'] * x + fit['B']))
        result[road] = entry
    return result


def fit_grms_speed(pairs: pd.DataFrame) -> dict:
    """
    P0.2-lite: IRI_ref = a*grms + b*v_kmh + c (multivariate OLS via lstsq).
    """
    df = _clean(pairs, ['grms', 'mean_speed_kmh', REF_COL])
    design = np.column_stack([
        df['grms'].to_numpy(float),
        df['mean_speed_kmh'].to_numpy(float),
        np.ones(len(df)),
    ])
    y = df[REF_COL].to_numpy(float)
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    result = {
        'a_grms': float(coef[0]),
        'b_speed': float(coef[1]),
        'c_const': float(coef[2]),
        'n': int(len(df)),
    }
    result.update(_ols_metrics(y, design @ coef))
    return result

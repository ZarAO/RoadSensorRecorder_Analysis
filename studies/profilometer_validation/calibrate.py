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


def fit_eq3_speed(pairs: pd.DataFrame) -> dict:
    """
    Speed-augmented Eq.3: IRI_ref = A*sqrtPSD + C*v_kmh + B. Quantifies how
    much of Eq.3's residual is the missing speed term (naturalistic driving
    slows down exactly on the worst spots, suppressing the excitation).
    """
    df = _clean(pairs, [SQRT_PSD_COL, 'mean_speed_kmh', REF_COL])
    design = np.column_stack([
        df[SQRT_PSD_COL].to_numpy(float),
        df['mean_speed_kmh'].to_numpy(float),
        np.ones(len(df)),
    ])
    y = df[REF_COL].to_numpy(float)
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    result = {
        'A': float(coef[0]),
        'C_speed': float(coef[1]),
        'B': float(coef[2]),
        'n': int(len(df)),
    }
    result.update(_ols_metrics(y, design @ coef))
    return result


def fit_linear(pairs: pd.DataFrame, cols: list, ref_col: str = REF_COL) -> dict:
    """OLS with intercept over arbitrary predictor columns (lstsq)."""
    df = _clean(pairs, cols + [ref_col])
    design = np.column_stack(
        [df[c].to_numpy(float) for c in cols] + [np.ones(len(df))])
    y = df[ref_col].to_numpy(float)
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    result = {'coef': {c: float(v) for c, v in zip(cols, coef[:-1])},
              'intercept': float(coef[-1]), 'n': int(len(df))}
    result.update(_ols_metrics(y, design @ coef))
    return result


def loro_linear(pairs: pd.DataFrame, cols: list, road_col: str = 'road') -> dict:
    """Generic leave-one-road-out for a linear model over `cols`."""
    result = {}
    for road in sorted(pairs[road_col].unique()):
        train = pairs[pairs[road_col] != road]
        test = _clean(pairs[pairs[road_col] == road], cols + [REF_COL])
        fit = fit_linear(train, cols)
        design = np.column_stack(
            [test[c].to_numpy(float) for c in cols] + [np.ones(len(test))])
        coef = np.array([fit['coef'][c] for c in cols] + [fit['intercept']])
        y = test[REF_COL].to_numpy(float)
        entry = {'train_fit': fit, 'n_test': int(len(test))}
        entry.update(_ols_metrics(y, design @ coef))
        result[road] = entry
    return result


def loro_bias_correction(pairs: pd.DataFrame, metric_col: str = 'iri_multi',
                         road_col: str = 'road') -> dict:
    """
    Out-of-sample check of the constant bias correction: the offset is fitted
    on the other road and applied to the held-out one (the in-sample corrected
    MAE is optimistic by construction).
    """
    result = {}
    for road in sorted(pairs[road_col].unique()):
        train = pairs[pairs[road_col] != road]
        test = pairs[pairs[road_col] == road]
        k = float((train[metric_col] - train[REF_COL]).mean())
        err = (test[metric_col] - k) - test[REF_COL]
        result[road] = {
            'k_train': k,
            'mae': float(err.abs().mean()),
            'rmse': float(np.sqrt((err ** 2).mean())),
            'n_test': int(len(test)),
        }
    return result


def effective_n(series: pd.Series) -> dict:
    """
    Bartlett-style effective sample size under lag-1 autocorrelation:
    n_eff = n * (1 - r1) / (1 + r1). Consecutive 100 m windows on one road are
    autocorrelated, so nominal-n p-values overstate precision.
    """
    x = series.to_numpy(float)
    n = len(x)
    if n < 3:
        return {'n': n, 'lag1_autocorr': float('nan'), 'n_eff': n}
    x0, x1 = x[:-1] - x.mean(), x[1:] - x.mean()
    denom = float(np.sum((x - x.mean()) ** 2))
    r1 = float(np.sum(x0 * x1) / denom) if denom > 0 else 0.0
    n_eff = n * (1 - r1) / (1 + r1) if abs(1 + r1) > 1e-12 else float(n)
    return {'n': n, 'lag1_autocorr': r1, 'n_eff': float(max(1.0, n_eff))}


def influence_on_eq3(pairs: pd.DataFrame, drop_counts=(1, 5)) -> dict:
    """Sensitivity of the pooled Eq.3 slope to the roughest (leverage) pairs."""
    out = {'full': {k: fit_eq3(pairs)[k] for k in ('A', 'B', 'r2', 'n')}}
    ranked = pairs.sort_values(REF_COL, ascending=False)
    for k in drop_counts:
        subset = ranked.iloc[k:]
        fit = fit_eq3(subset)
        out[f'drop_{k}_roughest'] = {key: fit[key] for key in ('A', 'B', 'r2', 'n')}
    return out

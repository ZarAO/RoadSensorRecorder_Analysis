"""
Calibration model of the smartphone IRI estimate
(spec docs/superpowers/specs/2026-11-15-calibration-model-and-ablation-design.md):

    IRI_cal = max(0, gamma * [R - beta * (v - v0)] + delta)              (M1)

R is the UNCLIPPED guidebook predictor (analyzer column `iri_multi_raw`,
Eq.6 nominal); the published `iri_multi = max(0, R)` loses the information
below zero, so the model acts on R and clips last.

- beta: within-bin (fixed-effects) speed slope of R across passes of the SAME
  section (aggregate.speed_effect on the unclipped column) - identified by the
  survey design, free of the driver-slows-on-bad-road endogeneity;
- gamma, delta: inverse calibration, OLS of the reference on the speed-
  normalised predictor across bins of the training sections;
- M2 (pre-declared alternative): a noise floor G0 removed from Grms in
  quadrature before the book coefficient is applied; chosen over M1 only by
  held-out error.

Bias-only correction is the special case gamma = 1, beta = 0 (applied to the
clipped value, as published). All functions are pure.
"""

import dataclasses

import numpy as np
import pandas as pd
from scipy import stats as sps

from profilometer_validation.aggregate import bin_pairs, speed_effect

R_COL = 'iri_multi_raw'
REF_COL = 'iri_ref'
SPEED_COL = 'mean_speed_kmh'
V0_KMH = 50.0
EQ6_GRMS_COEF = 50.32          # guidebook Eq.6 Grms coefficient (pinned by test)
ROUGH_THRESHOLD = 6.0          # m/km, same as calibrate.ranking_agreement
G0_GRID = tuple(np.round(np.arange(0.0, 0.0301, 0.0025), 4))


@dataclasses.dataclass(frozen=True)
class CalibrationParams:
    gamma: float
    delta: float
    beta: float = 0.0
    v0: float = V0_KMH
    g0: float = 0.0
    model: str = 'M1'

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def predictor(df: pd.DataFrame, beta: float = 0.0, v0: float = V0_KMH,
              g0: float = 0.0) -> np.ndarray:
    """R_v0 = R(G0) - beta (v - v0); R(G0) takes the noise floor G0 out of
    Grms in quadrature (G0 = 0 gives R itself)."""
    r = df[R_COL].to_numpy(float)
    if g0 > 0:
        grms = df['grms'].to_numpy(float)
        road = np.sqrt(np.maximum(0.0, grms ** 2 - g0 ** 2))
        r = r - EQ6_GRMS_COEF * (grms - road)
    return r - beta * (df[SPEED_COL].to_numpy(float) - v0)


def estimate_beta(passes: pd.DataFrame, section_col: str = 'section',
                  min_speed_spread_kmh: float = 3.0) -> dict | None:
    """
    beta from passes of the same section(s) at different speeds: pairs with
    run_id, chainage_m, iri_ref, iri_multi, iri_multi_raw, mean_speed_kmh.
    Sections are kept apart (their chainages are offset) so a bin never mixes
    two sections. None when the design does not identify it (single passes,
    no speed spread).
    """
    frame = passes.copy()
    if section_col in frame.columns:
        codes = {s: i for i, s in enumerate(sorted(frame[section_col].unique()))}
        frame['chainage_m'] = frame['chainage_m'] + 1e7 * frame[section_col].map(codes)
    return speed_effect(bin_pairs(frame), min_speed_spread_kmh, metric_col=R_COL)


def clean_pairs(df: pd.DataFrame) -> pd.DataFrame:
    """The pairs every model is fitted and scored on (finite R, reference, speed)."""
    return df.dropna(subset=[R_COL, REF_COL, SPEED_COL])



def fit(df: pd.DataFrame, beta: float = 0.0, v0: float = V0_KMH, g0: float = 0.0,
        model: str = 'M1') -> CalibrationParams:
    """gamma, delta by OLS of the reference on the speed-normalised predictor."""
    d = clean_pairs(df)
    if len(d) < 3:
        raise ValueError('need at least 3 pairs to fit gamma and delta')
    x = predictor(d, beta, v0, g0)
    if np.ptp(x) == 0:
        raise ValueError('predictor is constant: gamma is not identified')
    gamma, delta = np.polyfit(x, d[REF_COL].to_numpy(float), 1)
    return CalibrationParams(float(gamma), float(delta), beta, v0, g0, model)


def fit_m2(df: pd.DataFrame, beta: float = 0.0, v0: float = V0_KMH,
           g0_grid=G0_GRID) -> CalibrationParams:
    """M2: G0 chosen on the TRAINING pairs by the least squared residual."""
    d = clean_pairs(df)
    best = None
    for g0 in g0_grid:
        try:
            params = fit(d, beta, v0, float(g0), model='M2')
        except ValueError:
            continue
        sse = float(np.sum((predict(d, params, clip=False) - d[REF_COL]) ** 2))
        if best is None or sse < best[0]:
            best = (sse, params)
    if best is None:
        raise ValueError('M2 could not be fitted on any G0 of the grid')
    return best[1]


def predict(df: pd.DataFrame, params: CalibrationParams, clip: bool = True) -> np.ndarray:
    value = params.gamma * predictor(df, params.beta, params.v0, params.g0) + params.delta
    return np.maximum(0.0, value) if clip else value


def fit_bias_only(df: pd.DataFrame) -> float:
    """The published correction: one constant on the clipped value."""
    d = clean_pairs(df)
    return float((d[REF_COL] - np.maximum(0.0, d[R_COL])).mean())


def evaluate(pred: np.ndarray, ref: np.ndarray) -> dict:
    pred, ref = np.asarray(pred, float), np.asarray(ref, float)
    err = pred - ref
    rough = ref >= ROUGH_THRESHOLD
    rho = sps.spearmanr(pred, ref).statistic if np.ptp(pred) > 0 else float('nan')
    return {
        'n': int(len(ref)),
        'mae': float(np.mean(np.abs(err))),
        'bias': float(np.mean(err)),
        'rmse': float(np.sqrt(np.mean(err ** 2))),
        'spearman_rho': float(rho),
        'rough_n': int(rough.sum()),
        'rough_pred_to_ref': float(np.mean(pred[rough] / ref[rough])) if rough.any() else None,
    }


MODELS = ('book', 'bias_only', 'M1', 'M2')


def fit_and_predict(train: pd.DataFrame, test: pd.DataFrame, model: str,
                    beta: float = 0.0, v0: float = V0_KMH):
    """(params dict, predictions on test) for one model fitted on train."""
    train, test = clean_pairs(train), clean_pairs(test)
    if model == 'book':
        return {}, np.maximum(0.0, test[R_COL].to_numpy(float))
    if model == 'bias_only':
        k = fit_bias_only(train)
        return {'k': k}, np.maximum(0.0, test[R_COL].to_numpy(float)) + k
    params = fit(train, beta, v0) if model == 'M1' else fit_m2(train, beta, v0)
    return params.to_dict(), predict(test, params)


def holdout(df: pd.DataFrame, train_mask, models=MODELS, beta: float = 0.0,
            v0: float = V0_KMH) -> dict:
    """Fit every model on df[train_mask], evaluate on the rest."""
    train_mask = np.asarray(train_mask, bool)
    train, test = clean_pairs(df[train_mask]), clean_pairs(df[~train_mask])
    out = {}
    for model in models:
        params, pred = fit_and_predict(train, test, model, beta, v0)
        out[model] = {'params': params, **evaluate(pred, test[REF_COL].to_numpy(float))}
    return out


def leave_one_group_out(df: pd.DataFrame, group_col: str, models=MODELS,
                        beta: float = 0.0, v0: float = V0_KMH) -> dict:
    return {str(g): holdout(df, df[group_col] != g, models, beta, v0)
            for g in sorted(df[group_col].unique())}


def spatial_blocks(df: pd.DataFrame, section_col: str = 'road', block_m: float = 200.0) -> pd.Series:
    """Block id = section + chainage block, so autocorrelated neighbours stay together."""
    return (df[section_col].astype(str) + ':'
            + np.floor(df['chainage_m'].to_numpy(float) / block_m).astype(int).astype(str))


def block_cv(df: pd.DataFrame, n_folds: int = 5, section_col: str = 'road',
             block_m: float = 200.0, models=MODELS, beta: float = 0.0,
             v0: float = V0_KMH) -> dict:
    """K-fold CV over spatial blocks (blocks assigned to folds in chainage order
    per section, round-robin): pooled held-out predictions per model."""
    d = clean_pairs(df).copy()
    d['_block'] = spatial_blocks(d, section_col, block_m)
    order = d.drop_duplicates('_block').sort_values([section_col, 'chainage_m'])['_block']
    fold_of = {block: i % n_folds for i, block in enumerate(order)}
    d['_fold'] = d['_block'].map(fold_of)
    preds = {m: np.full(len(d), np.nan) for m in models}
    for fold in range(n_folds):
        test = (d['_fold'] == fold).to_numpy()
        if not test.any() or test.all():
            continue
        for model in models:
            _, p = fit_and_predict(d[~test], d[test], model, beta, v0)
            preds[model][test] = p
    ref = d[REF_COL].to_numpy(float)
    return {m: evaluate(preds[m], ref) for m in models}


def bootstrap_params(df: pd.DataFrame, n_boot: int = 1000, seed: int = 20261115,
                     section_col: str = 'road', block_m: float = 200.0,
                     beta: float = 0.0, v0: float = V0_KMH, confidence: float = 0.95) -> dict:
    """Percentile CI of gamma and delta, resampling spatial blocks with replacement."""
    d = clean_pairs(df).copy()
    d['_block'] = spatial_blocks(d, section_col, block_m)
    blocks = d['_block'].unique()
    groups = {b: g for b, g in d.groupby('_block')}
    rng = np.random.default_rng(seed)
    gammas, deltas = [], []
    for _ in range(n_boot):
        sample = pd.concat([groups[b] for b in rng.choice(blocks, size=len(blocks))])
        try:
            p = fit(sample, beta, v0)
        except ValueError:
            continue
        gammas.append(p.gamma)
        deltas.append(p.delta)
    lo, hi = (1 - confidence) / 2 * 100, (1 + confidence) / 2 * 100
    point = fit(d, beta, v0)
    return {
        'gamma': point.gamma, 'gamma_ci': [float(np.percentile(gammas, lo)), float(np.percentile(gammas, hi))],
        'delta': point.delta, 'delta_ci': [float(np.percentile(deltas, lo)), float(np.percentile(deltas, hi))],
        'n_blocks': int(len(blocks)), 'n_boot_ok': int(len(gammas)), 'seed': seed,
        'block_m': block_m, 'confidence': confidence,
    }

"""
Base-vs-improved (ablation) metrics
(spec docs/superpowers/specs/2026-11-15-calibration-model-and-ablation-design.md §4).

Pure functions over matched pairs of one method variant; run_study.py does the
I/O. Every variant is scored with the published correction applied out of
sample: the offset is fitted on the OTHER road of the same vehicle
(calibrate.loro_bias_correction), so no number reuses the pairs it is scored on.
"""

import numpy as np
import pandas as pd
from scipy import stats as sps

from profilometer_validation.calibrate import REF_COL, loro_bias_correction

METRIC_COL = 'iri_multi'


def variant_metrics(pairs: pd.DataFrame) -> dict:
    """
    Per 'vehicle|road': pairs, Spearman rho, the other-road offset k and the
    corrected MAE, segment length span, and the split of the error into
    segments inside / outside the 20-100 km/h corridor (speed_valid).
    pairs needs vehicle, road, iri_multi, iri_ref, speed_valid, length_m.
    """
    if pairs['speed_valid'].isna().any():
        raise ValueError('speed_valid has missing values: the segment merge did not match')
    d = pairs.dropna(subset=[METRIC_COL, REF_COL])
    out = {}
    for vehicle, vehicle_pairs in d.groupby('vehicle'):
        loro = (loro_bias_correction(vehicle_pairs, metric_col=METRIC_COL)
                if vehicle_pairs['road'].nunique() >= 2 else {})
        for road, group in vehicle_pairs.groupby('road'):
            k = loro.get(road, {}).get('k_train')
            err = (group[METRIC_COL] - k) - group[REF_COL] if k is not None else None
            outside = group['speed_valid'].eq(False)
            out[f'{vehicle}|{road}'] = {
                'n_pairs': int(len(group)),
                'spearman_rho': float(sps.spearmanr(group[METRIC_COL], group[REF_COL]).statistic),
                'k_other_road': k,
                'loro_bias_corrected_mae': float(err.abs().mean()) if err is not None else None,
                'segment_length_m': {'min': float(group['length_m'].min()),
                                     'max': float(group['length_m'].max())},
                'outside_20_100_kmh': {
                    'n': int(outside.sum()),
                    'mae': (float(err[outside].abs().mean())
                            if err is not None and outside.any() else None),
                    'mae_inside': (float(err[~outside].abs().mean())
                                   if err is not None and (~outside).any() else None),
                },
            }
    return out


def speed_range_by_group(pairs: pd.DataFrame) -> dict:
    """Slowest and fastest matched segment per (vehicle, road): the speed regime a
    variant covers. Fixed-duration windows are lost at BOTH ends (too short to
    cover the 100 m base when slow, longer than the matcher's window cap when
    fast), so a fair comparison needs both bounds."""
    grouped = pairs.groupby(['vehicle', 'road'])['mean_speed_kmh']
    return {key: (float(lo), float(hi)) for (key, lo), (_, hi) in zip(grouped.min().items(),
                                                                      grouped.max().items())}


def restrict_to_regime(pairs: pd.DataFrame, speed_range: dict) -> pd.DataFrame:
    """Keep pairs inside the per-(vehicle, road) speed range; a group absent from
    speed_range keeps nothing."""
    bounds = [speed_range.get((v, r), (np.inf, -np.inf)) for v, r in zip(pairs['vehicle'], pairs['road'])]
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    speed = pairs['mean_speed_kmh'].to_numpy(float)
    return pairs[(speed >= lo) & (speed <= hi)]

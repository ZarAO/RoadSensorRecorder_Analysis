"""
End-to-end validation/calibration study (spec:
docs/superpowers/specs/2026-08-20-profilometer-validation-design.md).

Deterministic: same inputs -> byte-identical matched_pairs.csv and stats.json.
Run from the repo root:
    .venv/Scripts/python.exe studies/profilometer_validation/run_study.py
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

STUDY_DIR = Path(__file__).resolve().parent
REPO_ROOT = STUDY_DIR.parents[1]
sys.path.insert(0, str(STUDY_DIR))

from calibrate import (  # noqa: E402
    bland_altman, fit_eq3, fit_eq3_speed, fit_grms_speed, loro, validation_stats,
)
from match import (  # noqa: E402
    REFERENCE_CHANNELS, load_form_10m, load_form_intervals, match_segments,
    segment_midpoints_from_geojson, windowed_reference,
)

# Study inputs (fixed by the spec §2): the two ground-truth pairings
DATASETS = [
    {
        'road': 'М-03',
        'form_csv': 'storage/field_measurements/derived/М-03_км19-км30смуга2_100.csv',
        'form_10m_csv': 'storage/field_measurements/derived/М-03_км19-км30смуга2_10.csv',
        'segments_csv': 'storage/results/field_new_sensor_data_20260820_100807/road_segments.csv',
        'recording_csv': 'storage/field_measurements/my_measurements/new/sensor_data_20260820_100807.csv',
    },
    {
        'road': 'Т1016',
        'form_csv': 'storage/field_measurements/derived/Т1016_км17-км0+200зворотній_100.csv',
        'form_10m_csv': 'storage/field_measurements/derived/Т1016_км17-км0+200зворотній_10.csv',
        'segments_csv': 'storage/results/field_new_sensor_data_20260820_102552/road_segments.csv',
        'recording_csv': 'storage/field_measurements/my_measurements/new/sensor_data_20260820_102552.csv',
    },
]

TOLERANCE_PRIMARY_M = 60.0
TOLERANCE_SENSITIVITY_M = [40.0, 60.0, 80.0]
GATES = {'r2_min': 0.85, 'mae_max': 0.5}
COEFFICIENT_SET_NAME = 'UA_2026_TRANSIT_S948B'

PAIR_COLUMNS = ['road', 'seg_id', 'chainage_m', 'match_dist_m', 'n_ref_rows',
                'iri_ref', 'psd_sqrt_scalar', 'grms', 'mean_speed_kmh',
                'iri_psd_raw', 'iri_multi']


def _segment_geometry(ds) -> pd.DataFrame:
    segments = pd.read_csv(REPO_ROOT / ds['segments_csv'])
    # Segment geometry from the run's own geojson (same s-grid as the metrics)
    geojson = Path(REPO_ROOT / ds['segments_csv']).parent / 'roughness.geojson'
    return segment_midpoints_from_geojson(segments, str(geojson))


def build_pairs() -> pd.DataFrame:
    """
    Primary pairing: windowed 10 m reference (grid-phase-free, spec §3 as
    amended after the first iteration — see study report §matching).
    """
    frames = []
    for ds in DATASETS:
        form10 = load_form_10m(str(REPO_ROOT / ds['form_10m_csv']))
        matched = windowed_reference(_segment_geometry(ds), form10)
        matched['road'] = ds['road']
        frames.append(matched[PAIR_COLUMNS])
    return pd.concat(frames, ignore_index=True)


def build_pairs_nearest_100(tolerance_m: float) -> pd.DataFrame:
    """Sensitivity variant: nearest-100 m-interval matching (grid phase kept)."""
    frames = []
    for ds in DATASETS:
        intervals = load_form_intervals(str(REPO_ROOT / ds['form_csv']))
        matched = match_segments(_segment_geometry(ds), intervals,
                                 tolerance_m=tolerance_m)
        matched['road'] = ds['road']
        keep = [c for c in PAIR_COLUMNS if c in matched.columns]
        frames.append(matched[keep])
    return pd.concat(frames, ignore_index=True)


def profilometer_noise_floor() -> dict:
    """
    Inter-channel agreement of the reference device per road at the 100 m step:
    the mean within-interval std across ch1..ch8 (how much the device disagrees
    with itself laterally) and the mean pairwise channel correlation. Serves as
    the noise floor when interpreting smartphone-vs-reference correlations.
    """
    out = {}
    for ds in DATASETS:
        df = pd.read_csv(REPO_ROOT / ds['form_csv'], encoding='utf-8')
        channels = df[REFERENCE_CHANNELS]
        corr = channels.corr(method='pearson').to_numpy()
        upper = corr[np.triu_indices_from(corr, k=1)]
        out[ds['road']] = {
            'mean_within_interval_std': float(channels.std(axis=1, ddof=1).mean()),
            'mean_iri_ref': float(channels.mean(axis=1).mean()),
            'std_iri_ref_between_intervals': float(channels.mean(axis=1).std(ddof=1)),
            'mean_pairwise_channel_pearson': float(np.mean(upper)),
            'n_intervals': int(len(df)),
        }
    return out


def per_road_and_pooled(pairs: pd.DataFrame, fn) -> dict:
    out = {'pooled': fn(pairs)}
    for road, group in pairs.groupby('road'):
        out[road] = fn(group)
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=str(STUDY_DIR / 'out'))
    parser.add_argument('--study-date', default='2026-08-20')
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Matched pairs (primary: windowed 10 m reference)
    pairs = build_pairs()
    n_per_road = pairs.groupby('road').size().to_dict()
    print(f'Matched pairs (windowed 10 m reference): {n_per_road}')

    # 2. Pre-calibration validation
    validation = {
        'sqrt_psd': per_road_and_pooled(pairs, lambda d: validation_stats(d, 'psd_sqrt_scalar')),
        'grms': per_road_and_pooled(pairs, lambda d: validation_stats(d, 'grms')),
        'iri_multi_generic': per_road_and_pooled(pairs, lambda d: validation_stats(d, 'iri_multi')),
    }
    ba_before = per_road_and_pooled(pairs, lambda d: bland_altman(d, 'iri_multi'))
    # Bias-corrected Eq.6: the fitted slopes reproduce the book's structure
    # (grms 53.1 vs 50.3, speed -0.089 vs -0.06), so a constant-offset
    # correction of iri_multi is the minimal calibration of that family
    iri_multi_bias = float((pairs['iri_multi'] - pairs['iri_ref']).mean())
    pairs['iri_multi_bias_corrected'] = pairs['iri_multi'] - iri_multi_bias
    validation['iri_multi_bias_corrected'] = per_road_and_pooled(
        pairs, lambda d: validation_stats(d, 'iri_multi_bias_corrected'))

    # 3. Calibration
    fit = fit_eq3(pairs)
    fit_per_road = {road: fit_eq3(group) for road, group in pairs.groupby('road')}
    fit_loro = loro(pairs)
    fit_grms = fit_grms_speed(pairs)
    fit_speed_aug = fit_eq3_speed(pairs)
    pairs['iri_calibrated'] = fit['A'] * pairs['psd_sqrt_scalar'] + fit['B']
    ba_after = per_road_and_pooled(pairs, lambda d: bland_altman(d, 'iri_calibrated'))
    calibrated_stats = per_road_and_pooled(pairs, lambda d: validation_stats(d, 'iri_calibrated'))

    # 4. Matching-method sensitivity: nearest-100m variant per tolerance
    sensitivity = {}
    for tol in TOLERANCE_SENSITIVITY_M:
        alt = build_pairs_nearest_100(tol)
        alt_fit = fit_eq3(alt)
        sensitivity[f'nearest100_{tol:.0f}m'] = {
            k: alt_fit[k] for k in ('A', 'B', 'r2', 'mae', 'n')}

    # 5. Gates verdict (spec §5)
    negative_calibrated = int((pairs['iri_calibrated'] < 0).sum())
    gates = {
        'r2_pooled': fit['r2'],
        'r2_gate': GATES['r2_min'],
        'r2_pass': bool(fit['r2'] > GATES['r2_min']),
        'mae_pooled': fit['mae'],
        'mae_gate': GATES['mae_max'],
        'mae_pass': bool(fit['mae'] < GATES['mae_max']),
        'negative_calibrated_iri': negative_calibrated,
        'negative_pass': bool(negative_calibrated == 0),
    }
    gates['all_pass'] = bool(gates['r2_pass'] and gates['mae_pass'] and gates['negative_pass'])

    stats = {
        'study_date': args.study_date,
        'coefficient_set': COEFFICIENT_SET_NAME,
        'tolerance_m': TOLERANCE_PRIMARY_M,
        'n_pairs': {str(k): int(v) for k, v in n_per_road.items()},
        'validation_before_calibration': validation,
        'bland_altman_iri_multi_before': ba_before,
        'iri_multi_pooled_bias': iri_multi_bias,
        'eq3_fit': fit,
        'eq3_fit_per_road': fit_per_road,
        'eq3_loro': fit_loro,
        'profilometer_noise_floor': profilometer_noise_floor(),
        'grms_speed_fit': fit_grms,
        'eq3_speed_augmented_fit': fit_speed_aug,
        'calibrated_stats': calibrated_stats,
        'bland_altman_calibrated_after': ba_after,
        'tolerance_sensitivity': sensitivity,
        'gates': gates,
    }

    # 6. Persist (sorted keys -> deterministic bytes)
    pairs_out = pairs.sort_values(['road', 'seg_id']).reset_index(drop=True)
    pairs_out.to_csv(out_dir / 'matched_pairs.csv', index=False,
                     encoding='utf-8', lineterminator='\n', float_format='%.10g')
    (out_dir / 'stats.json').write_text(
        json.dumps(stats, ensure_ascii=False, indent=1, sort_keys=True),
        encoding='utf-8')

    # 7. Figures
    from figures import bland_altman_plot, chainage_overlay, scatter_fit
    figures_dir = out_dir / 'figures'
    written = []
    written += scatter_fit(pairs, fit, figures_dir)
    written += bland_altman_plot(pairs, 'iri_multi',
                                 'До калібрування: IRI_multi (GENERIC)',
                                 figures_dir, 'fig2a_bland_altman_before')
    written += bland_altman_plot(pairs, 'iri_calibrated',
                                 'Після калібрування Eq.3',
                                 figures_dir, 'fig2b_bland_altman_after')
    for ds in DATASETS:
        written += chainage_overlay(pairs, ds['road'], figures_dir)

    # 8. UA summary report
    lines = [
        '# Звіт дослідження: смартфон vs профілометр',
        '',
        f'- Дата дослідження: {args.study_date}; набір коефіцієнтів: `{COEFFICIENT_SET_NAME}`',
        '- Пар сегмент↔еталон (віконний 10 м еталон): '
        + ', '.join(f'{k}: {v}' for k, v in sorted(n_per_road.items())),
        '',
        '## Валідація до калібрування (пул обох доріг)',
        f"- Spearman ρ (√PSD vs IRI): {validation['sqrt_psd']['pooled']['spearman_rho']:.3f} "
        f"(p={validation['sqrt_psd']['pooled']['spearman_p']:.2e})",
        f"- Pearson r (√PSD vs IRI): {validation['sqrt_psd']['pooled']['pearson_r']:.3f}",
        f"- Spearman ρ (Grms vs IRI): {validation['grms']['pooled']['spearman_rho']:.3f}",
        f"- IRI_multi (GENERIC): зсув {validation['iri_multi_generic']['pooled']['bias']:+.2f} м/км, "
        f"MAE {validation['iri_multi_generic']['pooled']['mae']:.2f} м/км",
        '',
        '## Калібрування Eq.3 (пул, OLS)',
        f"- A = {fit['A']:.4f} ± {fit['A_stderr']:.4f}; B = {fit['B']:.4f} ± {fit['B_stderr']:.4f} "
        f"(Theil–Sen: A={fit['A_theil_sen']:.4f}, B={fit['B_theil_sen']:.4f})",
        f"- R² = {fit['r2']:.3f}; MAE = {fit['mae']:.3f} м/км; RMSE = {fit['rmse']:.3f} м/км; n = {fit['n']}",
        '',
        '## Leave-one-road-out',
    ]
    for road, entry in sorted(fit_loro.items()):
        lines.append(
            f"- Тест на {road} (фіт на іншій дорозі: A={entry['A_train']:.3f}, "
            f"B={entry['B_train']:.3f}): R²={entry['r2']:.3f}, MAE={entry['mae']:.3f} м/км, "
            f"n={entry['n_test']}")
    lines += [
        '',
        '## Гейти (roadmap P0.1)',
        f"- R² > {GATES['r2_min']}: {'PASS' if gates['r2_pass'] else 'FAIL'} ({fit['r2']:.3f})",
        f"- MAE < {GATES['mae_max']} м/км: {'PASS' if gates['mae_pass'] else 'FAIL'} ({fit['mae']:.3f})",
        f"- Від'ємних каліброваних IRI: {negative_calibrated} "
        f"({'PASS' if gates['negative_pass'] else 'FAIL'})",
        f"- Підсумок: {'УСІ ГЕЙТИ ПРОЙДЕНО' if gates['all_pass'] else 'Є НЕПРОЙДЕНІ ГЕЙТИ — набір експериментальний'}",
        '',
        '_Повні числа: stats.json; пари: matched_pairs.csv; фігури: figures/_',
    ]
    (out_dir / 'study_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    print(f'✓ {out_dir / "matched_pairs.csv"}')
    print(f'✓ {out_dir / "stats.json"}')
    print(f'✓ {len(written)} figure files')
    print(f'✓ {out_dir / "study_report.md"}')
    print(f"Gates: {'ALL PASS' if gates['all_pass'] else 'NOT ALL PASSED'} "
          f"(R²={fit['r2']:.3f}, MAE={fit['mae']:.3f}, negatives={negative_calibrated})")


if __name__ == '__main__':
    main()

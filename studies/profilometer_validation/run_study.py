"""
End-to-end validation/calibration study.

Spec: docs/superpowers/specs/2026-08-20-profilometer-validation-design.md
(including Amendment A1: windowed 10 m reference as the primary matching).

Reporting principles (after the adversarial review of 2026-08-20):
- per-road numbers are the headline; pooled numbers are always labeled as
  carrying the between-road contrast (n_roads = 2, one bit of information);
- every model fitted is reported with its out-of-sample (LORO) counterpart;
- speed endogeneity is quantified with a speed-only baseline;
- no device-wide Eq.3 coefficient is claimed: the per-road slopes disagree
  in sign, so the pooled slope is a road-contrast artifact.

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

from profilometer_validation.calibrate import (
    bland_altman, effective_n, fit_eq3, fit_linear, influence_on_eq3,
    loro_bias_correction, loro_linear, validation_stats,
)
from profilometer_validation.match import (
    REFERENCE_CHANNELS, load_form_10m, load_form_intervals, match_segments,
    segment_midpoints_from_geojson, windowed_reference,
)

# Study inputs (spec §2): the two ground-truth pairings
DATASETS = [
    {
        'road': 'М-03',
        'form_csv': 'storage/field_measurements/derived/М-03_км19-км30смуга2_100.csv',
        'form_10m_csv': 'storage/field_measurements/derived/М-03_км19-км30смуга2_10.csv',
        'segments_csv': 'storage/results/field_new_sensor_data_20260820_100807/road_segments.csv',
    },
    {
        'road': 'Т1016',
        'form_csv': 'storage/field_measurements/derived/Т1016_км17-км0+200зворотній_100.csv',
        'form_10m_csv': 'storage/field_measurements/derived/Т1016_км17-км0+200зворотній_10.csv',
        'segments_csv': 'storage/results/field_new_sensor_data_20260820_102552/road_segments.csv',
    },
]

# Primary matcher parameters (windowed 10 m reference, spec Amendment A1)
MATCHING = {
    'method': 'windowed_10m_reference',
    'endpoint_tolerance_m': 60.0,
    'min_ref_rows': 9,       # audit: boundary-degraded windows (<9 rows) excluded
    'max_window_m': 160.0,
    'window_bounds': 'half-open [lo, hi)',
}
NEAREST100_TOLERANCES_M = [40.0, 60.0, 80.0]
GATES = {'r2_min': 0.85, 'mae_max': 0.5}

PAIR_COLUMNS = (['road', 'seg_id', 'chainage_m', 'match_dist_m', 'n_ref_rows',
                 'iri_ref', 'psd_sqrt_scalar', 'grms', 'mean_speed_kmh',
                 'iri_psd_raw', 'iri_multi']
                + [f'iri_ref_{c[4:]}' for c in REFERENCE_CHANNELS])

MODELS = {
    'eq3': ['psd_sqrt_scalar'],
    'eq3_speed': ['psd_sqrt_scalar', 'mean_speed_kmh'],
    'grms_speed': ['grms', 'mean_speed_kmh'],
    'speed_only': ['mean_speed_kmh'],   # endogeneity baseline, NOT a candidate
}


def _segment_geometry(ds) -> pd.DataFrame:
    segments = pd.read_csv(REPO_ROOT / ds['segments_csv'])
    geojson = Path(REPO_ROOT / ds['segments_csv']).parent / 'roughness.geojson'
    return segment_midpoints_from_geojson(segments, str(geojson))


def build_pairs() -> pd.DataFrame:
    frames = []
    for ds in DATASETS:
        form10 = load_form_10m(str(REPO_ROOT / ds['form_10m_csv']))
        matched = windowed_reference(
            _segment_geometry(ds), form10,
            endpoint_tolerance_m=MATCHING['endpoint_tolerance_m'],
            min_rows_in_window=MATCHING['min_ref_rows'],
            max_window_m=MATCHING['max_window_m'])
        matched['road'] = ds['road']
        frames.append(matched[[c for c in PAIR_COLUMNS if c in matched.columns]])
    return pd.concat(frames, ignore_index=True)


def build_pairs_nearest_100(tolerance_m: float) -> pd.DataFrame:
    """Sensitivity variant: the spec's original nearest-100 m matcher."""
    frames = []
    for ds in DATASETS:
        intervals = load_form_intervals(str(REPO_ROOT / ds['form_csv']))
        matched = match_segments(_segment_geometry(ds), intervals,
                                 tolerance_m=tolerance_m)
        matched['road'] = ds['road']
        frames.append(matched[[c for c in PAIR_COLUMNS if c in matched.columns]])
    return pd.concat(frames, ignore_index=True)


def profilometer_noise_floor() -> dict:
    """
    Reference self-agreement per road at 100 m, INCLUDING the attainable
    correlation ceiling via Spearman-Brown (composite reliability of the 8
    channels): if the ceiling is high, a null smartphone correlation is a
    genuine sensitivity failure, not reference noise.
    """
    out = {}
    for ds in DATASETS:
        df = pd.read_csv(REPO_ROOT / ds['form_csv'], encoding='utf-8')
        channels = df[REFERENCE_CHANNELS]
        corr = channels.corr(method='pearson').to_numpy()
        mean_r = float(np.mean(corr[np.triu_indices_from(corr, k=1)]))
        k = len(REFERENCE_CHANNELS)
        composite_reliability = (k * mean_r) / (1 + (k - 1) * mean_r)
        out[ds['road']] = {
            'mean_within_interval_std': float(channels.std(axis=1, ddof=1).mean()),
            'mean_iri_ref': float(channels.mean(axis=1).mean()),
            'std_iri_ref_between_intervals': float(channels.mean(axis=1).std(ddof=1)),
            'mean_pairwise_channel_pearson': mean_r,
            'composite_reliability_spearman_brown': float(composite_reliability),
            'attainable_correlation_ceiling': float(np.sqrt(composite_reliability)),
            'n_intervals': int(len(df)),
        }
    return out


def per_road_and_pooled(pairs: pd.DataFrame, fn) -> dict:
    out = {road: fn(group) for road, group in pairs.groupby('road')}
    out['pooled_CAUTION_between_road_contrast'] = fn(pairs)
    return out


def single_channel_sensitivity(pairs: pd.DataFrame) -> dict:
    """
    D1 sensitivity (spec §2): Spearman of iri_multi vs each single reference
    channel, per road — does the channel choice change the conclusion?
    """
    from scipy import stats as sps
    out = {}
    for road, group in pairs.groupby('road'):
        entry = {}
        for channel in REFERENCE_CHANNELS:
            col = f'iri_ref_{channel[4:]}'
            if col in group.columns:
                rho = sps.spearmanr(group['iri_multi'], group[col]).statistic
                entry[channel] = round(float(rho), 4)
        out[road] = entry
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default=str(STUDY_DIR / 'out'))
    parser.add_argument('--study-date', default='2026-08-20')
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    pairs = build_pairs()
    n_per_road = pairs.groupby('road').size().to_dict()
    print(f'Matched pairs (windowed 10 m reference, >= {MATCHING["min_ref_rows"]} rows): {n_per_road}')

    # --- Validation (per road first, pooled labeled) ---
    validation = {
        'sqrt_psd': per_road_and_pooled(pairs, lambda d: validation_stats(d, 'psd_sqrt_scalar')),
        'grms': per_road_and_pooled(pairs, lambda d: validation_stats(d, 'grms')),
        'iri_multi_generic': per_road_and_pooled(pairs, lambda d: validation_stats(d, 'iri_multi')),
    }
    ba_before = per_road_and_pooled(pairs, lambda d: bland_altman(d, 'iri_multi'))

    # --- All models: in-sample AND out-of-sample, plus the endogeneity baseline ---
    fits = {name: fit_linear(pairs, cols) for name, cols in MODELS.items()}
    loro_all = {name: loro_linear(pairs, cols) for name, cols in MODELS.items()}
    eq3_per_road = {road: fit_eq3(group) for road, group in pairs.groupby('road')}
    eq3_pooled = fit_eq3(pairs)   # kept for Theil-Sen + stderr diagnostics only

    # --- Bias-corrected Eq.6: in-sample AND transferred (LORO) ---
    iri_multi_bias = float((pairs['iri_multi'] - pairs['iri_ref']).mean())
    pairs['iri_multi_bias_corrected'] = pairs['iri_multi'] - iri_multi_bias
    bias_corrected_stats = per_road_and_pooled(
        pairs, lambda d: validation_stats(d, 'iri_multi_bias_corrected'))
    bias_loro = loro_bias_correction(pairs)

    # --- Diagnostics the adversarial review demanded ---
    autocorrelation = {
        road: {'iri_ref': effective_n(group.sort_values('chainage_m')['iri_ref']),
               'iri_multi': effective_n(group.sort_values('chainage_m')['iri_multi'])}
        for road, group in pairs.groupby('road')
    }
    influence = influence_on_eq3(pairs)
    channel_sensitivity = single_channel_sensitivity(pairs)

    # Calibrated column for the after-plot: the pooled line is DIAGNOSTIC ONLY
    pairs['iri_calibrated'] = eq3_pooled['A'] * pairs['psd_sqrt_scalar'] + eq3_pooled['B']
    ba_after = per_road_and_pooled(pairs, lambda d: bland_altman(d, 'iri_calibrated'))

    sensitivity_nearest = {}
    for tol in NEAREST100_TOLERANCES_M:
        alt_fit = fit_eq3(build_pairs_nearest_100(tol))
        sensitivity_nearest[f'nearest100_{tol:.0f}m'] = {
            k: alt_fit[k] for k in ('A', 'B', 'r2', 'mae', 'n')}

    # --- Gates (spec §5), honest framing ---
    gates = {
        'eq3_pooled_r2': eq3_pooled['r2'],
        'eq3_pooled_mae': eq3_pooled['mae'],
        'eq3_r2_pass': bool(eq3_pooled['r2'] > GATES['r2_min']),
        'eq3_mae_pass': bool(eq3_pooled['mae'] < GATES['mae_max']),
        'negative_calibrated_iri_note': (
            'algebraically zero for any fit with A>0, B>0 over sqrtPSD>=0 — '
            'a property of the fitted line, not empirical evidence'),
        'bias_corrected_eq6_mae_in_sample': None,   # filled below
        'bias_corrected_eq6_mae_loro': {
            road: entry['mae'] for road, entry in bias_loro.items()},
        'verdict': (
            'Eq.3 device-wide calibration NOT achievable on this data: per-road '
            'slopes disagree in sign (М-03 within-road slope ~0/negative, n.s.), '
            'so the pooled slope reflects the two-road contrast (df=1). No '
            'coefficient set is shipped. The transferable finding is ranking '
            'validity of iri_multi on the rough road and a bias correction that '
            'passes MAE<0.5 on М-03 (out-of-sample) but not on Т1016.'),
    }
    gates['bias_corrected_eq6_mae_in_sample'] = bias_corrected_stats[
        'pooled_CAUTION_between_road_contrast']['mae']

    stats = {
        'study_date': args.study_date,
        'matching': MATCHING,
        'n_pairs': {str(k): int(v) for k, v in n_per_road.items()},
        'validation': validation,
        'bland_altman_iri_multi_before': ba_before,
        'bland_altman_pooled_line_after': ba_after,
        'models_in_sample': fits,
        'models_loro': loro_all,
        'eq3_per_road': eq3_per_road,
        'eq3_pooled_diagnostic': eq3_pooled,
        'iri_multi_pooled_bias': iri_multi_bias,
        'iri_multi_bias_corrected': bias_corrected_stats,
        'bias_correction_loro': bias_loro,
        'profilometer_noise_floor': profilometer_noise_floor(),
        'autocorrelation_effective_n': autocorrelation,
        'eq3_influence_analysis': influence,
        'single_channel_sensitivity_spearman': channel_sensitivity,
        'matcher_sensitivity_nearest100': sensitivity_nearest,
        'models_fitted_count_disclosure': len(MODELS),
        'gates': gates,
    }

    pairs_out = pairs.sort_values(['road', 'seg_id']).reset_index(drop=True)
    pairs_out.to_csv(out_dir / 'matched_pairs.csv', index=False,
                     encoding='utf-8', lineterminator='\n', float_format='%.10g')
    (out_dir / 'stats.json').write_text(
        json.dumps(stats, ensure_ascii=False, indent=1, sort_keys=True),
        encoding='utf-8')

    # --- Figures ---
    from profilometer_validation.figures import bland_altman_plot, chainage_overlay, scatter_fit
    figures_dir = out_dir / 'figures'
    written = []
    written += scatter_fit(pairs, eq3_pooled, figures_dir)
    written += bland_altman_plot(pairs, 'iri_multi',
                                 'До калібрування: IRI_multi (GENERIC)',
                                 figures_dir, 'fig2a_bland_altman_before')
    written += bland_altman_plot(pairs, 'iri_multi_bias_corrected',
                                 'Після корекції зсуву Eq.6 (+1.55 м/км)',
                                 figures_dir, 'fig2b_bland_altman_bias_corrected')
    for ds in DATASETS:
        written += chainage_overlay(pairs, ds['road'], figures_dir,
                                    calibrated_col='iri_multi_bias_corrected')

    # --- UA summary (per-road first; every qualifier included) ---
    v_multi = validation['iri_multi_generic']
    nf = stats['profilometer_noise_floor']
    lines = [
        '# Звіт дослідження: смартфон vs профілометр',
        '',
        f"- Дата: {args.study_date}. Матчинг: віконний 10 м еталон "
        f"(толеранс {MATCHING['endpoint_tolerance_m']:.0f} м, вікно ≥ {MATCHING['min_ref_rows']} рядків, "
        "напіввідкриті межі). Пар: "
        + ', '.join(f'{k}: {v}' for k, v in sorted(n_per_road.items())),
        f"- Моделей підігнано: {len(MODELS)} (розкриття проти model-selection optimism); "
        'усі оцінені й in-sample, й leave-one-road-out (LORO).',
        '',
        '## Головні результати — по дорогах (чесний заголовок)',
        f"- **Т1016** (категорія 2, IRI 1.2–14.7): iri_multi vs профілометр "
        f"Spearman ρ = {v_multi['Т1016']['spearman_rho']:.3f}, Pearson r = {v_multi['Т1016']['pearson_r']:.3f} "
        f"(n = {v_multi['Т1016']['n']}; ефективний n ≈ {autocorrelation['Т1016']['iri_ref']['n_eff']:.0f} "
        'через автокореляцію) — сильна рангова валідність на дорозі з реальним діапазоном шорсткості.',
        f"- **М-03** (категорія 1, IRI 1.1–1.8): ρ = {v_multi['М-03']['spearman_rho']:.3f} (n.s.). "
        f"Стеля кореляції за надійністю еталона ≈ {nf['М-03']['attainable_correlation_ceiling']:.2f} — "
        'отже це реальна межа чутливості смартфона у вузькому діапазоні рівних доріг, а не шум еталона.',
        f"- Пул обох доріг (ρ = {v_multi['pooled_CAUTION_between_road_contrast']['spearman_rho']:.3f}) "
        'свідомо НЕ є заголовком: він несе переважно контраст «Т1016 шорсткіша за М-03» '
        '(дві дороги = один ступінь свободи між кластерами).',
        '',
        '## Ендогенність швидкості (розкриття)',
        f"- Швидкість сама по собі (без акселерометра) дає R² = {fits['speed_only']['r2']:.3f}, "
        f"MAE = {fits['speed_only']['mae']:.3f} — краще за чисту Eq.3 "
        f"(R² = {fits['eq3']['r2']:.3f}, MAE = {fits['eq3']['mae']:.3f}). Водій сповільнюється на поганих "
        'ділянках, тому будь-яка модель зі швидкістю частково міряє поведінку водія, а не лише вібрацію.',
        '',
        '## Калібрування Eq.3 — головний висновок',
        f"- Всередині доріг слопи несумісні: М-03 A = {eq3_per_road['М-03']['A']:.1f} "
        f"(r² = {eq3_per_road['М-03']['r2']:.3f}, n.s.), Т1016 A = {eq3_per_road['Т1016']['A']:.1f} "
        f"(r² = {eq3_per_road['Т1016']['r2']:.3f}). Пул A = {eq3_pooled['A']:.1f} — артефакт контрасту двох "
        f"доріг (df=1); Theil–Sen дає {eq3_pooled['A_theil_sen']:.1f}, а викидання 5 найгрубших пар "
        f"(1.8% даних) зсуває A до {influence['drop_5_roughest']['A']:.1f} — фіт нестійкий.",
        '- **Приладовий набір коефіцієнтів Eq.3 НЕ публікується** — двох доріг недостатньо; '
        f"гейти P0.1 не пройдено (R² = {eq3_pooled['r2']:.3f} < {GATES['r2_min']}, "
        f"MAE = {eq3_pooled['mae']:.3f} > {GATES['mae_max']}). Це чесний негативний результат.",
        '- Гейт «нуль від\'ємних каліброваних IRI» алгебраїчно гарантований формою фіту (A>0, B>0) '
        'і не є емпіричним свідченням.',
        '',
        '## Що працює: корекція зсуву Eq.6',
        f"- Наш незалежний фіт відтворює структуру Eq.6: коеф. Grms {fits['grms_speed']['coef']['grms']:.1f} "
        f"(книжковий 50.3), швидкості {fits['grms_speed']['coef']['mean_speed_kmh']:.3f} (книжковий −0.06) — "
        'форма рівняння підтверджується незалежними даними.',
        f"- Постійний зсув Eq.6 (GENERIC): {iri_multi_bias:+.3f} м/км. Корекція: in-sample MAE = "
        f"{bias_corrected_stats['pooled_CAUTION_between_road_contrast']['mae']:.3f} "
        f"(оптимістична за побудовою); out-of-sample (LORO): М-03 {bias_loro['М-03']['mae']:.3f} м/км "
        f"(проходить гейт 0.5), Т1016 {bias_loro['Т1016']['mae']:.3f} м/км (НЕ проходить).",
        '',
        '## LORO всіх моделей (out-of-sample MAE, м/км)',
    ]
    for name in MODELS:
        entry = loro_all[name]
        lines.append(
            f"- {name}: М-03 = {entry['М-03']['mae']:.3f}, Т1016 = {entry['Т1016']['mae']:.3f} "
            '(R² по дорогах непорівнянні — дисперсії еталона різняться у ~14 разів)')
    lines += [
        '',
        '## Чутливість',
        "- Вибір каналу еталона (Spearman iri_multi vs ch1..ch8, Т1016): "
        + ', '.join(f"{k[-3:]}: {v:.2f}" for k, v in channel_sensitivity['Т1016'].items()),
        f"- Альтернативний матчинг (nearest-100, 60 м): R² = {sensitivity_nearest['nearest100_60m']['r2']:.3f} "
        f"проти {fits['eq3']['r2']:.3f} у первинного — висновки не змінюються.",
        '',
        '_Повні числа: stats.json; пари: matched_pairs.csv; фігури: figures/_',
    ]
    (out_dir / 'study_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    print(f'✓ {out_dir / "matched_pairs.csv"}')
    print(f'✓ {out_dir / "stats.json"}')
    print(f'✓ {len(written)} figure files')
    print(f'✓ {out_dir / "study_report.md"}')
    print('Verdict:', gates['verdict'][:110] + '…')


if __name__ == '__main__':
    main()

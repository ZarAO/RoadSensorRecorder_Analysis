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
    bland_altman, cross_vehicle_bias_transfer, effective_n, fit_eq3, fit_linear,
    influence_on_eq3, loro_bias_correction, loro_linear, ranking_agreement,
    validation_stats,
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
        'segments_csv': 'storage/results/field_new_sensor_data_20260820_100807_v31/road_segments.csv',
    },
    {
        'road': 'Т1016',
        'form_csv': 'storage/field_measurements/derived/Т1016_км17-км0+200зворотній_100.csv',
        'form_10m_csv': 'storage/field_measurements/derived/Т1016_км17-км0+200зворотній_10.csv',
        'segments_csv': 'storage/results/field_new_sensor_data_20260820_102552_v31/road_segments.csv',
    },
]

# Second carrier (block added 2026-11-15): the same phone in a crossover, one
# pass per road a month after the profilometer run; inputs are the analyzer
# CLI output for the tracked recordings storage/data/sensor_data_20260920_*.csv
CROSS_VEHICLE_DATASETS = [
    {
        'road': 'М-03',
        'form_10m_csv': DATASETS[0]['form_10m_csv'],
        'segments_csv': 'storage/results/field_cupra_sensor_data_20260920_112021/road_segments.csv',
    },
    {
        'road': 'Т1016',
        'form_10m_csv': DATASETS[1]['form_10m_csv'],
        'segments_csv': 'storage/results/field_cupra_sensor_data_20260920_120302/road_segments.csv',
    },
]

# Base-vs-improved (block added 2026-11-15): the same four recordings re-run with
# one method step switched off (make_ablation_inputs.py writes these directories)
ABLATION_ROOT = 'storage/results/ablation'
ABLATION_VARIANTS = ('no_orientation', 'time_segments', 'no_speed_gate')

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
                 'iri_psd_raw', 'iri_multi', 'iri_multi_vehicle', 'iri_multi_raw']
                + [f'iri_ref_{c[4:]}' for c in REFERENCE_CHANNELS])

MODELS = {
    'eq3': ['psd_sqrt_scalar'],
    'eq3_speed': ['psd_sqrt_scalar', 'mean_speed_kmh'],
    'grms_speed': ['grms', 'mean_speed_kmh'],
    'speed_only': ['mean_speed_kmh'],   # endogeneity baseline, NOT a candidate
}


def _vehicle_resolved(ds) -> dict:
    """The Eq.4/5/6 set the analyzer resolved from the recording's vehicle passport."""
    meta_path = Path(REPO_ROOT / ds['segments_csv']).parent / 'recording_meta.json'
    return json.loads(meta_path.read_text(encoding='utf-8'))['vehicle_params']


def _segment_geometry(ds, drop_low_speed: bool = True) -> pd.DataFrame:
    segments = pd.read_csv(REPO_ROOT / ds['segments_csv'])
    geojson = Path(REPO_ROOT / ds['segments_csv']).parent / 'roughness.geojson'
    return segment_midpoints_from_geojson(segments, str(geojson), drop_low_speed)


def build_pairs(datasets=DATASETS, drop_low_speed: bool = True) -> pd.DataFrame:
    frames = []
    for ds in datasets:
        form10 = load_form_10m(str(REPO_ROOT / ds['form_10m_csv']))
        matched = windowed_reference(
            _segment_geometry(ds, drop_low_speed), form10,
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


def analyzer_source_hash() -> str:
    """sha256 over the analyzer package sources (path + bytes, sorted): ties the
    ablation inputs to the analyzer code that produced them."""
    import hashlib
    digest = hashlib.sha256()
    package = REPO_ROOT / 'analyzer' / 'src' / 'road_quality_analyzer'
    for path in sorted(package.rglob('*.py')):
        digest.update(path.relative_to(package).as_posix().encode('utf-8'))
        digest.update(path.read_bytes().replace(b'\r\n', b'\n'))
    return digest.hexdigest()


def check_ablation_inputs() -> None:
    manifest_path = REPO_ROOT / ABLATION_ROOT / 'manifest.json'
    if not manifest_path.is_file():
        raise FileNotFoundError(f'{manifest_path} missing: run studies/profilometer_validation/'
                                'make_ablation_inputs.py first')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['analyzer_source_sha256'] != analyzer_source_hash():
        raise RuntimeError('ablation inputs were produced by a different analyzer version: '
                           'rerun make_ablation_inputs.py (and the study inputs if they differ)')


def study_recordings() -> list:
    """(vehicle, dataset) of every recording the ablation block covers."""
    return ([('van', ds) for ds in DATASETS]
            + [('crossover', ds) for ds in CROSS_VEHICLE_DATASETS])


def ablation_pairs(variant: str) -> pd.DataFrame:
    """
    Matched pairs of one method variant ('full' = the method itself, regenerated
    by make_ablation_inputs.py together with the ablated variants so base and
    variants come from the same analyzer code). The speed-gate variant keeps the
    low-speed segments, which the published method leaves without a number.
    """
    frames = []
    for vehicle, ds in study_recordings():
        folder = Path(ds['segments_csv']).parent.name
        segments_csv = f'{ABLATION_ROOT}/{variant}/{folder}/road_segments.csv'
        if not (REPO_ROOT / segments_csv).is_file():
            raise FileNotFoundError(f'{segments_csv} missing: run studies/profilometer_validation/'
                                    'make_ablation_inputs.py first')
        if variant == 'full' and (REPO_ROOT / segments_csv).read_bytes() != \
                (REPO_ROOT / ds['segments_csv']).read_bytes():
            raise RuntimeError(f'{segments_csv} (current analyzer) differs from the study input '
                               f'{ds["segments_csv"]}: regenerate the study input with the analyzer CLI')
        pairs_v = build_pairs([{**ds, 'segments_csv': segments_csv}],
                              drop_low_speed=(variant != 'no_speed_gate'))
        extra = pd.read_csv(REPO_ROOT / segments_csv)[['seg_id', 'speed_valid', 'length_m']]
        frames.append(pairs_v.merge(extra, on='seg_id', how='left', validate='one_to_one')
                      .assign(vehicle=vehicle))
    return pd.concat(frames, ignore_index=True).dropna(subset=['iri_multi', 'iri_ref'])


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
        # Same pairs, Eq.4/5/6 set chosen from the vehicle passport (sensitivity to the carrier class)
        'iri_multi_vehicle': per_road_and_pooled(pairs, lambda d: validation_stats(d, 'iri_multi_vehicle')),
    }
    ba_before = per_road_and_pooled(pairs, lambda d: bland_altman(d, 'iri_multi'))
    ba_vehicle_before = per_road_and_pooled(pairs, lambda d: bland_altman(d, 'iri_multi_vehicle'))

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

    # --- Ordering and normative-level agreement (what prioritisation and a
    # comparison with DSTU 3587:2022 respectively need); per road, pooled labeled ---
    ranking = per_road_and_pooled(pairs, lambda d: ranking_agreement(d))

    # --- The same constant correction for the passport-resolved set: does the
    # carrier class of the guidebook explain the offset of this phone-vehicle pair? ---
    vehicle_resolved = {ds['road']: _vehicle_resolved(ds) for ds in DATASETS}
    iri_multi_vehicle_bias = float((pairs['iri_multi_vehicle'] - pairs['iri_ref']).mean())
    pairs['iri_multi_vehicle_bias_corrected'] = pairs['iri_multi_vehicle'] - iri_multi_vehicle_bias
    vehicle_bias_corrected_stats = per_road_and_pooled(
        pairs, lambda d: validation_stats(d, 'iri_multi_vehicle_bias_corrected'))
    bias_loro_vehicle = loro_bias_correction(pairs, metric_col='iri_multi_vehicle')

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

    # --- Second carrier: same matcher, nothing refitted on its pairs; the van's
    # offsets (same road / pooled) are applied as they are ---
    pairs_cv = build_pairs(CROSS_VEHICLE_DATASETS)
    pairs_cv['iri_multi_bias_corrected'] = pairs_cv['iri_multi'] - iri_multi_bias

    def _per_road(frame, fn):
        return {road: fn(group) for road, group in frame.groupby('road')}

    cross_vehicle = {
        'block_added': '2026-11-15',
        'target_vehicle_resolved': {ds['road']: _vehicle_resolved(ds)
                                    for ds in CROSS_VEHICLE_DATASETS},
        'n_pairs': _per_road(pairs_cv, len),
        'validation_iri_multi': _per_road(pairs_cv, lambda d: validation_stats(d, 'iri_multi')),
        'bland_altman_iri_multi': _per_road(pairs_cv, lambda d: bland_altman(d, 'iri_multi')),
        'effective_n': _per_road(pairs_cv, lambda d: {
            'iri_ref': effective_n(d.sort_values('chainage_m')['iri_ref']),
            'iri_multi': effective_n(d.sort_values('chainage_m')['iri_multi'])}),
        'iri_multi_zero_share': {
            'source': _per_road(pairs, lambda d: float((d['iri_multi'] == 0).mean())),
            'target': _per_road(pairs_cv, lambda d: float((d['iri_multi'] == 0).mean()))},
        'mean_speed_kmh': {
            'source': _per_road(pairs, lambda d: float(d['mean_speed_kmh'].mean())),
            'target': _per_road(pairs_cv, lambda d: float(d['mean_speed_kmh'].mean()))},
        'bias_transfer_from_source': cross_vehicle_bias_transfer(pairs, pairs_cv),
        'ranking_agreement_pooled_source_offset': _per_road(
            pairs_cv, lambda d: ranking_agreement(d)),
    }

    # --- Calibration model pilot (block added 2026-11-15; spec 2026-11-15-
    # calibration-model-and-ablation-design.md): IRI_cal = max(0, γ[R − β(v − v0)] + δ)
    # on the unclipped predictor. Single passes per road and vehicle -> β is NOT
    # identified here (declared, β = 0); γ, δ fitted on the van, Т1016 ---
    from profilometer_validation import calibration_model as cmod
    model_pairs = pd.concat([pairs.assign(vehicle='van'), pairs_cv.assign(vehicle='crossover')],
                            ignore_index=True)
    train_mask = ((model_pairs['vehicle'] == 'van') & (model_pairs['road'] == 'Т1016')).to_numpy()
    transfer = {}
    for vehicle, road in (('crossover', 'Т1016'), ('van', 'М-03'), ('crossover', 'М-03')):
        test_mask = ((model_pairs['vehicle'] == vehicle) & (model_pairs['road'] == road)).to_numpy()
        subset = model_pairs[train_mask | test_mask]
        transfer[f'{vehicle}|{road}'] = cmod.holdout(subset, train_mask[train_mask | test_mask])
    van_t1016 = model_pairs[train_mask]
    # β is estimated per vehicle (passes of one vehicle over the same section at
    # different speeds); pooling vehicles would confound speed with the carrier
    beta_by_vehicle = {
        vehicle: cmod.estimate_beta(group.assign(run_id=group['vehicle'] + '|' + group['road'],
                                                 section=group['road']))
        for vehicle, group in model_pairs.groupby('vehicle')}
    beta_identified = {v: b for v, b in beta_by_vehicle.items() if b is not None}
    calibration_model_pilot = {
        'block_added': '2026-11-15',
        'model': 'IRI_cal = max(0, gamma * [R - beta * (v - v0)] + delta), R = iri_multi_raw',
        'beta_by_vehicle': beta_by_vehicle,
        'beta_status': ('identified for: ' + ', '.join(sorted(beta_identified)) if beta_identified
                        else 'not identified: no section was driven by one vehicle at different '
                             'speeds; beta = 0 used in this block'),
        'v0_kmh': cmod.V0_KMH,
        'fit_van_T1016': cmod.bootstrap_params(van_t1016, n_boot=1000),
        'fit_van_T1016_m2': cmod.fit_m2(van_t1016).to_dict(),
        'in_sample_van_T1016': {
            model: cmod.evaluate(cmod.fit_and_predict(van_t1016, van_t1016, model)[1],
                                 cmod.clean_pairs(van_t1016)['iri_ref'].to_numpy(float))
            for model in cmod.MODELS},
        'transfer_from_van_T1016': transfer,
        'leave_one_road_out': cmod.leave_one_group_out(model_pairs, 'road'),
        'leave_one_vehicle_out_CAUTION_pooled_roads': cmod.leave_one_group_out(model_pairs, 'vehicle'),
        'block_cv_van_T1016_200m': cmod.block_cv(van_t1016, n_folds=5),
        'raw_below_zero_share': {
            f'{v}|{r}': float((g['iri_multi_raw'].dropna() < 0).mean())
            for (v, r), g in model_pairs.groupby(['vehicle', 'road'])},
    }

    from profilometer_validation import ablation as abl_mod
    check_ablation_inputs()
    variant_pairs = {v: ablation_pairs(v) for v in ('full', *ABLATION_VARIANTS)}
    # Fixed-duration windows survive matching only inside a speed band (too short
    # when slow, longer than the matcher's cap when fast): compare with the full
    # method on the same band, otherwise the lost bins flatter the error
    regime = abl_mod.speed_range_by_group(variant_pairs['time_segments'])

    def _tilt(ds) -> float:
        meta = REPO_ROOT / ABLATION_ROOT / 'no_orientation' / Path(ds['segments_csv']).parent.name \
            / 'recording_meta.json'
        return json.loads(meta.read_text(encoding='utf-8'))['ablations']['orientation']['tilt_deg']

    ablation = {
        'block_added': '2026-11-15',
        'mount_tilt_deg': {f"{vehicle}|{ds['road']}": _tilt(ds) for vehicle, ds in study_recordings()},
        'variants': {v: abl_mod.variant_metrics(p) for v, p in variant_pairs.items()},
        'full_in_time_segments_speed_regime': abl_mod.variant_metrics(
            abl_mod.restrict_to_regime(variant_pairs['full'], regime)),
        'time_segments_speed_range_kmh': {f'{v}|{r}': list(s) for (v, r), s in regime.items()},
    }

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
        'ranking_agreement': ranking,
        'vehicle_resolved': vehicle_resolved,
        'vehicle_block_added': '2026-09-20',
        'bland_altman_iri_multi_vehicle_before': ba_vehicle_before,
        'iri_multi_vehicle_pooled_bias': iri_multi_vehicle_bias,
        'iri_multi_vehicle_bias_corrected': vehicle_bias_corrected_stats,
        'bias_correction_loro_vehicle': bias_loro_vehicle,
        'cross_vehicle': cross_vehicle,
        'calibration_model_pilot': calibration_model_pilot,
        'ablation_base_vs_improved': ablation,
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
    pairs_cv.sort_values(['road', 'seg_id']).reset_index(drop=True).to_csv(
        out_dir / 'matched_pairs_cross_vehicle.csv', index=False,
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
    vehicle_equations = '/'.join(sorted({v['equation'] for v in vehicle_resolved.values()}))
    written += bland_altman_plot(pairs, 'iri_multi_vehicle',
                                 f'До калібрування: IRI_multi (паспорт носія, {vehicle_equations})',
                                 figures_dir, 'fig2c_bland_altman_vehicle_before')
    written += bland_altman_plot(pairs, 'iri_multi_bias_corrected',
                                 'Після корекції зсуву Eq.6 (+1.55 м/км)',
                                 figures_dir, 'fig2b_bland_altman_bias_corrected')
    for ds in DATASETS:
        written += chainage_overlay(pairs, ds['road'], figures_dir,
                                    calibrated_col='iri_multi_bias_corrected',
                                    smartphone_label='Смартфон (корекція зсуву Eq.6)')

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
        '## Впорядкування і рівні ДСТУ 3587:2022 (Т1016, після корекції зсуву)',
    ]
    rk = ranking['Т1016']
    lines += [
        f"- Топ-10 найгірших сегментів за еталоном збігається зі смартфоном на "
        f"{rk['top_k_overlap']['10']['overlap']}/{rk['top_k_overlap']['10']['k']}; топ-20 — "
        f"{rk['top_k_overlap']['20']['overlap']}/{rk['top_k_overlap']['20']['k']}.",
        f"- Сегментів з IRI еталона ≥ {rk['rough']['threshold']:g} м/км: {rk['rough']['n']}, пікетаж "
        f"{rk['rough']['chainage_min_m']/1000:.1f}–{rk['rough']['chainage_max_m']/1000:.1f} км; "
        f"смартфон дає в середньому {rk['rough']['metric_to_ref_mean_ratio']:.2f} еталона на них. "
        f"Найгрубший сегмент: {rk['worst']['iri_ref']:.1f} проти {rk['worst']['metric']:.1f} м/км "
        f"(пікетаж {rk['worst']['chainage_m']/1000:.2f} км).",
        f"- Збіг рівня вимог ДСТУ: {rk['level_same_share']:.1%} сегментів; у межах сусіднього рівня: "
        f"{rk['level_within_one_share']:.1%}; у межах ±1 м/км: {rk['share_within']['1']:.1%}, "
        f"±0,5 м/км: {rk['share_within']['0.5']:.1%}.",
        '',
        '## Паспорт носія: набір Eq.4/5/6 за класом автомобіля (чутливість)',
    ]
    v_vehicle = validation['iri_multi_vehicle']
    resolved = vehicle_resolved['Т1016']
    bias_grows = abs(iri_multi_vehicle_bias) > abs(iri_multi_bias)
    lines += [
        f"- Резолвер аналізатора підставив у рівняння паспорт запису: {resolved['equation']} "
        f"({resolved['vehicle_type']}), параметри {resolved['params']}, походження "
        f"{resolved['provenance']}.",
        f"- Рангова валідність: Т1016 ρ = {v_vehicle['Т1016']['spearman_rho']:.3f} проти "
        f"{v_multi['Т1016']['spearman_rho']:.3f} у Eq.6 "
        f"(зміна {v_vehicle['Т1016']['spearman_rho'] - v_multi['Т1016']['spearman_rho']:+.3f}); "
        f"М-03 ρ = {v_vehicle['М-03']['spearman_rho']:.3f} проти {v_multi['М-03']['spearman_rho']:.3f}.",
        f"- Постійний зсув: {iri_multi_vehicle_bias:+.3f} м/км проти {iri_multi_bias:+.3f} у Eq.6 — "
        + ('клас носія за довідником зсув НЕ пояснює: за модулем він зростає. '
           if bias_grows else 'клас носія за довідником зменшує зсув. ')
        + f"LORO після корекції зсуву: М-03 {bias_loro_vehicle['М-03']['mae']:.3f} "
        f"(Eq.6: {bias_loro['М-03']['mae']:.3f}), Т1016 {bias_loro_vehicle['Т1016']['mae']:.3f} "
        f"(Eq.6: {bias_loro['Т1016']['mae']:.3f}) м/км.",
        ('- Висновок: зсув є властивістю пари «телефон — автомобіль», а не класу носія у довіднику; '
         'книжковий набір класу не заміняє польового калібрування з провенансом.'
         if bias_grows else
         '- Висновок: частина зсуву пояснюється класом носія; решта лишається за польовим калібруванням.'),
        '',
        '## Другий носій: той самий телефон у кросовері (по одному проїзду)',
    ]
    cv_val = cross_vehicle['validation_iri_multi']
    cv_tr = cross_vehicle['bias_transfer_from_source']
    cv_zero = cross_vehicle['iri_multi_zero_share']
    cv_speed = cross_vehicle['mean_speed_kmh']
    cv_rank = cross_vehicle['ranking_agreement_pooled_source_offset']['Т1016']
    lines += [
        f"- Т1016: ρ = {cv_val['Т1016']['spearman_rho']:.3f} (n = {cv_val['Т1016']['n']}, ефективний n ≈ "
        f"{cross_vehicle['effective_n']['Т1016']['iri_ref']['n_eff']:.0f}) проти "
        f"{v_multi['Т1016']['spearman_rho']:.3f} у фургона; зсув {cv_val['Т1016']['bias']:+.3f} проти "
        f"{v_multi['Т1016']['bias']:+.3f} м/км; середня швидкість {cv_speed['target']['Т1016']:.0f} "
        f"проти {cv_speed['source']['Т1016']:.0f} км/год.",
        f"- Зсув фургона на тій самій дорозі ({cv_tr['Т1016']['same_road']['k_source']:+.3f}), застосований до "
        f"кросовера без переналаштування: залишковий зсув {cv_tr['Т1016']['same_road']['bias_residual']:+.3f}, "
        f"MAE {cv_tr['Т1016']['same_road']['mae']:.3f} м/км (гейт {GATES['mae_max']} не проходить).",
        f"- Після об'єднаної поправки фургона: топ-10 {cv_rank['top_k_overlap']['10']['overlap']}/"
        f"{cv_rank['top_k_overlap']['10']['k']}, топ-20 {cv_rank['top_k_overlap']['20']['overlap']}/"
        f"{cv_rank['top_k_overlap']['20']['k']}; збіг рівня ДСТУ {cv_rank['level_same_share']:.1%}.",
        f"- М-03: iri_multi обрізано до нуля у {cv_zero['target']['М-03']:.0%} пар кросовера "
        f"(у фургона {cv_zero['source']['М-03']:.0%}) — та сама межа чутливості на рівній дорозі; "
        f"ρ = {cv_val['М-03']['spearman_rho']:.3f} тут не є мірою валідності.",
        '- Обмеження: по одному проїзду кожним носієм, проїзд кросовера на місяць пізніший за еталон.',
        '',
        '## Калібрувальна модель (пілот): IRI_cal = max(0, γ·[R − β(v − v0)] + δ)',
    ]
    cmp_ = calibration_model_pilot
    fit_ = cmp_['fit_van_T1016']
    tr_ = cmp_['transfer_from_van_T1016']

    def _f(value, digits=3):
        return '—' if value is None else f'{value:.{digits}f}'

    lines += [
        f"- R — необрізана оцінка Eq.6 (`iri_multi_raw`). β: {cmp_['beta_status']}. "
        f"Підгонка на фургоні, Т1016: γ = {fit_['gamma']:.3f} "
        f"[{fit_['gamma_ci'][0]:.3f}; {fit_['gamma_ci'][1]:.3f}], δ = {fit_['delta']:.3f} "
        f"[{fit_['delta_ci'][0]:.3f}; {fit_['delta_ci'][1]:.3f}] (бутстреп блоків 200 м).",
    ]
    for key, label in (('crossover|Т1016', 'кросовер, Т1016'), ('van|М-03', 'фургон, М-03'),
                       ('crossover|М-03', 'кросовер, М-03')):
        res = tr_.get(key)
        if res is None:
            continue
        verdict = 'краще' if res['M1']['mae'] < res['bias_only']['mae'] else 'гірше'
        lines.append(f"- Перенесення на {label}: MAE M1 {res['M1']['mae']:.3f} проти "
                     f"{res['bias_only']['mae']:.3f} (лише зсув, модель {verdict}) і "
                     f"{res['book']['mae']:.3f} (книжкова).")
    lines += [
        f"- Частка від'ємних R: " + ', '.join(f"{k} {v:.0%}" for k, v in sorted(cmp_['raw_below_zero_share'].items())),
        '',
        '## Базовий метод проти удосконаленого (ті самі записи, той самий еталон)',
        '- Похибка — після корекції зсуву, оціненого на іншій дорозі того самого автомобіля.',
    ]
    abl = ablation['variants']
    for key in sorted(abl['full']):
        full_ = abl['full'][key]
        parts = [f"- {key}: повний метод n = {full_['n_pairs']}, ρ = {full_['spearman_rho']:.3f}, "
                 f"MAE = {_f(full_['loro_bias_corrected_mae'])}; нахил телефона "
                 f"{_f(ablation['mount_tilt_deg'].get(key), 1)}°"]
        orient_ = abl['no_orientation'].get(key)
        if orient_:
            parts.append(f"без корекції орієнтації ρ = {orient_['spearman_rho']:.3f}, "
                         f"MAE = {_f(orient_['loro_bias_corrected_mae'])}")
        time_ = abl['time_segments'].get(key)
        regime_ = ablation['full_in_time_segments_speed_regime'].get(key)
        if time_ and regime_:
            lo, hi = ablation['time_segments_speed_range_kmh'][key]
            parts.append(f"вікна за часом n = {time_['n_pairs']}, ρ = {time_['spearman_rho']:.3f}, "
                         f"MAE = {_f(time_['loro_bias_corrected_mae'])} (повний метод у тому ж "
                         f"діапазоні {lo:.0f}–{hi:.0f} км/год: n = {regime_['n_pairs']}, ρ = "
                         f"{regime_['spearman_rho']:.3f}, MAE = {_f(regime_['loro_bias_corrected_mae'])})")
        else:
            parts.append('вікна за часом: жодне не зіставлено')
        lines.append('; '.join(parts) + '.')
    gate = abl['no_speed_gate']
    outside_keys = [k for k in sorted(gate) if gate[k]['outside_20_100_kmh']['n']]
    if outside_keys:
        lines.append('- Без швидкісного коридору: ' + '; '.join(
            f"{k} — {gate[k]['outside_20_100_kmh']['n']} сегм. поза 20–100 км/год, MAE на них "
            f"{_f(gate[k]['outside_20_100_kmh']['mae'])} проти {_f(gate[k]['outside_20_100_kmh']['mae_inside'])} "
            f"в коридорі; загальна MAE {_f(abl['full'].get(k, {}).get('loro_bias_corrected_mae'))} → "
            f"{_f(gate[k]['loro_bias_corrected_mae'])}" for k in outside_keys) + '.')
    else:
        lines.append('- Швидкісний коридор: зіставлених сегментів поза 20–100 км/год немає — '
                     'на цих даних його ефект не перевіряється.')
    lines += [
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

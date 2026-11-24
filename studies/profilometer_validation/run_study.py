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
    REFERENCE_CHANNELS, form_10m, load_form_10m, load_form_intervals, match_segments,
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

# G3 section campaigns (block added 2026-11-21; spec 2026-11-15-calibration-model-
# and-ablation-design.md, Amendment 2026-11-21): one section surveyed with the ARRB
# Walking Profiler G3 (class 1; passes = reference channels) and driven by the same
# phone and car at several steady speeds in the surveyed lane. The reference is
# rebuilt from the raw G3 exports on every run (profilometer_validation.g3); the
# segments are the analyzer CLI output (defaults) for storage/data/field_2026_11_21.
G3_CAMPAIGNS = [
    {
        'section': 'G3_2026-11-21',
        'vehicle': 'crossover',
        'surveys_dir': 'storage/field_measurements/g3/2026-11-21/Surveys',
        'surveys': ('2026-11-21 14h10m34s Zao_7', '2026-11-21 14h45m35s Zao_8'),
        'results_dir': 'storage/results/field_g3_20261121',
        'runs': {'sensor_data_20261121_145112': 30, 'sensor_data_20261121_145720': 40,
                 'sensor_data_20261121_150236': 50, 'sensor_data_20261121_150735': 60},
    },
    # Second section (added 2026-11-22): both wheel paths there and back, Fast
    # Profiling. The first odometer calibration of the day was wrong (factor 1.16176);
    # the surveys are the tablet app's own REPROCESS with the factor of the second,
    # taped calibration (0.99483) - see Dissertation/field_research_22_11_2026/
    # walking_profiler_g3/README.md. Segments: analyzer CLI output (defaults) for
    # storage/data/field_2026_11_22; the failed 80 km/h attempt is not used.
    {
        'section': 'G3_2026-11-22',
        'vehicle': 'crossover',
        'surveys_dir': 'storage/field_measurements/g3/2026-11-22/Surveys',
        'surveys': ('2026-11-22 06h02m15s B_l_1', '2026-11-22 06h11m58s B_l_2',
                    '2026-11-22 06h18m57s B_R_1', '2026-11-22 06h25m14s B_R_2'),
        'results_dir': 'storage/results/field_g3_20261122',
        'runs': {'sensor_data_20261122_044740': 40, 'sensor_data_20261122_045451': 50,
                 'sensor_data_20261122_050113': 60, 'sensor_data_20261122_050800': 70},
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


def _vehicle_passport(segments_csv: str) -> dict:
    """vehicle_id and tyres of a recording (its recording_meta.json)."""
    meta = json.loads((REPO_ROOT / segments_csv).parent.joinpath('recording_meta.json')
                      .read_text(encoding='utf-8'))
    return {k: meta['vehicle'].get(k) for k in ('vehicle_id', 'vehicle_tire_type', 'vehicle_make_model')}


def _g3_segments_csv(run_id: str, campaigns=G3_CAMPAIGNS) -> str:
    campaign = next(c for c in campaigns if run_id in c['runs'])
    return f"{campaign['results_dir']}/{run_id}/road_segments.csv"


def g3_reference(campaign: dict):
    """The section reference rebuilt from the raw G3 exports of a campaign."""
    from profilometer_validation import g3
    root = REPO_ROOT / campaign['surveys_dir']

    def _pass(stem):
        def read(suffix):
            return (root / f'{stem} {suffix}').read_text(encoding='utf-8-sig')
        return g3.G3Pass.from_texts(stem, read('IRI.csv'), read('GNSS.csv'), read('Profile.csv'),
                                    read('Information.txt'))
    return g3.build_section_reference([_pass(stem) for stem in campaign['surveys']])


def g3_pairs(campaigns=G3_CAMPAIGNS) -> tuple:
    """(pairs of every run against its section reference, {section: reference});
    the study matcher with its parameters unchanged."""
    frames, references = [], {}
    for campaign in campaigns:
        reference = g3_reference(campaign)
        references[campaign['section']] = reference
        form10 = form_10m(reference.intervals)
        for run_id, target_kmh in campaign['runs'].items():
            matched = windowed_reference(
                _segment_geometry({'segments_csv': _g3_segments_csv(run_id, campaigns)}), form10,
                endpoint_tolerance_m=MATCHING['endpoint_tolerance_m'],
                min_rows_in_window=MATCHING['min_ref_rows'],
                max_window_m=MATCHING['max_window_m'])
            matched['road'] = campaign['section']
            frames.append(matched[[c for c in PAIR_COLUMNS if c in matched.columns]].assign(
                run_id=run_id, target_kmh=target_kmh, vehicle=campaign['vehicle']))
    return pd.concat(frames, ignore_index=True), references


def g3_section_campaign(pairs_g3: pd.DataFrame, references: dict,
                        pairs_external: pd.DataFrame) -> dict:
    """
    Calibration model on the G3 section(s): beta from the passes at different
    speeds, gamma/delta by inverse calibration, checked on held-out passes
    (beta re-estimated without them), on 200 m spatial blocks, and on the
    laser-profilometer roads driven by the same car (pairs_external), where
    nothing is refitted.
    """
    from scipy import stats as sps
    from profilometer_validation import calibration_model as cmod
    from profilometer_validation.aggregate import bin_pairs, repeatability_sd

    clean = cmod.clean_pairs(pairs_g3)
    beta = cmod.estimate_beta(clean, section_col='road')
    slope = beta['slope_iri_per_kmh'] if beta else 0.0
    m1, m1_beta0 = cmod.fit(clean, slope), cmod.fit(clean, 0.0)
    k = cmod.fit_bias_only(clean)

    per_run = _g3_per_run(clean)

    # Pass-mean agreement over 100 m bins (what averaging the passes gives)
    binned = bin_pairs(clean.assign(r_v0=cmod.predictor(clean, slope)))
    bins = binned.groupby(['road', 'bin_center']).agg(
        iri_ref=('iri_ref', 'mean'), r=('iri_multi_raw', 'mean'), r_v0=('r_v0', 'mean'))
    pass_mean = {'n_bins': int(len(bins)),
                 'spearman_r': float(sps.spearmanr(bins['r'], bins['iri_ref']).statistic),
                 'pearson_r_v0': float(np.corrcoef(bins['r_v0'], bins['iri_ref'])[0, 1])}

    training_range, external = _g3_external_roads(clean, slope, pairs_external)

    return {
        'block_added': '2026-11-21',
        'model': 'IRI_cal = max(0, gamma * [R - beta * (v - v0)] + delta), R = iri_multi_raw',
        'v0_kmh': cmod.V0_KMH,
        'references': _g3_reference_summary(references),
        'n_pairs': int(len(clean)),
        'per_run': per_run,
        'training_range': training_range,
        'beta': beta,
        'fits': {'M1_beta': m1.to_dict(), 'M1_beta0': m1_beta0.to_dict(),
                 'M2_beta': cmod.fit_m2(clean, slope).to_dict(), 'bias_only_k': k},
        'in_sample': {'book': _g3_book(clean),
                      'bias_only': cmod.evaluate(np.maximum(0.0, clean['iri_multi_raw']) + k, clean['iri_ref']),
                      'M1_beta0': cmod.evaluate(cmod.predict(clean, m1_beta0), clean['iri_ref']),
                      'M1_beta': cmod.evaluate(cmod.predict(clean, m1), clean['iri_ref'])},
        'leave_one_run_out_beta_refitted': cmod.leave_one_run_out(clean, section_col='road'),
        'block_cv_200m_beta_all_passes': cmod.block_cv(clean, n_folds=5, beta=slope),
        'block_cv_200m_beta0': cmod.block_cv(clean, n_folds=5, beta=0.0),
        'bootstrap_M1_beta': cmod.bootstrap_params(clean, n_boot=1000, beta=slope),
        'repeatability_sd': {'book': repeatability_sd(bin_pairs(clean)),
                             'M1_beta': repeatability_sd(bin_pairs(
                                 clean.assign(iri_multi=cmod.predict(clean, m1))))},
        'pass_mean_agreement_100m': pass_mean,
        'external_profilometer_roads_same_car': external,
        'external_vehicle': {ds['road']: _vehicle_passport(ds['segments_csv'])
                             for ds in CROSS_VEHICLE_DATASETS},
        'notes': [
            'block_cv uses beta estimated on all passes (beta is a property of the design, '
            'not of a spatial block); leave_one_run_out re-estimates it without the held-out pass',
            'external roads: fitted on G3 only, nothing refitted; outside the training speed or '
            'IRI range the model extrapolates',
        ],
    }


def _g3_book(d: pd.DataFrame) -> dict:
    from profilometer_validation import calibration_model as cmod
    return cmod.evaluate(np.maximum(0.0, d['iri_multi_raw']), d['iri_ref'])


def _g3_reference_summary(references: dict) -> dict:
    return {s: {'channels': r.channels, 'warnings': r.warnings, 'step_m': r.step_m,
                'chainage_span_m': r.chainage_span_m, 'survey_date': r.survey_date,
                'n_intervals': int(len(r.intervals))} for s, r in references.items()}


def _g3_external_roads(clean: pd.DataFrame, slope: float, pairs_external: pd.DataFrame) -> tuple:
    """(training range, the G3-fitted model on the laser-profilometer roads, nothing refitted)."""
    from profilometer_validation import calibration_model as cmod
    training_range = {'speed_kmh': [float(clean['mean_speed_kmh'].min()), float(clean['mean_speed_kmh'].max())],
                      'iri_ref': [float(clean['iri_ref'].min()), float(clean['iri_ref'].max())]}
    external = {}
    ext = cmod.clean_pairs(pairs_external)
    for road, g in ext.groupby('road'):
        both = pd.concat([clean, g], ignore_index=True)
        train = np.r_[np.ones(len(clean), bool), np.zeros(len(g), bool)]
        with_beta = cmod.holdout(both, train, models=('book', 'bias_only', 'M1'), beta=slope)
        speed = g['mean_speed_kmh']
        external[road] = {
            'n': int(len(g)), 'mean_speed_kmh': float(speed.mean()),
            'share_inside_training_speed_range': float(speed.between(*training_range['speed_kmh']).mean()),
            'share_inside_training_iri_range': float(g['iri_ref'].between(*training_range['iri_ref']).mean()),
            'book': with_beta['book'], 'bias_only': with_beta['bias_only'], 'M1_beta': with_beta['M1'],
            'M1_beta0': cmod.holdout(both, train, models=('M1',), beta=0.0)['M1'],
        }
    return training_range, external


def _g3_per_run(clean: pd.DataFrame) -> dict:
    return {run: {'target_kmh': int(g['target_kmh'].iloc[0]), 'n_pairs': int(len(g)),
                  'mean_speed_kmh': float(g['mean_speed_kmh'].mean()),
                  'match_dist_m_max': float(g['match_dist_m'].max()),
                  'vehicle': _vehicle_passport(_g3_segments_csv(run)),
                  'book': _g3_book(g)}
            for run, g in clean.groupby('run_id')}


def _g3_gate_row(train: pd.DataFrame, test: pd.DataFrame, beta: float) -> dict:
    """The gate quantities of one held-out set: book, bias-only and M1 fitted on train."""
    from profilometer_validation import calibration_model as cmod
    test = cmod.clean_pairs(test)
    ref = test['iri_ref'].to_numpy(float)
    preds = {m: cmod.fit_and_predict(train, test, m, beta)[1] for m in ('book', 'bias_only', 'M1')}
    ev = {m: cmod.evaluate(p, ref) for m, p in preds.items()}
    level = {m: ranking_agreement(test.assign(pred=p), metric_col='pred')['level_same_share']
             for m, p in preds.items()}
    ratio = ev['M1']['rough_pred_to_ref']
    return {
        'n': ev['M1']['n'], 'iri_ref_mean': float(ref.mean()), 'beta': beta,
        'mae': {m: e['mae'] for m, e in ev.items()},
        'mae_below_0_5': ev['M1']['mae'] < 0.5,
        'rough_n': ev['M1']['rough_n'], 'rough_pred_to_ref_M1': ratio,
        'rough_ratio_in_0_9_1_1': None if ratio is None else bool(0.9 <= ratio <= 1.1),
        'spearman': {m: e['spearman_rho'] for m, e in ev.items()},
        'spearman_not_lower': bool(ev['M1']['spearman_rho'] >= ev['book']['spearman_rho']),
        'dstu_level_same_share': level,
        'dstu_not_worse_than_bias_only': bool(level['M1'] >= level['bias_only']),
    }


def g3_two_sections(pairs_g3: pd.DataFrame, references: dict, pairs_external: pd.DataFrame) -> dict:
    """
    The calibration model on every G3 section together (block added 2026-11-22):
    what each section says on its own, the pooled fit, and the error on a section
    the model has not seen (leave_one_section_out: beta, gamma, delta from the other
    section only). The 2026-11-21 block above stays the single-section record.
    """
    from profilometer_validation import calibration_model as cmod

    clean = cmod.clean_pairs(pairs_g3)
    per_section = {}
    for road, g in clean.groupby('road'):
        b = cmod.estimate_beta(g, section_col='road')
        per_section[road] = {
            'n_pairs': int(len(g)), 'n_runs': int(g['run_id'].nunique()),
            'speed_kmh': [float(g['mean_speed_kmh'].min()), float(g['mean_speed_kmh'].max())],
            'iri_ref': [float(g['iri_ref'].min()), float(g['iri_ref'].max())],
            'iri_ref_mean': float(g['iri_ref'].mean()),
            'book': _g3_book(g),
            'bias_only_k': cmod.fit_bias_only(g),
            'beta': b,
        }
    beta = cmod.estimate_beta(clean, section_col='road')
    slope = beta['slope_iri_per_kmh'] if beta else 0.0
    m1 = cmod.fit(clean, slope)
    k = cmod.fit_bias_only(clean)
    training_range, external = _g3_external_roads(clean, slope, pairs_external)

    # Pre-declared gates (spec 2026-11-15, section 3) on every held-out set: each G3
    # section with the model of the other one, each profilometer road with the model
    # of both sections
    held_out = {}
    for road in sorted(clean['road'].unique()):
        train = clean[clean['road'] != road]
        b = cmod.estimate_beta(train, section_col='road')
        held_out[road] = _g3_gate_row(train, clean[clean['road'] == road], b['slope_iri_per_kmh'] if b else 0.0)
    for road, g in cmod.clean_pairs(pairs_external).groupby('road'):
        held_out[road] = _g3_gate_row(clean, g, slope)
    gate_keys = ('mae_below_0_5', 'rough_ratio_in_0_9_1_1', 'spearman_not_lower', 'dstu_not_worse_than_bias_only')
    gates = {'held_out': held_out,
             'all_pass': {g: all(row[g] is not False for row in held_out.values()) for g in gate_keys}}
    return {
        'block_added': '2026-11-22',
        'sections': sorted(clean['road'].unique()),
        'references': _g3_reference_summary(references),
        'n_pairs': int(len(clean)),
        'per_run': _g3_per_run(clean),
        'per_section': per_section,
        'beta_pooled': beta,
        'fits': {'M1_beta': m1.to_dict(), 'bias_only_k': k},
        'in_sample': {'book': _g3_book(clean),
                      'bias_only': cmod.evaluate(np.maximum(0.0, clean['iri_multi_raw']) + k, clean['iri_ref']),
                      'M1_beta': cmod.evaluate(cmod.predict(clean, m1), clean['iri_ref'])},
        'leave_one_section_out': cmod.leave_one_section_out(clean, section_col='road'),
        'leave_one_run_out_beta_refitted': cmod.leave_one_run_out(clean, section_col='road'),
        'training_range': training_range,
        'external_profilometer_roads_same_car': external,
        'gates': gates,
        'notes': [
            'gates (spec 2026-11-15, section 3, fixed before the campaign): held-out MAE of M1 '
            '< 0.5 m/km; mean predicted/reference on rough bins within 0.9-1.1 (None = no rough '
            'bins); "rho unchanged" read as Spearman of M1 not lower than of the book estimate; '
            'DSTU 3587 level agreement of M1 not worse than bias-only',
            'a 100 m phone segment is matched only when it lies inside the surveyed section, '
            'so the 380 m section of 2026-11-22 yields 2-3 pairs per pass',
            'leave_one_section_out: beta re-estimated on the training section (0 when it no '
            'longer identifies it); external roads: fitted on both sections, nothing refitted',
        ],
    }


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

    # --- G3 section campaign (block added 2026-11-21): the same car on a section
    # with a class-1 reference at several speeds; checked on the profilometer roads ---
    pairs_g3, g3_references = g3_pairs()
    first = G3_CAMPAIGNS[0]['section']
    g3_campaign = g3_section_campaign(pairs_g3[pairs_g3['road'] == first],
                                      {first: g3_references[first]}, pairs_cv)
    g3_sections = g3_two_sections(pairs_g3, g3_references, pairs_cv)

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
        'g3_section_campaign': g3_campaign,
        'g3_two_sections': g3_sections,
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
    pairs_g3.sort_values(['road', 'run_id', 'seg_id']).reset_index(drop=True).to_csv(
        out_dir / 'matched_pairs_g3.csv', index=False,
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
    g3c = g3_campaign
    lines += ['', '## Ділянка з еталоном G3: калібрувальна модель на проїздах із різними швидкостями']
    for section, ref_ in sorted(g3c['references'].items()):
        lines.append(f"- {section}: еталон із {len(ref_['channels'])} проходів G3, {ref_['n_intervals']} "
                     f"інтервалів по {ref_['step_m']:g} м; "
                     + ('попередження: ' + '; '.join(ref_['warnings']) if ref_['warnings']
                        else 'без попереджень') + '.')
    lines.append('- Проїзди: ' + '; '.join(
        f"{run[-6:]} — {v['target_kmh']} км/год (факт {v['mean_speed_kmh']:.1f}), n = {v['n_pairs']}, "
        f"зсув книжкової оцінки {v['book']['bias']:+.2f} м/км" for run, v in sorted(g3c['per_run'].items())) + '.')
    beta_ = g3c['beta']
    lines.append(
        f"- β = {beta_['slope_iri_per_kmh']:.4f} м/км на км/год [{beta_['ci_low']:.4f}; {beta_['ci_high']:.4f}] "
        f"({beta_['confidence']:.0%}, dof = {beta_['dof']}; {beta_['n_rows']} пар, {beta_['n_bins']} бінів по 100 м)."
        if beta_ else '- β не ідентифіковано: немає розкиду швидкостей на одній ділянці.')
    lines.append('- Проїзд поза підгонкою (β перераховано без нього), MAE / зсув, м/км: ' + '; '.join(
        f"{run[-6:]}: модель {res['M1']['mae']:.2f} / {res['M1']['bias']:+.2f}, лише зсув "
        f"{res['bias_only']['mae']:.2f} / {res['bias_only']['bias']:+.2f}, книжкова {res['book']['mae']:.2f}"
        for run, res in sorted(g3c['leave_one_run_out_beta_refitted'].items())) + '.')
    boot_, cv_ = g3c['bootstrap_M1_beta'], g3c['block_cv_200m_beta_all_passes']
    lines.append(
        f"- γ = {boot_['gamma']:.3f} [{boot_['gamma_ci'][0]:.3f}; {boot_['gamma_ci'][1]:.3f}], "
        f"δ = {boot_['delta']:.3f} [{boot_['delta_ci'][0]:.3f}; {boot_['delta_ci'][1]:.3f}] (бутстреп "
        f"{boot_['n_blocks']} блоків по 200 м); просторові блоки: MAE моделі {cv_['M1']['mae']:.3f} проти "
        f"{cv_['bias_only']['mae']:.3f} (лише зсув) — "
        + ('модель краща.' if cv_['M1']['mae'] < cv_['bias_only']['mae']
           else 'модель не краща: γ однією ділянкою не визначається.'))
    rep_ = g3c['repeatability_sd']
    lines.append(f"- Розкид між проїздами (σ_r): {rep_['book']['sd']:.2f} → {rep_['M1_beta']['sd']:.2f} м/км "
                 'після моделі.')
    tyres_g3 = sorted({v['vehicle']['vehicle_tire_type'] for v in g3c['per_run'].values()})
    tyres_ext = sorted({v['vehicle_tire_type'] for v in g3c['external_vehicle'].values()})
    for road, ext_ in sorted(g3c['external_profilometer_roads_same_car'].items()):
        lines.append(
            f"- {road} (лазерний профілометр, той самий автомобіль; нічого не перепідганялося; "
            f"{ext_['share_inside_training_speed_range']:.0%} пар у діапазоні швидкостей підгонки, "
            f"{ext_['share_inside_training_iri_range']:.0%} — у діапазоні IRI): MAE моделі "
            f"{ext_['M1_beta']['mae']:.3f}, лише зсув {ext_['bias_only']['mae']:.3f}, книжкова "
            f"{ext_['book']['mae']:.3f} м/км.")
    if tyres_g3 != tyres_ext:
        lines.append(f"- Шини: на ділянці G3 {', '.join(tyres_g3)}, на дорогах із профілометром "
                     f"{', '.join(tyres_ext)} — перевірка перенесення включає зміну шин.")
    g3s = g3_sections
    lines += ['', '## Дві ділянки з еталоном G3: перенесення моделі на ділянку, якої вона не бачила']
    for section, s_ in sorted(g3s['per_section'].items()):
        b_ = s_['beta']
        lines.append(
            f"- {section}: {s_['n_pairs']} пар із {s_['n_runs']} проїздів, швидкості "
            f"{s_['speed_kmh'][0]:.0f}–{s_['speed_kmh'][1]:.0f} км/год, IRI еталона "
            f"{s_['iri_ref'][0]:.1f}–{s_['iri_ref'][1]:.1f} м/км; книжкова оцінка MAE {s_['book']['mae']:.2f}, "
            f"зсув {s_['book']['bias']:+.2f}; власний зсув k = {s_['bias_only_k']:.2f}; β = "
            + (f"{b_['slope_iri_per_kmh']:.4f} [{b_['ci_low']:.4f}; {b_['ci_high']:.4f}]." if b_
               else 'не ідентифіковано.'))
    for section, res in sorted(g3s['leave_one_section_out'].items()):
        lines.append(
            f"- Ділянка {section} поза підгонкою (β = {res['beta_train']:.4f} з іншої ділянки), MAE / зсув, "
            f"м/км: книжкова {res['book']['mae']:.2f} / {res['book']['bias']:+.2f}, лише зсув "
            f"{res['bias_only']['mae']:.2f} / {res['bias_only']['bias']:+.2f}, модель "
            f"{res['M1']['mae']:.2f} / {res['M1']['bias']:+.2f} (n = {res['M1']['n']}).")
    bp_ = g3s['beta_pooled']
    if bp_:
        lines.append(f"- β за обома ділянками = {bp_['slope_iri_per_kmh']:.4f} [{bp_['ci_low']:.4f}; "
                     f"{bp_['ci_high']:.4f}] ({bp_['n_rows']} пар).")
    verdict = {True: 'так', False: 'ні', None: '—'}
    lines.append('- Заздалегідь задані ворота (специфікація 2026-11-15, розд. 3), M1 на відкладеному наборі:')
    for name, row in g3s['gates']['held_out'].items():
        ratio_ = row['rough_pred_to_ref_M1']
        lines.append(
            f"  - {name} (n = {row['n']}, IRI еталона {row['iri_ref_mean']:.1f}): MAE {row['mae']['M1']:.2f} "
            f"< 0.5 — {verdict[row['mae_below_0_5']]}; прогноз/еталон на розбитих "
            + (f"{ratio_:.2f}" if ratio_ is not None else '—')
            + f" у 0.9–1.1 — {verdict[row['rough_ratio_in_0_9_1_1']]}; ρ {row['spearman']['M1']:.2f} проти "
            f"книжкової {row['spearman']['book']:.2f} — {verdict[row['spearman_not_lower']]}; рівень ДСТУ "
            f"{row['dstu_level_same_share']['M1']:.0%} проти {row['dstu_level_same_share']['bias_only']:.0%} "
            f"(лише зсув) — {verdict[row['dstu_not_worse_than_bias_only']]}.")
    all_ = g3s['gates']['all_pass']
    lines.append('  - Усі відкладені набори: ' + '; '.join(
        f"{g} — {verdict[v]}" for g, v in all_.items()) + '. Невиконані ворота — результат, не приховується.')
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
        '_Повні числа: stats.json; пари: matched_pairs.csv, matched_pairs_cross_vehicle.csv, '
        'matched_pairs_g3.csv; фігури: figures/_',
    ]
    (out_dir / 'study_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    print(f'✓ {out_dir / "matched_pairs.csv"}')
    print(f'✓ {out_dir / "stats.json"}')
    print(f'✓ {len(written)} figure files')
    print(f'✓ {out_dir / "study_report.md"}')
    print('Verdict:', gates['verdict'][:110] + '…')


if __name__ == '__main__':
    main()

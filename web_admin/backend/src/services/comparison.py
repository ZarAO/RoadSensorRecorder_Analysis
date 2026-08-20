"""
Executes one run-vs-reference comparison job: geo-matching of the run's 100 m
segments against the profilometer 10 m form, validation statistics, figures and
the compact chart series the UI renders (spec §3).

The statistics come from the validation study package (profilometer_validation)
unchanged — the admin runs the same math the dissertation reports, per single
comparison (one road), so nothing here is pooled across roads.
"""

import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from profilometer_validation.calibrate import (
    bland_altman,
    effective_n,
    fit_eq3,
    influence_on_eq3,
    validation_stats,
)
from profilometer_validation.match import (
    load_form_10m,
    segment_midpoints_from_geojson,
    windowed_reference,
)

from src.core.config import Settings
from src.db.models import AnalysisRun, CoefficientSet, Comparison, ReferenceDataset
from src.services.references import intervals_csv_path

# Study defaults (spec §3): min_rows_in_window=9 keeps a 100 m window that lost
# at most one 10 m row; the client may override any of the three.
DEFAULT_MATCH_PARAMS = {
    'endpoint_tolerance_m': 60.0,
    'min_rows_in_window': 9,
    'max_window_m': 160.0,
}
MIN_PAIRS = 5
BBOX_MARGIN_DEG = 0.01
GATE_R2_MIN = 0.85
GATE_MAE_MAX = 0.5
# influence_on_eq3 refits Eq.3 without the 5 roughest pairs; on a very small
# match that subset is too thin for a regression, so it is reported only when
# there is enough data for the refit to mean anything.
MIN_PAIRS_FOR_INFLUENCE = 10

# Shared Ukrainian 409 wording — the API's pre-queue validation and this
# module's own `_check_reference` guard must say the same thing, so the text
# lives here once and both sides import it.
MSG_REFERENCE_DELETED = 'еталон видалено — файл еталонних інтервалів більше не доступний'
MSG_REFERENCE_NOT_10M = 'еталон має бути 10 м формою (крок цього еталона: {step_m:g} м)'


class ComparisonError(Exception):
    """A guard failure carrying a user-facing Ukrainian explanation."""


def _json_safe(value):
    """NaN/Inf are not valid JSON: a missing metric is null, never NaN."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _geojson_bbox(geojson_path: Path) -> tuple:
    """[min_lat, min_lon, max_lat, max_lon] over every vertex (GeoJSON is [lon, lat])."""
    collection = json.loads(geojson_path.read_text(encoding='utf-8'))
    lats, lons = [], []
    for feature in collection.get('features', []):
        coordinates = feature.get('geometry', {}).get('coordinates') or []
        # The analyzer emits Point geometry (a flat [lon, lat] pair) for a segment
        # with fewer than 2 grid points, LineString (a list of pairs) otherwise.
        if coordinates and not isinstance(coordinates[0], (list, tuple)):
            coordinates = [coordinates]
        for point in coordinates:
            lons.append(float(point[0]))
            lats.append(float(point[1]))
    if not lats:
        raise ComparisonError('roughness.geojson рану не містить координат — зіставлення неможливе')
    return min(lats), min(lons), max(lats), max(lons)


def _bboxes_intersect(run_bbox: tuple, ref_bbox: list, margin: float = BBOX_MARGIN_DEG) -> bool:
    r_min_lat, r_min_lon, r_max_lat, r_max_lon = run_bbox
    e_min_lat, e_min_lon, e_max_lat, e_max_lon = (float(v) for v in ref_bbox)
    return (r_min_lat <= e_max_lat + margin and e_min_lat <= r_max_lat + margin
            and r_min_lon <= e_max_lon + margin and e_min_lon <= r_max_lon + margin)


def _check_run(run: AnalysisRun | None) -> Path:
    if run is None:
        raise ComparisonError('ран не знайдено')
    if run.status != 'done' or not run.result_dir:
        raise ComparisonError(
            f'ран не завершено успішно (статус: {run.status}) — '
            'порівняння можливе лише для завершеного аналізу')
    result_dir = Path(run.result_dir)
    missing = [name for name in ('road_segments.csv', 'roughness.geojson')
               if not (result_dir / name).is_file()]
    if missing:
        raise ComparisonError(
            f"артефакти рану відсутні на диску: {', '.join(missing)}")
    return result_dir


def _check_reference(reference: ReferenceDataset | None, settings: Settings) -> Path:
    if reference is None:
        raise ComparisonError('еталон не знайдено')
    if reference.source_deleted:
        raise ComparisonError(MSG_REFERENCE_DELETED)
    if reference.step_m != 10:
        raise ComparisonError(MSG_REFERENCE_NOT_10M.format(step_m=reference.step_m))
    intervals_path = intervals_csv_path(settings, reference)
    if not intervals_path.is_file():
        raise ComparisonError('файл еталонних інтервалів відсутній на диску')
    return intervals_path


def _match_params(params: dict | None) -> dict:
    supplied = {k: v for k, v in (params or {}).items() if k in DEFAULT_MATCH_PARAMS}
    merged = {**DEFAULT_MATCH_PARAMS, **supplied}
    return {
        'endpoint_tolerance_m': float(merged['endpoint_tolerance_m']),
        'min_rows_in_window': int(merged['min_rows_in_window']),
        'max_window_m': float(merged['max_window_m']),
    }


def _build_stats(pairs: pd.DataFrame, bias: float) -> dict:
    eq3 = fit_eq3(pairs)
    corrected = validation_stats(pairs, 'iri_multi_bias_corrected')
    stats = {
        'n_pairs': int(len(pairs)),
        'validation': {c: validation_stats(pairs, c)
                       for c in ('iri_multi', 'psd_sqrt_scalar', 'grms')},
        'bland_altman_before': bland_altman(pairs, 'iri_multi'),
        'bland_altman_bias_corrected': bland_altman(pairs, 'iri_multi_bias_corrected'),
        'eq3_fit': eq3,
        'eq6_bias': {'bias': bias, 'mae_corrected': corrected['mae']},
        'effective_n': {c: effective_n(pairs.sort_values('chainage_m')[c])
                        for c in ('iri_ref', 'iri_multi')},
        'influence': (influence_on_eq3(pairs)
                      if len(pairs) >= MIN_PAIRS_FOR_INFLUENCE else None),
        'gates': {
            'r2_min': GATE_R2_MIN,
            'mae_max': GATE_MAE_MAX,
            'eq3_r2_pass': bool(eq3['r2'] >= GATE_R2_MIN),
            'eq6_bias_mae_pass': bool(corrected['mae'] <= GATE_MAE_MAX),
            'note': 'Гейти — індикатори для людини, не автоматичне рішення (spec §3).',
        },
    }
    return stats


def _build_chart_data(pairs: pd.DataFrame, stats: dict, bias: float) -> dict:
    prof = pairs.sort_values('chainage_m')
    return {
        'scatter': pairs[['seg_id', 'psd_sqrt_scalar', 'iri_ref', 'iri_multi',
                          'chainage_m']].round(6).to_dict('records'),
        'profile': prof[['chainage_m', 'iri_ref', 'iri_multi',
                         'iri_multi_bias_corrected', 'seg_id']].round(6).to_dict('records'),
        'bland_altman': [{'seg_id': int(r.seg_id),
                          'mean': round((r.iri_multi + r.iri_ref) / 2, 6),
                          'diff': round(r.iri_multi - r.iri_ref, 6)}
                         for r in pairs.itertuples()],
        'eq3_fit': {k: stats['eq3_fit'][k] for k in ('A', 'B', 'r2', 'mae', 'n')},
        'bias': bias,
        'gates': stats['gates'],
    }


def _build_summary(pairs: pd.DataFrame, stats: dict, bias: float) -> dict:
    multi = stats['validation']['iri_multi']
    return {
        'n_pairs': int(len(pairs)),
        'spearman_rho': round(multi['spearman_rho'], 4),
        'pearson_r': round(multi['pearson_r'], 4),
        'mae': round(multi['mae'], 4),
        'bias': round(bias, 4),
        'n_eff': round(stats['effective_n']['iri_ref']['n_eff'], 4),
        'eq3_r2': round(stats['eq3_fit']['r2'], 4),
        'gates': stats['gates'],
    }


def _write_figures(pairs: pd.DataFrame, stats: dict, bias: float,
                   road_name: str, figures_dir: Path) -> None:
    # Imported lazily: figures pulls in matplotlib + scienceplots and applies a
    # global style (Agg backend, worker thread with max_workers=1)
    from profilometer_validation.figures import (
        bland_altman_plot,
        chainage_overlay,
        scatter_fit,
    )

    pairs['road'] = road_name
    scatter_fit(pairs, stats['eq3_fit'], figures_dir)
    bland_altman_plot(pairs, 'iri_multi', 'До корекції',
                      figures_dir, 'fig2a_bland_altman_before')
    bland_altman_plot(pairs, 'iri_multi_bias_corrected',
                      f'Після корекції зсуву ({bias:+.2f} м/км)',
                      figures_dir, 'fig2b_bland_altman_corrected')
    chainage_overlay(pairs, road_name, figures_dir,
                     calibrated_col='iri_multi_bias_corrected',
                     smartphone_label='Смартфон (корекція зсуву Eq.6)')


def _result_dir_for(settings: Settings, comparison_id: int) -> Path:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    return settings.storage_results_dir / 'comparisons' / f'cmp{comparison_id}_{stamp}'


def delete_comparison_artifacts(comparison: Comparison) -> None:
    if comparison.result_dir:
        shutil.rmtree(comparison.result_dir, ignore_errors=True)


def detach_coefficient_sets(session: Session, comparison_ids: list[int]) -> None:
    """Null out CoefficientSet.comparison_id for the given comparisons before
    they are deleted. A CoefficientSet's FK is nullable and its stats_snapshot
    already carries the metrics, so the set survives — only the back-reference
    is cleared. Shared by the comparisons and runs delete endpoints so a run
    deletion (which cascades its comparisons) closes the same dangling-FK hole."""
    if not comparison_ids:
        return
    for cs in session.scalars(
            select(CoefficientSet).where(
                CoefficientSet.comparison_id.in_(comparison_ids))).all():
        cs.comparison_id = None


def execute_comparison(comparison_id: int, engine, settings: Settings) -> None:
    with Session(engine) as session:
        comparison = session.get(Comparison, comparison_id)
        if comparison is None:
            return
        comparison.status = 'running'
        session.commit()

        try:
            run_dir = _check_run(session.get(AnalysisRun, comparison.run_id))
            reference = session.get(ReferenceDataset, comparison.reference_id)
            intervals_path = _check_reference(reference, settings)
            if reference.bbox and len(reference.bbox) == 4:
                if not _bboxes_intersect(_geojson_bbox(run_dir / 'roughness.geojson'),
                                         reference.bbox):
                    raise ComparisonError(
                        'ділянки рану та еталона не перетинаються географічно')

            usable = segment_midpoints_from_geojson(
                pd.read_csv(run_dir / 'road_segments.csv'),
                str(run_dir / 'roughness.geojson'))
            form10 = load_form_10m(str(intervals_path))
            params = _match_params(comparison.params)
            pairs = windowed_reference(usable, form10, **params)
            if len(pairs) < MIN_PAIRS:
                raise ComparisonError(
                    f'замало зіставлених пар ({len(pairs)}) — перевірте, що ран і '
                    'еталон покривають ту саму ділянку')

            bias = float((pairs['iri_multi'] - pairs['iri_ref']).mean())
            pairs['iri_multi_bias_corrected'] = pairs['iri_multi'] - bias
            stats = _build_stats(pairs, bias)
            chart_data = _build_chart_data(pairs, stats, bias)

            result_dir = _result_dir_for(settings, comparison.id)
            result_dir.mkdir(parents=True, exist_ok=True)
            comparison.result_dir = str(result_dir)
            pairs.to_csv(result_dir / 'matched_pairs.csv', index=False,
                         encoding='utf-8', lineterminator='\n', float_format='%.10g')
            (result_dir / 'stats.json').write_text(
                json.dumps(_json_safe(stats), ensure_ascii=False, indent=1, sort_keys=True),
                encoding='utf-8')
            (result_dir / 'chart_data.json').write_text(
                json.dumps(_json_safe(chart_data), ensure_ascii=False),
                encoding='utf-8')
            _write_figures(pairs, stats, bias, reference.road_name, result_dir / 'figures')

            comparison.summary = _json_safe(_build_summary(pairs, stats, bias))
            comparison.status = 'done'
            comparison.error = None
        except Exception as exc:
            comparison.status = 'failed'
            comparison.error = (str(exc) if isinstance(exc, ComparisonError)
                                else f'{type(exc).__name__}: {exc}')
        finally:
            session.commit()

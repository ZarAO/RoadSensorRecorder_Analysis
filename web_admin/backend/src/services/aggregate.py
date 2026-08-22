"""
Executes one multi-pass aggregation job: several runs of the same road are
geo-matched against the same profilometer 10 m form, pooled onto a fixed 100 m
bin grid, and reported as a repeatability / bias-CI / speed-effect triple plus
the aggregated profile the UI renders (spec Phase 2).

The math comes from the validation study package (profilometer_validation.aggregate)
unchanged — the admin runs exactly what the dissertation reports. This module only
orchestrates: guards, per-run matching, artifacts, figures, summary. Matching and
its parameters are shared with the single-pass job (services.comparison), so an
aggregate of one pass would reproduce that pass's comparison.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from profilometer_validation.aggregate import (
    bias_with_ci,
    bin_pairs,
    per_bin_stats,
    repeatability_sd,
    speed_effect,
)
from profilometer_validation.calibrate import validation_stats
from profilometer_validation.match import (
    load_form_10m,
    segment_midpoints_from_geojson,
    windowed_reference,
)

from src.core.config import Settings
from src.db.models import AggregateComparison, AnalysisRun, CoefficientSet, ReferenceDataset
from src.services.comparison import (
    MIN_PAIRS,
    ComparisonError,
    _bboxes_intersect,
    _check_reference,
    _check_run,
    _geojson_bbox,
    _json_safe,
    _match_params,
)

MIN_RUNS = 2
MSG_TOO_FEW_RUNS = 'потрібно щонайменше два рани'
DPI = 300


class AggregateError(ComparisonError):
    """A guard failure carrying a user-facing Ukrainian explanation."""


def unique_run_ids(run_ids) -> list:
    """Order-preserving de-duplication: the same run listed twice is one pass,
    not two, so it must not inflate n_runs or fake a repeatability estimate."""
    return list(dict.fromkeys(int(r) for r in (run_ids or [])))


def _round4(value):
    return None if value is None else round(float(value), 4)


def _run_label(run: AnalysisRun | None, run_id: int) -> str:
    if run is not None and run.file is not None:
        return f'ран #{run_id} ({run.file.filename})'
    return f'ран #{run_id}'


def _pairs_for_run(run: AnalysisRun | None, run_id: int, reference: ReferenceDataset,
                   form10: pd.DataFrame, params: dict) -> pd.DataFrame:
    """One pass's matched pairs, tagged with run_id. Every guard names the run:
    in an aggregate the operator has to know WHICH pass broke the job."""
    try:
        run_dir = _check_run(run)
    except ComparisonError as exc:
        raise AggregateError(f'{_run_label(run, run_id)}: {exc}') from exc

    if reference.bbox and len(reference.bbox) == 4:
        if not _bboxes_intersect(_geojson_bbox(run_dir / 'roughness.geojson'),
                                 reference.bbox):
            raise AggregateError(
                f'{_run_label(run, run_id)}: ділянки рану та еталона не '
                'перетинаються географічно')

    usable = segment_midpoints_from_geojson(
        pd.read_csv(run_dir / 'road_segments.csv'),
        str(run_dir / 'roughness.geojson'))
    pairs = windowed_reference(usable, form10, **params)
    if len(pairs) < MIN_PAIRS:
        raise AggregateError(
            f'{_run_label(run, run_id)}: замало зіставлених пар ({len(pairs)}) — '
            'перевірте, що ран і еталон покривають ту саму ділянку')
    pairs = pairs.copy()
    pairs['run_id'] = run.id
    return pairs


def _build_stats(run_ids: list, pairs: pd.DataFrame, bins: pd.DataFrame,
                 binned: pd.DataFrame, params: dict) -> dict:
    # The aggregated profile is validated as one series: the pooled per-bin mean
    # against the bin's reference IRI (rho/MAE of the mean pass, not of a pass).
    aggregated = pd.DataFrame({'m': bins['mean_iri'], 'iri_ref': bins['iri_ref']})
    return {
        'n_runs': len(run_ids),
        'run_ids': list(run_ids),
        'n_pairs': int(len(pairs)),
        'n_bins': int(len(bins)),
        'bias': bias_with_ci(bins),
        'repeatability': repeatability_sd(binned),
        'speed_effect': speed_effect(binned),
        'validation': validation_stats(aggregated, 'm'),
        'params': params,
    }


def _build_chart_data(bins: pd.DataFrame, stats: dict) -> dict:
    profile = [{'chainage_m': float(r.bin_center),
                'iri_ref': float(r.iri_ref),
                'mean_iri': float(r.mean_iri),
                'lo': float(r.min_iri),
                'hi': float(r.max_iri),
                'n_passes': int(r.n_passes),
                'std_iri': float(r.std_iri)}
               for r in bins.itertuples()]
    return {
        'profile': profile,
        'bias': stats['bias'],
        'repeatability': stats['repeatability'],
        'speed_effect': stats['speed_effect'],
        'validation': {'rho': stats['validation']['spearman_rho'],
                       'mae': stats['validation']['mae']},
    }


def _build_summary(stats: dict, stale: bool) -> dict:
    speed = stats['speed_effect']
    return {
        'n_runs': stats['n_runs'],
        'n_bins': stats['n_bins'],
        'bias': _round4(stats['bias']['bias']),
        'bias_ci_low': _round4(stats['bias']['ci_low']),
        'bias_ci_high': _round4(stats['bias']['ci_high']),
        'repeatability_sd': _round4(stats['repeatability']['sd']),
        'rho': _round4(stats['validation']['spearman_rho']),
        'mae_aggregated': _round4(stats['validation']['mae']),
        'speed_slope': _round4(speed['slope_iri_per_kmh']) if speed else None,
        # Threaded in by the caller, not hardcoded: mark_stale_for_run may commit
        # 'stale': True (a pooled run got deleted) from another session while
        # this job is still running its own long computation, and hardcoding
        # False here would silently clobber that mark on this job's finalize.
        'stale': stale,
    }


def _demeaned_speed_points(binned: pd.DataFrame):
    """The exact point cloud speed_effect regresses on: rows collapsed to one
    per (run_id, bin), only bins driven by >=2 passes, both axes demeaned within
    the bin. Mirrors profilometer_validation.aggregate.speed_effect so the
    figure shows the data the slope was fitted to."""
    collapsed = binned.groupby(['run_id', 'bin_center'], as_index=False)[
        ['iri_multi', 'iri_ref', 'mean_speed_kmh']].mean()
    multi = collapsed.groupby('bin_center').filter(lambda g: g['run_id'].nunique() >= 2)
    x, y = [], []
    for _, group in multi.groupby('bin_center'):
        diff = group['iri_multi'].to_numpy(float) - group['iri_ref'].to_numpy(float)
        speed = group['mean_speed_kmh'].to_numpy(float)
        x.extend(speed - speed.mean())
        y.extend(diff - diff.mean())
    return x, y


def _write_figures(bins: pd.DataFrame, binned: pd.DataFrame, stats: dict,
                   road_name: str, figures_dir: Path) -> None:
    # Imported lazily (matplotlib is heavy and applies global state); the job
    # runs on the queue's single worker thread, so the Agg backend is safe.
    # The style is pinned explicitly, not inherited: profilometer_validation.figures
    # applies ['science', 'no-latex'] process-wide at import, so without this an
    # aggregate rendered after a comparison would look different from one
    # rendered before it.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import scienceplots  # noqa: F401 (registers the styles)
    plt.style.use(['science', 'no-latex'])

    figures_dir.mkdir(parents=True, exist_ok=True)

    def _save(fig, name):
        for ext in ('png', 'pdf'):
            fig.savefig(figures_dir / f'{name}.{ext}', dpi=DPI, bbox_inches='tight')
        plt.close(fig)

    chainage_km = bins['bin_center'].to_numpy(float) / 1000.0
    fig, ax = plt.subplots(figsize=(6.0, 3.4))
    ax.fill_between(chainage_km, bins['min_iri'].to_numpy(float),
                    bins['max_iri'].to_numpy(float), alpha=0.3, color='#4393c3',
                    linewidth=0, label='Розкид проїздів (min–max)')
    ax.plot(chainage_km, bins['iri_ref'].to_numpy(float), color='#333333',
            linewidth=1.2, label='Профілометр (еталон)')
    ax.plot(chainage_km, bins['mean_iri'].to_numpy(float), color='#b2182b',
            linewidth=1.2, label=f"Смартфон, середнє з {stats['n_runs']} проїздів")
    ax.set_xlabel('Пікетаж, км')
    ax.set_ylabel('IRI, м/км')
    ax.set_title(road_name)
    ax.legend(fontsize=7)
    _save(fig, 'fig_agg_profile')

    speed = stats['speed_effect']
    if not speed:
        return
    x, y = _demeaned_speed_points(binned)
    fig, ax = plt.subplots(figsize=(4.2, 3.2))
    ax.scatter(x, y, s=16, alpha=0.7, color='#2166ac', edgecolors='none')
    if x:
        x_line = [min(x), max(x)]
        slope = speed['slope_iri_per_kmh']
        ax.plot(x_line, [slope * v for v in x_line], color='#333333', linewidth=1.2,
                label=f"нахил {slope:+.4f} ± {speed['stderr']:.4f} (м/км)/(км/год)")
        ax.legend(fontsize=7)
    ax.axhline(0.0, color='#999999', linewidth=0.6)
    ax.set_xlabel('Швидкість — центрована в межах біна, км/год')
    ax.set_ylabel('Відхилення IRI — центроване в межах біна, м/км')
    _save(fig, 'fig_agg_speed')


def _result_dir_for(settings: Settings, aggregate_id: int) -> Path:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    return settings.storage_results_dir / 'aggregates' / f'agg{aggregate_id}_{stamp}'


def delete_aggregate_artifacts(aggregate: AggregateComparison) -> None:
    if aggregate.result_dir:
        shutil.rmtree(aggregate.result_dir, ignore_errors=True)


def detach_coefficient_sets(session: Session, aggregate_ids: list[int]) -> None:
    """Null out CoefficientSet.aggregate_comparison_id before the aggregates are
    deleted — the set's stats_snapshot already carries the metrics, so only the
    back-reference is cleared (mirrors comparison.detach_coefficient_sets)."""
    if not aggregate_ids:
        return
    for cs in session.scalars(
            select(CoefficientSet).where(
                CoefficientSet.aggregate_comparison_id.in_(aggregate_ids))).all():
        cs.aggregate_comparison_id = None


def mark_stale_for_run(session, run_id: int) -> None:
    """Flag every aggregate that pooled this run: its artifacts still describe a
    pass that no longer exists, so the numbers stay readable but are marked as
    no longer reproducible. Does not commit — the caller owns the transaction.
    A fresh dict is assigned because the JSON column is not mutation-tracked."""
    for aggregate in session.scalars(select(AggregateComparison)).all():
        if run_id in unique_run_ids(aggregate.run_ids):
            aggregate.summary = {**(aggregate.summary or {}), 'stale': True}


def execute_aggregate(aggregate_id: int, engine, settings: Settings) -> None:
    with Session(engine) as session:
        aggregate = session.get(AggregateComparison, aggregate_id)
        if aggregate is None:
            return
        aggregate.status = 'running'
        session.commit()

        try:
            run_ids = unique_run_ids(aggregate.run_ids)
            if len(run_ids) < MIN_RUNS:
                raise AggregateError(MSG_TOO_FEW_RUNS)

            reference = session.get(ReferenceDataset, aggregate.reference_id)
            intervals_path = _check_reference(reference, settings)
            form10 = load_form_10m(str(intervals_path))
            params = _match_params(aggregate.params)

            frames = [_pairs_for_run(session.get(AnalysisRun, run_id), run_id,
                                     reference, form10, params)
                      for run_id in run_ids]
            pairs = pd.concat(frames, ignore_index=True)

            binned = bin_pairs(pairs)
            bins = per_bin_stats(binned)
            if bins.empty:
                raise AggregateError(
                    'після відсіву некоректних значень не залишилось жодного '
                    '100-метрового біна — агрегація неможлива')
            stats = _build_stats(run_ids, pairs, bins, binned, params)
            chart_data = _build_chart_data(bins, stats)

            result_dir = _result_dir_for(settings, aggregate.id)
            result_dir.mkdir(parents=True, exist_ok=True)
            aggregate.result_dir = str(result_dir)
            pairs.to_csv(result_dir / 'per_pass_pairs.csv', index=False,
                         encoding='utf-8', lineterminator='\n', float_format='%.10g')
            bins.to_csv(result_dir / 'per_bin.csv', index=False,
                        encoding='utf-8', lineterminator='\n', float_format='%.10g')
            (result_dir / 'aggregate_stats.json').write_text(
                json.dumps(_json_safe(stats), ensure_ascii=False, indent=1, sort_keys=True),
                encoding='utf-8')
            (result_dir / 'chart_data.json').write_text(
                json.dumps(_json_safe(chart_data), ensure_ascii=False),
                encoding='utf-8')
            _write_figures(bins, binned, stats, reference.road_name,
                           result_dir / 'figures')

            # A concurrent mark_stale_for_run (run deleted while this job was
            # still computing) commits on another session; this session's own
            # cached copy of `aggregate` would otherwise miss it. A scoped
            # column read picks up that commit without disturbing this
            # session's own pending, not-yet-flushed attributes on `aggregate`
            # (result_dir, set above) -- session.refresh() would discard those.
            existing_summary = session.scalar(
                select(AggregateComparison.summary).where(AggregateComparison.id == aggregate.id))
            stale = bool((existing_summary or {}).get('stale'))
            aggregate.summary = _json_safe(_build_summary(stats, stale))
            aggregate.status = 'done'
            aggregate.error = None
        except Exception as exc:
            aggregate.status = 'failed'
            aggregate.error = (str(exc) if isinstance(exc, ComparisonError)
                               else f'{type(exc).__name__}: {exc}')
        finally:
            session.commit()

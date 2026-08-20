"""
Executes one analysis run: status transitions, stdout -> run.log, in-process
analyze() call, summary extraction from the artifacts.

Note: contextlib.redirect_stdout patches sys.stdout process-wide for the
duration of the run. With max_workers=1 and no other stdout writers in the
server this is acceptable locally (uvicorn logs go through logging/stderr).
"""

import contextlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from road_quality_analyzer.cli import analyze

from src.core.config import Settings
from src.db.models import AnalysisRun, SourceFile
from src.services.coefficients import bias_of, eq3_kwargs


def build_summary(result_dir: Path, coefficients: dict | None = None) -> dict:
    segments = pd.read_csv(result_dir / 'road_segments.csv')
    full_valid = segments[(~segments['partial']) & (segments['speed_valid'])]
    mean_iri = float(full_valid['iri_multi'].mean()) if len(full_valid) else None
    # An all-NaN column means the mean is NaN: a missing metric is null, never NaN
    if mean_iri is not None and not math.isfinite(mean_iri):
        mean_iri = None

    meta_path = result_dir / 'recording_meta.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
    events = meta.get('events', [])

    summary = {
        'segments_total': int(len(segments)),
        'km_total': float(segments['length_m'].sum()) / 1000.0,
        'mean_iri_multi': mean_iri,
        'low_speed_count': int(segments['needs_class12_survey'].sum()),
        'partial_count': int(segments['partial'].sum()),
        'events_total': len(events),
        'incidents_total': sum(1 for e in events if e.get('type') != 'accuracy_changed'),
        'clean_stop': meta.get('clean_stop'),
        'vehicle_type': (meta.get('vehicle') or {}).get('vehicle_type'),
    }
    if coefficients:
        summary['coefficients'] = coefficients
        bias = bias_of(coefficients)
        if bias is not None and mean_iri is not None:
            summary['mean_iri_multi_corrected'] = mean_iri - bias
    return summary


def _result_dir_for(settings: Settings, filename: str, run_id: int) -> Path:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    return settings.storage_results_dir / f"{Path(filename).stem}__run{run_id}_{stamp}"


def execute_run(run_id: int, engine, settings: Settings) -> None:
    with Session(engine) as session:
        run = session.get(AnalysisRun, run_id)
        if run is None:
            return
        source = session.get(SourceFile, run.file_id)
        csv_path = settings.storage_data_dir / source.filename

        result_dir = _result_dir_for(settings, source.filename, run.id)
        result_dir.mkdir(parents=True, exist_ok=True)
        log_path = result_dir / 'run.log'

        run.status = 'running'
        run.started_at = datetime.now(timezone.utc)
        run.result_dir = str(result_dir)
        run.log_path = str(log_path)
        session.commit()

        try:
            policy = (run.params or {}).get('low_speed_policy', 'invalid')
            # Snapshot taken at run creation; absent -> the analyzer's book constants
            coefficients = (run.params or {}).get('coefficients')
            with open(log_path, 'w', encoding='utf-8') as log_file:
                with contextlib.redirect_stdout(log_file):
                    analyze(str(csv_path), str(result_dir), low_speed_policy=policy,
                            **eq3_kwargs(coefficients))
            if coefficients:
                (result_dir / 'calibration.json').write_text(
                    json.dumps(coefficients, ensure_ascii=False, indent=1),
                    encoding='utf-8')
            run.summary = build_summary(result_dir, coefficients)
            run.status = 'done'
        except Exception as exc:
            run.status = 'failed'
            run.error = f"{type(exc).__name__}: {exc}"
            # Keep the partial dir: run.log explains the failure
        finally:
            run.finished_at = datetime.now(timezone.utc)
            session.commit()


def delete_run_artifacts(run: AnalysisRun) -> None:
    if run.result_dir:
        shutil.rmtree(run.result_dir, ignore_errors=True)

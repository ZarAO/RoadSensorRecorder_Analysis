"""
Inputs of the base-vs-improved (ablation) block of run_study.py
(spec docs/superpowers/specs/2026-11-15-calibration-model-and-ablation-design.md §4).

Runs the analyzer on every study recording once per variant - INCLUDING the
full method, so base and ablated outputs always come from the same analyzer
code - and writes manifest.json with a hash of the analyzer sources; run_study.py
refuses ablation inputs produced by a different analyzer, and a 'full' that
differs from its own inputs. The list of recordings comes from run_study.py
itself (DATASETS, CROSS_VEHICLE_DATASETS).

Run from the repo root (takes a few minutes):
    .venv/Scripts/python.exe studies/profilometer_validation/make_ablation_inputs.py
"""

import contextlib
import io
import json
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

from road_quality_analyzer.cli import analyze  # noqa: E402
from run_study import ABLATION_ROOT, REPO_ROOT, analyzer_source_hash, study_recordings  # noqa: E402

VARIANTS = {
    'full': {},
    'no_orientation': {'ablate_orientation': True},
    'time_segments': {'ablate_segmentation_time': True},
    'no_speed_gate': {'ablate_speed_gate': True},
}


def _source_csv(ds) -> Path:
    meta = Path(REPO_ROOT / ds['segments_csv']).parent / 'recording_meta.json'
    return REPO_ROOT / json.loads(meta.read_text(encoding='utf-8'))['source_file']


def main() -> None:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    for _, ds in study_recordings():
        folder = Path(ds['segments_csv']).parent.name
        for variant, switches in VARIANTS.items():
            out = REPO_ROOT / ABLATION_ROOT / variant / folder
            with contextlib.redirect_stdout(io.StringIO()):
                analyze(str(_source_csv(ds)), str(out), **switches)
            print(f'✓ {variant}: {folder}')
    manifest = {'analyzer_source_sha256': analyzer_source_hash(), 'variants': sorted(VARIANTS)}
    (REPO_ROOT / ABLATION_ROOT / 'manifest.json').write_text(
        json.dumps(manifest, indent=1, sort_keys=True), encoding='utf-8')
    print(f"✓ manifest.json: {manifest['analyzer_source_sha256'][:12]}…")


if __name__ == '__main__':
    main()

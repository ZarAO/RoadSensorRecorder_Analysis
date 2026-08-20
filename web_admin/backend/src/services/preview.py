"""
Upload-time preview: one light pass over the CSV for duration/rate/GPS
coverage plus the recording metadata (Stage D). Reuses the analyzer's
contract definitions — no duplicate parsing logic.
"""

import dataclasses

import pandas as pd

from road_quality_analyzer.io import parse_recording_metadata
from road_quality_analyzer.io.ingestion import EXPECTED_COLUMNS


def _validate_header(path: str) -> None:
    """The first non-comment line must be exactly the v2 contract header."""
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('#'):
                continue
            header = [c.strip() for c in line.rstrip('\r\n').split(',')]
            if header != EXPECTED_COLUMNS:
                raise ValueError(
                    f"Unexpected CSV header: expected {EXPECTED_COLUMNS}, "
                    f"found {header}"
                )
            return
    raise ValueError("Empty file: no header row found")


def probe_csv(path: str) -> dict:
    """
    Returns {duration_s, fs_hz, gps_coverage_ratio, recording_meta}.

    Raises ValueError when the header violates the v2 contract; the comment
    layer is optional and never raises (pre-v2.1 files give empty metadata).
    """
    _validate_header(path)

    df = pd.read_csv(path, comment='#', usecols=['Time', 'Type'], index_col=False)
    if len(df) == 0 or not pd.api.types.is_numeric_dtype(df['Time']):
        raise ValueError("CSV has no numeric Time rows to preview")

    t_min, t_max = float(df['Time'].min()), float(df['Time'].max())
    # The contract Time column is epoch-ms; second-scale files still preview
    # sanely because ratios cancel the unit except duration
    divisor = 1000.0 if t_max >= 1e11 else 1.0
    duration_s = (t_max - t_min) / divisor

    type_lower = df['Type'].astype(str).str.lower()
    accel_count = int((type_lower == 'accelerometer').sum())
    fs_hz = accel_count / duration_s if duration_s > 0 else None

    gps_times = df.loc[type_lower == 'location', 'Time']
    if len(gps_times) >= 2 and t_max > t_min:
        gps_coverage = (float(gps_times.max()) - float(gps_times.min())) / (t_max - t_min)
    else:
        gps_coverage = 0.0

    meta = parse_recording_metadata(path)
    meta_dict = dataclasses.asdict(meta)
    meta_dict['clean_stop'] = meta.clean_stop
    meta_dict['incident_count'] = meta.incident_count

    return {
        'duration_s': duration_s,
        'fs_hz': fs_hz,
        'gps_coverage_ratio': gps_coverage,
        'recording_meta': meta_dict,
    }

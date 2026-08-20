"""
Segmentation into 100m segments
Section B7 - Distance-based segmentation
"""

import numpy as np
import pandas as pd
from typing import Dict

# A segment shorter than this is considered partial (recording tail) and
# excluded from report means
MIN_FULL_SEGMENT_M = 90.0

# Survey speed range from the guidebook (Eq.4/5/6 calibrated at 30/50/80 km/h)
SPEED_VALID_MIN_KMH = 20.0
SPEED_VALID_MAX_KMH = 100.0

# Spatial sampling requirement
DX_COMPLIANT_M = 0.3

# A segment driven slower than this is LOW-SPEED: the road itself, not the driver,
# sets the pace. Same threshold as the low side of speed_valid - above
# SPEED_VALID_MAX_KMH a segment is plain speed-invalid, never low-speed.
LOW_SPEED_MAX_KMH = SPEED_VALID_MIN_KMH

# low_speed_class written for a segment that is NOT low-speed
NORMAL_SPEED_CLASS = 'normal'

# CLI policy -> categorical label for a low-speed segment. The label is the whole
# output: IRI_multi stays NaN under every policy, because Eq.4/5/6 are calibrated
# at 30/50/80 km/h and have no meaning below the survey range.
LOW_SPEED_CLASS_BY_POLICY = {
    'very-poor': 'very_poor',
    'poor': 'poor',
    'invalid': 'invalid',
    'ignore': 'ignore',
}

DEFAULT_LOW_SPEED_POLICY = 'invalid'


def create_segments(
    s_grid: np.ndarray,
    segment_length_m: float = 100.0
) -> Dict[int, np.ndarray]:
    """
    Create 100 m segments based on cumulative distance

    Per B7:
    seg_id = floor(s / 100)
    bounds: [100*seg_id, 100*(seg_id+1))

    Args:
        s_grid: cumulative distance (meters) for each sample
        segment_length_m: segment length (default 100 m)

    Returns:
        segments: dict {seg_id: indices array}

    Raises:
        ValueError: if s_grid holds non-finite samples (distance is unknown
            outside GPS coverage; np.floor(NaN).astype(int) would silently
            create a phantom segment with a garbage seg_id)
    """
    if not np.all(np.isfinite(s_grid)):
        raise ValueError(
            f"s_grid contains {int(np.sum(~np.isfinite(s_grid)))} non-finite samples: "
            "distance is undefined outside GPS coverage, so those samples must be "
            "dropped before segmentation."
        )

    seg_ids = np.floor(s_grid / segment_length_m).astype(int)

    segments = {}
    for seg_id in np.unique(seg_ids):
        idx = np.where(seg_ids == seg_id)[0]
        segments[seg_id] = idx

    return segments


def longest_finite_run(signal: np.ndarray) -> np.ndarray:
    """
    Longest contiguous run of finite samples

    Distress removal (B8) writes NaN into the anomaly windows. Dropping those
    samples and butting the survivors together would splice step discontinuities
    into the signal Welch sees, injecting broadband energy right across the Eq.3
    band, so the PSD is computed on the longest clean run instead. If that run is
    shorter than fs*2 the segment simply has no IRI_psd (NaN, never a fabricated
    value).

    Args:
        signal: signal that may contain NaN

    Returns:
        the longest contiguous finite slice (empty if the signal has none)
    """
    finite = np.isfinite(signal)
    if finite.all():
        return signal

    # Run boundaries: +1 where a finite run starts, -1 where it ends
    edges = np.diff(finite.astype(np.int8))
    starts = np.flatnonzero(edges == 1) + 1
    ends = np.flatnonzero(edges == -1) + 1
    if finite.size and finite[0]:
        starts = np.concatenate(([0], starts))
    if finite.size and finite[-1]:
        ends = np.concatenate((ends, [finite.size]))

    if len(starts) == 0:
        return signal[:0]

    longest = np.argmax(ends - starts)
    return signal[starts[longest]:ends[longest]]


def aggregate_segment_metrics(
    seg_id: int,
    indices: np.ndarray,
    a_vertical_g: np.ndarray,
    a_vertical_g_psd: np.ndarray,
    v_grid: np.ndarray,
    s_grid: np.ndarray,
    fs: float,
    anomaly_mask: np.ndarray = None,
    scalar_mode: str = 'mean_psd_sqrt',
    f_low: float = 0.5,
    f_high: float = 6.0,
    low_speed_policy: str = DEFAULT_LOW_SPEED_POLICY,
    iri_psd_A: float = None,
    iri_psd_B: float = None,
    **kwargs
) -> Dict:
    """
    Aggregate metrics for a single segment

    Args:
        seg_id: segment ID
        indices: sample indices within the segment
        a_vertical_g: vertical acceleration in g (band-pass)
        a_vertical_g_psd: same, after distress removal (NaN in anomaly windows)
        v_grid: speed (m/s)
        s_grid: cumulative distance (m)
        fs: sampling rate (Hz)
        anomaly_mask: anomaly mask (optional)
        scalar_mode: PSD scalarization mode
        f_low, f_high: Welch band for Eq.3 (must match the band-pass the caller applied)
        low_speed_policy: label written into low_speed_class for a segment below
            LOW_SPEED_MAX_KMH (see LOW_SPEED_CLASS_BY_POLICY)
        **kwargs: additional metrics to store

    Returns:
        metrics: dict with the segment's metrics

    Raises:
        ValueError: if low_speed_policy is not one of LOW_SPEED_CLASS_BY_POLICY
    """
    from road_quality_analyzer.metrics.grms import compute_grms
    from road_quality_analyzer.metrics.iri import (
        compute_iri_psd, compute_iri_multi, VehicleType, IRI_MULTI_DEFAULT_PARAMS
    )

    if low_speed_policy not in LOW_SPEED_CLASS_BY_POLICY:
        raise ValueError(
            f"Unknown low_speed_policy {low_speed_policy!r}; expected one of "
            f"{sorted(LOW_SPEED_CLASS_BY_POLICY)}"
        )

    if len(indices) == 0:
        return None

    # Base metrics
    seg_a_vert = a_vertical_g[indices]
    seg_v = v_grid[indices]
    seg_s = s_grid[indices]

    mean_speed_mps = np.mean(seg_v)
    mean_speed_kmh = mean_speed_mps * 3.6
    length_m = seg_s[-1] - seg_s[0]

    # A road that cannot be driven faster than LOW_SPEED_MAX_KMH excites the
    # suspension below the 0.5-6 Hz band the IRI models read, so the segment is
    # labelled and referred to a Class 1/2 (laser profilometer) survey instead of
    # being given a number.
    low_speed = bool(mean_speed_kmh < LOW_SPEED_MAX_KMH)

    metrics = {
        'seg_id': seg_id,
        's_start': seg_s[0],
        's_end': seg_s[-1],
        'length_m': length_m,
        'partial': bool(length_m < MIN_FULL_SEGMENT_M),
        'n_samples': len(indices),
        'mean_speed_mps': mean_speed_mps,
        'mean_speed_kmh': mean_speed_kmh,
        'speed_valid': bool(SPEED_VALID_MIN_KMH <= mean_speed_kmh <= SPEED_VALID_MAX_KMH),
        'low_speed_class': (
            LOW_SPEED_CLASS_BY_POLICY[low_speed_policy] if low_speed
            else NORMAL_SPEED_CLASS
        ),
        'needs_class12_survey': low_speed,
        'dx_le_03_share': float(np.mean((seg_v / fs) <= DX_COMPLIANT_M)),
    }

    # Grms
    metrics['grms'] = compute_grms(seg_a_vert)

    # IRI_psd on the signal without distress windows: Welch runs on the longest
    # contiguous clean run, never on chunks spliced across the removed windows
    seg_psd_input = longest_finite_run(a_vertical_g_psd[indices])

    iri_psd_raw, iri_psd, debug_info = compute_iri_psd(
        seg_psd_input, fs, f_low=f_low, f_high=f_high,
        scalar_mode=scalar_mode, return_debug=True,
        A=iri_psd_A, B=iri_psd_B
    )
    metrics['iri_psd_raw'] = iri_psd_raw
    metrics['iri_psd'] = iri_psd

    # Debug fields (B)
    metrics['psd_band_power'] = debug_info['psd_band_power']
    metrics['psd_sqrt_scalar'] = debug_info['psd_sqrt_scalar']
    metrics['psd_scalar_mode'] = debug_info['psd_scalar_mode']
    metrics['psd_n_samples_used'] = debug_info['psd_n_samples_used']
    metrics['psd_df_hz'] = debug_info['psd_df_hz']
    metrics['fs_used_hz'] = fs

    # IRI_multi (GENERIC by default).
    # Eq.4/5/6 carry a speed term and are calibrated for 20-100 km/h only - outside
    # that range NaN, not 0. Eq.3 has no speed term, so iri_psd is not gated here
    # and keeps its contract iri_psd == max(0, iri_psd_raw).
    if metrics['speed_valid']:
        metrics['iri_multi'] = compute_iri_multi(
            metrics['grms'],
            mean_speed_kmh,
            vehicle_type=VehicleType.GENERIC,
            **IRI_MULTI_DEFAULT_PARAMS
        )
    else:
        metrics['iri_multi'] = np.nan

    # Anomaly count
    if anomaly_mask is not None:
        metrics['anomaly_count'] = int(np.sum(anomaly_mask[indices]))
    else:
        metrics['anomaly_count'] = 0

    # Event rate. The threshold detector keeps working below the survey speed
    # range, so this is what a low-speed segment reports instead of an IRI. A
    # zero-length segment (a single sample) has no rate: NaN, never a division
    # by zero.
    metrics['events_per_km'] = (
        metrics['anomaly_count'] / (length_m / 1000.0) if length_m > 0 else np.nan
    )

    # Additional metrics
    for key, value in kwargs.items():
        if isinstance(value, np.ndarray):
            metrics[key] = np.mean(value[indices])
        else:
            metrics[key] = value

    return metrics


def create_segments_dataframe(
    s_grid: np.ndarray,
    a_vertical_g: np.ndarray,
    a_vertical_g_psd: np.ndarray,
    v_grid: np.ndarray,
    fs: float,
    anomaly_mask: np.ndarray = None,
    segment_length_m: float = 100.0,
    scalar_mode: str = 'mean_psd_sqrt',
    f_low: float = 0.5,
    f_high: float = 6.0,
    low_speed_policy: str = DEFAULT_LOW_SPEED_POLICY,
    iri_psd_A: float = None,
    iri_psd_B: float = None
) -> pd.DataFrame:
    """
    Create a DataFrame with metrics per 100 m segment

    Args:
        s_grid: cumulative distance (m)
        a_vertical_g: vertical acceleration in g (band-pass)
        a_vertical_g_psd: same, after distress removal (NaN in anomaly windows)
        v_grid: speed (m/s)
        fs: sampling rate (Hz)
        anomaly_mask: anomaly mask
        segment_length_m: segment length (m)
        scalar_mode: PSD scalarization mode
        f_low, f_high: Welch band for Eq.3 (must match the band-pass the caller applied)
        low_speed_policy: label for segments below LOW_SPEED_MAX_KMH

    Returns:
        df: DataFrame with segment metrics
    """
    segments = create_segments(s_grid, segment_length_m)

    metrics_list = []
    for seg_id, indices in segments.items():
        metrics = aggregate_segment_metrics(
            seg_id, indices, a_vertical_g, a_vertical_g_psd, v_grid, s_grid,
            fs, anomaly_mask, scalar_mode=scalar_mode, f_low=f_low, f_high=f_high,
            low_speed_policy=low_speed_policy, iri_psd_A=iri_psd_A, iri_psd_B=iri_psd_B
        )
        if metrics is not None:
            metrics_list.append(metrics)

    df = pd.DataFrame(metrics_list)
    return df

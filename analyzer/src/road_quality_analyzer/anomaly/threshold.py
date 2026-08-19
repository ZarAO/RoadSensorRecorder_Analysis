"""
Anomaly detection (threshold)
Section A5 - Threshold-based detection
"""

import numpy as np


def detect_threshold_anomalies(
    a_vertical: np.ndarray,
    threshold_ms2: float = 10.0
) -> np.ndarray:
    """
    Detect anomalies via threshold

    Per A5 (Book Canon):
    anomaly(t) = [a_vertical(t) > 10 m/s²]

    NOTE: the pipeline feeds this the gravity-removed vertical acceleration in
    world-frame, while the guidebook specifies 10 m/s² for raw accelerometer
    readings. The value is kept as the book baseline, but it is NOT calibrated
    to this signal or to a specific device.

    Args:
        a_vertical: vertical acceleration (m/s², after gravity removal)
        threshold_ms2: threshold (default 10 m/s²)

    Returns:
        anomaly_mask: boolean mask, True where an anomaly occurs
    """
    anomaly_mask = np.abs(a_vertical) > threshold_ms2
    return anomaly_mask


def remove_distress_windows(
    signal: np.ndarray,
    anomaly_mask: np.ndarray,
    fs: float,
    window_sec: float = 0.5
) -> np.ndarray:
    """
    Remove windows around distress events for PSD

    Per B8: cut out ±w seconds around each distress event

    Args:
        signal: signal to clean
        anomaly_mask: anomaly mask
        fs: sampling rate (Hz)
        window_sec: window size around anomaly (seconds)

    Returns:
        cleaned_signal: signal with NaN at distress locations
    """
    cleaned_signal = signal.copy()

    # Find anomaly indices
    anomaly_indices = np.where(anomaly_mask)[0]

    # Window size in samples
    window_samples = int(window_sec * fs)

    # Mask ±window around each anomaly
    for idx in anomaly_indices:
        start = max(0, idx - window_samples)
        end = min(len(signal), idx + window_samples + 1)
        cleaned_signal[start:end] = np.nan
    
    return cleaned_signal

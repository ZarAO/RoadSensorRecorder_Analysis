"""
Band-pass filtering of the vertical acceleration
Step 5 - Filtering (0.5-6 Hz, per guidebook: iRoad / Byrne et al.)
"""

import numpy as np
from scipy.signal import butter, filtfilt


def apply_bandpass(
    signal: np.ndarray,
    fs: float,
    f_low: float = 0.5,
    f_high: float = 6.0,
    order: int = 4
) -> np.ndarray:
    """
    Zero-phase Butterworth band-pass filter.

    Removes drift/residual gravity below f_low and engine/tire vibration
    above f_high before computing Grms and PSD metrics.

    Args:
        signal: input signal (uniformly sampled)
        fs: sampling rate (Hz)
        f_low, f_high: band edges (Hz)
        order: Butterworth filter order

    Returns:
        filtered signal of the same length

    Raises:
        ValueError: if the band does not fit within [0, Nyquist]
    """
    nyq = 0.5 * fs
    if not 0.0 < f_low < f_high < nyq:
        raise ValueError(
            f"Band [{f_low}, {f_high}] Hz is not valid for fs={fs:.1f} Hz "
            f"(Nyquist {nyq:.1f} Hz)"
        )

    b, a = butter(order, [f_low / nyq, f_high / nyq], btype='band', analog=False)
    return filtfilt(b, a, signal)

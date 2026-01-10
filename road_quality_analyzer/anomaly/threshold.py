"""
Anomaly detection (threshold)
Розділ A5 - Threshold-based detection
"""

import numpy as np


def detect_threshold_anomalies(
    a_vertical: np.ndarray,
    threshold_ms2: float = 10.0
) -> np.ndarray:
    """
    Виявити аномалії через threshold
    
    Згідно A5 (Book Canon):
    anomaly(t) = [a_vertical(t) > 10 м/с²]
    
    Args:
        a_vertical: вертикальне прискорення (м/с²)
        threshold_ms2: поріг (за замовчуванням 10 м/с²)
        
    Returns:
        anomaly_mask: boolean маска True де аномалія
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
    Вилучити вікна навколо distress events для PSD
    
    Згідно B8: вирізати ±w секунд навколо кожного distress
    
    Args:
        signal: сигнал для очищення
        anomaly_mask: маска аномалій
        fs: частота семплювання (Гц)
        window_sec: розмір вікна навколо аномалії (секунди)
        
    Returns:
        cleaned_signal: сигнал з NaN в місцях distress
    """
    cleaned_signal = signal.copy()
    
    # Знайти індекси аномалій
    anomaly_indices = np.where(anomaly_mask)[0]
    
    # Розмір вікна в семплах
    window_samples = int(window_sec * fs)
    
    # Маскувати ±window навколо кожної аномалії
    for idx in anomaly_indices:
        start = max(0, idx - window_samples)
        end = min(len(signal), idx + window_samples + 1)
        cleaned_signal[start:end] = np.nan
    
    return cleaned_signal

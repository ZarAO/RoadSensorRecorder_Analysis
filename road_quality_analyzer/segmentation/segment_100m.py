"""
Segmentation into 100m segments
Згідно з agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md розділ B7
"""

import numpy as np
import pandas as pd
from typing import Dict, List


def create_segments(
    s_grid: np.ndarray,
    segment_length_m: float = 100.0
) -> Dict[int, np.ndarray]:
    """
    Створити 100 м сегменти на базі cumulative distance
    
    Згідно B7:
    seg_id = floor(s / 100)
    межі: [100*seg_id, 100*(seg_id+1))
    
    Args:
        s_grid: cumulative distance (метри) для кожного семпла
        segment_length_m: довжина сегмента (за замовчуванням 100 м)
        
    Returns:
        segments: dict {seg_id: indices масив}
    """
    seg_ids = np.floor(s_grid / segment_length_m).astype(int)
    
    segments = {}
    for seg_id in np.unique(seg_ids):
        idx = np.where(seg_ids == seg_id)[0]
        segments[seg_id] = idx
    
    return segments


def aggregate_segment_metrics(
    seg_id: int,
    indices: np.ndarray,
    a_vertical_g: np.ndarray,
    v_grid: np.ndarray,
    s_grid: np.ndarray,
    fs: float,
    anomaly_mask: np.ndarray = None,
    scalar_mode: str = 'band_power_sqrt',
    **kwargs
) -> Dict:
    """
    Агрегувати метрики для одного сегмента
    
    Args:
        seg_id: ID сегмента
        indices: індекси семплів у сегменті
        a_vertical_g: вертикальне прискорення в g
        v_grid: швидкість (м/с)
        s_grid: cumulative distance (м)
        fs: частота семплювання (Гц)
        anomaly_mask: маска аномалій (опціонально)
        scalar_mode: режим скаляризації PSD
        **kwargs: додаткові метрики для збереження
        
    Returns:
        metrics: dict з метриками сегмента
    """
    from road_quality_analyzer.metrics.grms import compute_grms
    from road_quality_analyzer.metrics.iri import compute_iri_psd, compute_iri_multi, VehicleType
    
    if len(indices) == 0:
        return None
    
    # Базові метрики
    seg_a_vert = a_vertical_g[indices]
    seg_v = v_grid[indices]
    seg_s = s_grid[indices]
    
    metrics = {
        'seg_id': seg_id,
        's_start': seg_s[0],
        's_end': seg_s[-1],
        'length_m': seg_s[-1] - seg_s[0],
        'n_samples': len(indices),
        'valid_ratio': len(indices) / max(1, len(indices)),  # Поки що 1.0
        'mean_speed_mps': np.mean(seg_v),
        'mean_speed_kmh': np.mean(seg_v) * 3.6,
    }
    
    # Grms
    if len(seg_a_vert) > 0:
        metrics['grms'] = compute_grms(seg_a_vert)
    else:
        metrics['grms'] = 0.0
    
    # IRI_psd (потрібно достатньо семплів)
    if len(seg_a_vert) >= fs * 2:  # Мінімум 2 секунди
        try:
            iri_psd_raw, iri_psd, debug_info = compute_iri_psd(
                seg_a_vert, fs, scalar_mode=scalar_mode, return_debug=True
            )
            metrics['iri_psd_raw'] = iri_psd_raw
            metrics['iri_psd'] = iri_psd
            
            # Debug поля (B)
            metrics['psd_band_power'] = debug_info.get('psd_band_power', np.nan)
            metrics['psd_sqrt_scalar'] = debug_info.get('psd_sqrt_scalar', np.nan)
            metrics['psd_scalar_mode'] = debug_info.get('psd_scalar_mode', scalar_mode)
            metrics['psd_n_samples_used'] = debug_info.get('psd_n_samples_used', len(seg_a_vert))
            metrics['psd_df_hz'] = debug_info.get('psd_df_hz', np.nan)
            metrics['fs_used_hz'] = fs
        except Exception as e:
            metrics['iri_psd_raw'] = np.nan
            metrics['iri_psd'] = np.nan
            metrics['psd_band_power'] = np.nan
            metrics['psd_sqrt_scalar'] = np.nan
            metrics['psd_scalar_mode'] = scalar_mode
            metrics['psd_n_samples_used'] = len(seg_a_vert)
            metrics['psd_df_hz'] = np.nan
            metrics['fs_used_hz'] = fs
    else:
        metrics['iri_psd_raw'] = np.nan
        metrics['iri_psd'] = np.nan
        metrics['psd_band_power'] = np.nan
        metrics['psd_sqrt_scalar'] = np.nan
        metrics['psd_scalar_mode'] = scalar_mode
        metrics['psd_n_samples_used'] = len(seg_a_vert)
        metrics['psd_df_hz'] = np.nan
        metrics['fs_used_hz'] = fs
    
    # IRI_multi (GENERIC за замовчуванням)
    if metrics['grms'] > 0:
        metrics['iri_multi'] = compute_iri_multi(
            metrics['grms'],
            metrics['mean_speed_kmh'],
            vehicle_type=VehicleType.GENERIC
        )
    else:
        metrics['iri_multi'] = 0.0
    
    # Anomaly count
    if anomaly_mask is not None:
        metrics['anomaly_count'] = np.sum(anomaly_mask[indices])
    else:
        metrics['anomaly_count'] = 0
    
    # Додаткові метрики
    for key, value in kwargs.items():
        if isinstance(value, np.ndarray):
            metrics[key] = np.mean(value[indices])
        else:
            metrics[key] = value
    
    return metrics


def create_segments_dataframe(
    s_grid: np.ndarray,
    a_vertical_g: np.ndarray,
    v_grid: np.ndarray,
    fs: float,
    anomaly_mask: np.ndarray = None,
    segment_length_m: float = 100.0,
    scalar_mode: str = 'band_power_sqrt'
) -> pd.DataFrame:
    """
    Створити DataFrame з метриками по 100 м сегментах
    
    Args:
        s_grid: cumulative distance (м)
        a_vertical_g: вертикальне прискорення в g
        v_grid: швидкість (м/с)
        fs: частота семплювання (Гц)
        anomaly_mask: маска аномалій
        segment_length_m: довжина сегмента (м)
        scalar_mode: режим скаляризації PSD
        
    Returns:
        df: DataFrame з метриками сегментів
    """
    segments = create_segments(s_grid, segment_length_m)
    
    metrics_list = []
    for seg_id, indices in segments.items():
        metrics = aggregate_segment_metrics(
            seg_id, indices, a_vertical_g, v_grid, s_grid, fs, 
            anomaly_mask, scalar_mode=scalar_mode
        )
        if metrics is not None:
            metrics_list.append(metrics)
    
    df = pd.DataFrame(metrics_list)
    return df

"""
Time grid and distance grid utilities
"""

import numpy as np
from scipy.interpolate import interp1d
from typing import Tuple


def build_uniform_time_grid(
    accel_time: np.ndarray,
    accel_x: np.ndarray,
    accel_y: np.ndarray,
    accel_z: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Побудувати uniform time grid для акселя на базі median dt
    
    Args:
        accel_time: час семплів акселя (секунди)
        accel_x, accel_y, accel_z: компоненти акселя (м/с²)
        
    Returns:
        (t_grid, ax_grid, ay_grid, az_grid) - інтерпольовані на t_grid
    """
    # Обчислити median dt
    dt_samples = np.diff(accel_time)
    dt_median = np.median(dt_samples)
    
    # Побудувати uniform grid
    t_start = accel_time[0]
    t_end = accel_time[-1]
    t_grid = np.arange(t_start, t_end, dt_median)
    
    # Інтерполяція (linear)
    interp_x = interp1d(accel_time, accel_x, kind='linear', 
                        bounds_error=False, fill_value='extrapolate')
    interp_y = interp1d(accel_time, accel_y, kind='linear',
                        bounds_error=False, fill_value='extrapolate')
    interp_z = interp1d(accel_time, accel_z, kind='linear',
                        bounds_error=False, fill_value='extrapolate')
    
    ax_grid = interp_x(t_grid)
    ay_grid = interp_y(t_grid)
    az_grid = interp_z(t_grid)
    
    return t_grid, ax_grid, ay_grid, az_grid


def compute_gps_distance(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """
    Обчислити cumulative distance з GPS (haversine)
    
    Args:
        lat, lon: широта/довгота (градуси)
        
    Returns:
        s: cumulative distance (метри)
    """
    R = 6371000.0  # радіус Землі в метрах
    
    # Конвертувати в радіани
    lat_rad = np.deg2rad(lat)
    lon_rad = np.deg2rad(lon)
    
    # Обчислити відстані між сусідніми точками
    dlat = np.diff(lat_rad)
    dlon = np.diff(lon_rad)
    
    a = (np.sin(dlat/2)**2 + 
         np.cos(lat_rad[:-1]) * np.cos(lat_rad[1:]) * np.sin(dlon/2)**2)
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
    distances = R * c
    
    # Cumulative sum
    s = np.zeros(len(lat))
    s[1:] = np.cumsum(distances)
    
    return s


def build_distance_grid(
    gps_time: np.ndarray,
    gps_lat: np.ndarray,
    gps_lon: np.ndarray,
    t_grid: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Побудувати cumulative distance s(t) та швидкість v(t) на t_grid
    
    Args:
        gps_time: час GPS семплів (секунди)
        gps_lat, gps_lon: координати (градуси)
        t_grid: uniform time grid (секунди)
        
    Returns:
        (s_grid, v_grid) - відстань (м) та швидкість (м/с) на t_grid
    """
    # Обчислити cumulative distance на GPS семплах
    s_gps = compute_gps_distance(gps_lat, gps_lon)
    
    # Інтерполювати на t_grid
    interp_s = interp1d(gps_time, s_gps, kind='linear',
                        bounds_error=False, fill_value='extrapolate')
    s_grid = interp_s(t_grid)
    
    # Обчислити швидкість v = ds/dt
    dt = np.median(np.diff(t_grid))
    v_grid = np.gradient(s_grid, dt)
    
    # Згладжування швидкості (moving average, вікно 1 секунда)
    window_size = max(1, int(1.0 / dt))
    if window_size > 1:
        kernel = np.ones(window_size) / window_size
        v_grid = np.convolve(v_grid, kernel, mode='same')
    
    # Обрізати негативні швидкості
    v_grid = np.maximum(v_grid, 0.0)
    
    return s_grid, v_grid

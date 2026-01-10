"""
GPS heading and perpendicular acceleration
Згідно з agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md розділи B1, B2, B3.4
"""

import numpy as np
from typing import Tuple


def latlon_to_enu(
    lat: np.ndarray,
    lon: np.ndarray,
    lat0: float = None
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Перетворити lat/lon в локальні метри (ENU-апроксимація)
    
    Згідно B1: equirectangular approximation для малих ділянок
    x = R·cos(lat0)·(lon - lon0)
    y = R·(lat - lat0)
    
    Args:
        lat, lon: широта/довгота в градусах
        lat0: опорна широта (якщо None, береться перша точка)
        
    Returns:
        (x, y) в метрах
    """
    R = 6371000.0  # радіус Землі в метрах
    
    # Конвертувати в радіани
    lat_rad = np.deg2rad(lat)
    lon_rad = np.deg2rad(lon)
    
    # Опорна точка
    if lat0 is None:
        lat0_rad = lat_rad[0]
        lon0_rad = lon_rad[0]
    else:
        lat0_rad = np.deg2rad(lat0)
        lon0_rad = lon_rad[0]
    
    # ENU координати
    x = R * np.cos(lat0_rad) * (lon_rad - lon0_rad)
    y = R * (lat_rad - lat0_rad)
    
    return x, y


def compute_gps_heading(
    gps_time: np.ndarray,
    gps_lat: np.ndarray,
    gps_lon: np.ndarray,
    t_grid: np.ndarray,
    heading_min_speed_mps: float = 1.0
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Обчислити heading з GPS на t_grid
    
    Згідно B2: heading = normalize([Δx, Δy, 0]) між сусідніми GPS точками
    Якщо швидкість < heading_min_speed_mps, heading невизначений
    
    Args:
        gps_time: час GPS семплів (секунди)
        gps_lat, gps_lon: координати (градуси)
        t_grid: uniform time grid (секунди)
        heading_min_speed_mps: мінімальна швидкість для валідного heading (м/с)
        
    Returns:
        (heading_x, heading_y, heading_valid) на t_grid
        heading_valid: маска True де heading валідний
    """
    from scipy.interpolate import interp1d
    
    # Перетворити GPS в ENU
    x_gps, y_gps = latlon_to_enu(gps_lat, gps_lon)
    
    # Інтерполювати на t_grid
    interp_x = interp1d(gps_time, x_gps, kind='linear',
                        bounds_error=False, fill_value='extrapolate')
    interp_y = interp1d(gps_time, y_gps, kind='linear',
                        bounds_error=False, fill_value='extrapolate')
    
    x_grid = interp_x(t_grid)
    y_grid = interp_y(t_grid)
    
    # Обчислити heading з градієнтів
    dt = np.median(np.diff(t_grid))
    dx = np.gradient(x_grid, dt)
    dy = np.gradient(y_grid, dt)
    
    # Швидкість
    speed = np.sqrt(dx**2 + dy**2)
    
    # Нормалізувати heading
    heading_x = np.zeros_like(dx)
    heading_y = np.zeros_like(dy)
    heading_valid = speed >= heading_min_speed_mps
    
    # Де швидкість достатня, нормалізувати
    valid_idx = np.where(heading_valid)[0]
    for i in valid_idx:
        norm = np.sqrt(dx[i]**2 + dy[i]**2)
        if norm > 1e-6:
            heading_x[i] = dx[i] / norm
            heading_y[i] = dy[i] / norm
    
    return heading_x, heading_y, heading_valid


def compute_perpendicular_accel(
    a_lin_world_x: np.ndarray,
    a_lin_world_y: np.ndarray,
    a_lin_world_z: np.ndarray,
    heading_x: np.ndarray,
    heading_y: np.ndarray,
    heading_valid: np.ndarray
) -> np.ndarray:
    """
    Обчислити горизонтальне прискорення перпендикулярне до руху
    
    Згідно B3.4:
    p_hat = normalize(z_world × h_hat)
    a_perp = a_lin_world · p_hat
    
    Маскуємо a_perp коли heading невалідний (швидкість низька)
    
    Args:
        a_lin_world_x, _y, _z: лінійне прискорення в world координатах (м/с²)
        heading_x, heading_y: heading unit vector
        heading_valid: маска валідності heading
        
    Returns:
        a_perp: перпендикулярне прискорення (м/с²), NaN де heading невалідний
    """
    N = len(a_lin_world_x)
    a_perp = np.full(N, np.nan)
    
    z_world = np.array([0.0, 0.0, 1.0])
    
    for i in range(N):
        if not heading_valid[i]:
            continue
        
        # h_hat в 3D (горизонтальний)
        h_hat = np.array([heading_x[i], heading_y[i], 0.0])
        
        # p_hat = z_world × h_hat (перпендикуляр у горизонтальній площині)
        p_hat = np.cross(z_world, h_hat)
        p_norm = np.linalg.norm(p_hat)
        
        if p_norm < 1e-6:
            continue
        
        p_hat = p_hat / p_norm
        
        # Скалярний добуток
        a_vec = np.array([a_lin_world_x[i], a_lin_world_y[i], a_lin_world_z[i]])
        a_perp[i] = np.dot(a_vec, p_hat)
    
    return a_perp

"""
GPS heading
Sections B1, B2, B3.4 - GPS-based heading
"""

import numpy as np
from typing import Tuple


def latlon_to_enu(
    lat: np.ndarray,
    lon: np.ndarray,
    lat0: float = None
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Convert lat/lon to local meters (ENU approximation)

    Per B1: equirectangular approximation for small areas
    x = R·cos(lat0)·(lon - lon0)
    y = R·(lat - lat0)

    Args:
        lat, lon: latitude/longitude in degrees
        lat0: reference latitude (if None, the first point is used)

    Returns:
        (x, y) in meters
    """
    R = 6371000.0  # Earth radius in meters

    # Convert to radians
    lat_rad = np.deg2rad(lat)
    lon_rad = np.deg2rad(lon)

    # Reference point
    if lat0 is None:
        lat0_rad = lat_rad[0]
        lon0_rad = lon_rad[0]
    else:
        lat0_rad = np.deg2rad(lat0)
        lon0_rad = lon_rad[0]

    # ENU coordinates
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
    Compute heading from GPS on t_grid

    Per B2: heading = normalize([Δx, Δy, 0]) between neighboring GPS points
    If speed < heading_min_speed_mps, heading is undefined

    Args:
        gps_time: time of GPS samples (seconds)
        gps_lat, gps_lon: coordinates (degrees)
        t_grid: uniform time grid (seconds)
        heading_min_speed_mps: minimum speed for a valid heading (m/s)

    Returns:
        (heading_x, heading_y, heading_valid) on t_grid
        heading_valid: mask, True where heading is valid
    """
    from scipy.interpolate import interp1d
    from scipy.ndimage import uniform_filter1d

    # Convert GPS to ENU
    x_gps, y_gps = latlon_to_enu(gps_lat, gps_lon)

    # Interpolate onto t_grid
    interp_x = interp1d(gps_time, x_gps, kind='linear',
                        bounds_error=False, fill_value='extrapolate')
    interp_y = interp1d(gps_time, y_gps, kind='linear',
                        bounds_error=False, fill_value='extrapolate')

    x_grid = interp_x(t_grid)
    y_grid = interp_y(t_grid)

    dt = np.median(np.diff(t_grid))

    # Smooth the position BEFORE differentiating (~1 s): np.gradient amplifies GPS noise,
    # otherwise heading and the validity mask "jump" from sample to sample
    window_size = max(1, int(round(1.0 / dt)))
    if window_size > 1:
        x_grid = uniform_filter1d(x_grid, size=window_size, mode='nearest')
        y_grid = uniform_filter1d(y_grid, size=window_size, mode='nearest')

    # Compute heading from the gradients
    dx = np.gradient(x_grid, dt)
    dy = np.gradient(y_grid, dt)

    # Speed
    speed = np.hypot(dx, dy)

    # Normalize heading where speed is sufficient
    heading_x = np.zeros_like(dx)
    heading_y = np.zeros_like(dy)
    heading_valid = speed >= heading_min_speed_mps

    normalizable = heading_valid & (speed > 1e-6)
    heading_x[normalizable] = dx[normalizable] / speed[normalizable]
    heading_y[normalizable] = dy[normalizable] / speed[normalizable]

    return heading_x, heading_y, heading_valid

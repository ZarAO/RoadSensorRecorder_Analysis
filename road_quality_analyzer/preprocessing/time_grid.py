"""
Time grid and distance grid utilities
"""

import numpy as np
from scipy.interpolate import interp1d
from scipy.ndimage import uniform_filter1d
from typing import Tuple


def build_uniform_time_grid(
    accel_time: np.ndarray,
    accel_x: np.ndarray,
    accel_y: np.ndarray,
    accel_z: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Build a uniform time grid for the accelerometer based on the median dt

    Args:
        accel_time: accelerometer sample times (seconds)
        accel_x, accel_y, accel_z: accelerometer components (m/s²)

    Returns:
        (t_grid, ax_grid, ay_grid, az_grid) - interpolated onto t_grid
    """
    # Compute the median dt
    dt_samples = np.diff(accel_time)
    dt_median = np.median(dt_samples)

    # Build the uniform grid
    t_start = accel_time[0]
    t_end = accel_time[-1]
    t_grid = np.arange(t_start, t_end, dt_median)

    # Interpolation (linear)
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
    Compute cumulative distance from GPS (haversine)

    Args:
        lat, lon: latitude/longitude (degrees)

    Returns:
        s: cumulative distance (meters)
    """
    R = 6371000.0  # Earth radius in meters

    # Convert to radians
    lat_rad = np.deg2rad(lat)
    lon_rad = np.deg2rad(lon)

    # Compute distances between neighboring points
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
    Build cumulative distance s(t) and speed v(t) on t_grid

    No extrapolation is done outside the GPS time span: s and v are NaN there
    (linear extrapolation produced negative s and a spurious seg_id=-1 segment).

    Args:
        gps_time: time of GPS samples (seconds)
        gps_lat, gps_lon: coordinates (degrees)
        t_grid: uniform time grid (seconds)

    Returns:
        (s_grid, v_grid) - distance (m) and speed (m/s) on t_grid,
        NaN outside GPS coverage
    """
    # Compute cumulative distance at GPS samples
    s_gps = compute_gps_distance(gps_lat, gps_lon)

    # Interpolate onto t_grid (no extrapolation)
    interp_s = interp1d(gps_time, s_gps, kind='linear',
                        bounds_error=False, fill_value=np.nan)
    s_grid = interp_s(t_grid)

    dt = np.median(np.diff(t_grid))
    window_size = max(1, int(round(1.0 / dt)))

    # Smoothing BEFORE differentiating (numeric gradient amplifies GPS noise);
    # mode='nearest' does not pull the edges to zero like zero-padded convolve.
    # s is a cumulative sum of haversine magnitudes, so it is monotone and the
    # speed derived from it is non-negative without any clipping.
    v_grid = np.full_like(s_grid, np.nan)
    covered = np.isfinite(s_grid)
    if np.sum(covered) > 1:
        s_covered = s_grid[covered]
        if window_size > 1:
            s_covered = uniform_filter1d(s_covered, size=window_size, mode='nearest')
        v_grid[covered] = np.gradient(s_covered, dt)

    return s_grid, v_grid

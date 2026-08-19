"""
Unit tests for the uniform time grid, haversine distance and the distance grid.

Longitude varies in the distance cases on purpose: with a constant longitude the
cos(lat) term of the haversine formula is identically zero and a missing degree
conversion or a lat/lon swap would go unnoticed.
"""

import numpy as np
import pytest
from scipy.interpolate import interp1d

from road_quality_analyzer.preprocessing.time_grid import (
    build_distance_grid,
    build_uniform_time_grid,
    compute_gps_distance,
)

R_EARTH = 6371000.0
METERS_PER_DEG = R_EARTH * np.pi / 180.0  # 111 194.9 m


def constant_accel(accel_time: np.ndarray):
    """(x, y, z) channels for a phone at rest, matching accel_time's length."""
    n = len(accel_time)
    return np.linspace(0.1, 0.5, n), np.zeros(n), np.full(n, 9.8)


# --- Uniform time grid --------------------------------------------------------

def test_uniform_grid_dt_equals_expected_median():
    """diffs [0.01, 0.015, 0.01, 0.015] -> median dt = 0.0125 s."""
    accel_time = np.array([0.0, 0.01, 0.025, 0.035, 0.05])

    t_grid, ax_grid, _, _ = build_uniform_time_grid(accel_time, *constant_accel(accel_time))

    assert np.diff(t_grid) == pytest.approx(0.0125)
    assert len(ax_grid) == len(t_grid)


def test_uniform_grid_dt_is_median_not_mean():
    """
    One dropped-packet gap must not stretch the grid.

    diffs are [0.01, 0.01, 0.01, 1.0]: median = 0.01 (100 Hz), mean = 0.2575 (4 Hz).
    """
    accel_time = np.array([0.0, 0.01, 0.02, 0.03, 1.03])

    t_grid, _, _, _ = build_uniform_time_grid(accel_time, *constant_accel(accel_time))

    assert np.diff(t_grid)[0] == pytest.approx(0.01)
    assert len(t_grid) == 103          # mean dt would have produced 5
    assert np.diff(t_grid) == pytest.approx(0.01)


def test_uniform_grid_interpolates_onto_the_new_axis():
    accel_time = np.array([0.0, 0.01, 0.02, 0.03])
    accel_x = np.array([0.0, 1.0, 2.0, 3.0])

    t_grid, ax_grid, _, _ = build_uniform_time_grid(
        accel_time, accel_x, np.zeros(4), np.full(4, 9.8)
    )

    # x rises 100 per second, so the grid must reproduce that ramp exactly
    assert ax_grid == pytest.approx(100.0 * t_grid)


# --- Haversine ----------------------------------------------------------------

def test_compute_gps_distance_haversine_latitude_step():
    """0.01 deg of latitude is ~1112 m anywhere on the globe."""
    s = compute_gps_distance(np.array([50.45, 50.46]), np.array([30.52, 30.52]))

    assert s[0] == 0.0
    assert s[1] == pytest.approx(METERS_PER_DEG * 0.01, rel=1e-4)


def test_haversine_pure_longitude_step_scales_with_cos_lat():
    """
    0.01 deg of longitude at 50 deg N is ~715 m, not the ~1112 m of a bare degree.

    Dropping the cos(lat) factor would inflate every east-west leg by 1.56x.
    """
    s = compute_gps_distance(np.array([50.0, 50.0]), np.array([30.0, 30.01]))

    expected = METERS_PER_DEG * 0.01 * np.cos(np.deg2rad(50.0))
    assert s[1] == pytest.approx(expected, rel=1e-4)
    assert s[1] == pytest.approx(714.8, rel=0.01)
    assert s[1] < 0.7 * METERS_PER_DEG * 0.01


def test_haversine_diagonal_step_matches_reference():
    """Kyiv (50.45, 30.52) -> (50.46, 30.53): 1112 m north + 708 m east = 1318 m."""
    s = compute_gps_distance(np.array([50.45, 50.46]), np.array([30.52, 30.53]))

    north = METERS_PER_DEG * 0.01
    east = METERS_PER_DEG * 0.01 * np.cos(np.deg2rad(50.455))
    assert s[1] == pytest.approx(np.hypot(north, east), rel=1e-3)
    assert s[1] == pytest.approx(1318.3, rel=0.01)


def test_haversine_lat_lon_swap_gives_different_distance():
    """Guards against transposed arguments, which would silently shrink distances."""
    lat = np.array([50.0, 50.01])
    lon = np.array([30.0, 30.02])

    correct = compute_gps_distance(lat, lon)[1]
    swapped = compute_gps_distance(lon, lat)[1]

    assert correct == pytest.approx(1810.9, rel=0.01)
    assert swapped == pytest.approx(2424.3, rel=0.01)


def test_compute_gps_distance_cumulative():
    """Equal legs accumulate linearly."""
    s = compute_gps_distance(np.array([50.0, 50.01, 50.02]), np.array([30.0, 30.0, 30.0]))

    assert np.all(np.diff(s) >= 0)
    assert s[2] == pytest.approx(2 * s[1], rel=0.01)


# --- Distance grid ------------------------------------------------------------

def northbound_track(speed_mps=22.239, duration_s=10.0, gps_dt=0.5, lat0=50.0):
    """GPS samples for a constant-speed northbound drive."""
    gps_time = np.arange(0.0, duration_s + gps_dt / 2, gps_dt)
    gps_lat = lat0 + speed_mps * gps_time / METERS_PER_DEG
    gps_lon = np.full_like(gps_lat, 30.0)
    return gps_time, gps_lat, gps_lon


def test_build_distance_grid():
    """0.0001 deg of latitude every 0.5 s is 11.12 m per step, i.e. 22.24 m/s."""
    gps_time = np.arange(0.0, 10.5, 0.5)
    gps_lat = 50.0 + np.arange(len(gps_time)) * 0.0001
    gps_lon = np.full_like(gps_lat, 30.0)
    t_grid = np.arange(0.0, 10.0, 0.05)

    s_grid, v_grid = build_distance_grid(gps_time, gps_lat, gps_lon, t_grid)

    assert np.all(np.diff(s_grid) >= 0)
    assert np.all(v_grid >= 0)
    assert np.mean(v_grid[40:-40]) == pytest.approx(2 * METERS_PER_DEG * 0.0001, rel=0.01)
    assert np.mean(v_grid[40:-40]) == pytest.approx(22.24, rel=0.01)


def test_distance_grid_is_nan_outside_the_gps_time_span():
    """Extrapolating GPS would invent distance; outside the span s must be NaN."""
    gps_time, gps_lat, gps_lon = northbound_track(duration_s=5.0)
    t_grid = np.arange(0.0, 10.0, 0.01)

    s_grid, v_grid = build_distance_grid(gps_time, gps_lat, gps_lon, t_grid)

    assert np.all(np.isfinite(s_grid[t_grid <= 5.0]))
    assert np.all(np.isnan(s_grid[t_grid > 5.0]))
    assert np.all(np.isnan(v_grid[t_grid > 5.0]))


def test_velocity_smoothing_reduces_noise_std(rng):
    """
    Position is smoothed over ~1 s BEFORE differentiating.

    Without it, np.gradient on the interpolated GPS amplifies the position noise
    into a velocity trace far noisier than the true constant speed.
    """
    gps_time = np.arange(0.0, 20.5, 0.5)
    true_distance = 10.0 * gps_time
    noise = rng.normal(scale=0.5, size=len(gps_time))
    gps_lat = 50.0 + (true_distance + noise) / METERS_PER_DEG
    gps_lon = np.full_like(gps_lat, 30.0)
    t_grid = np.arange(0.0, 20.0, 0.01)

    _, v_smoothed = build_distance_grid(gps_time, gps_lat, gps_lon, t_grid)

    # Same interpolation, differentiated without the pre-smoothing step
    s_gps = compute_gps_distance(gps_lat, gps_lon)
    s_raw = interp1d(gps_time, s_gps, kind='linear')(t_grid)
    v_raw = np.gradient(s_raw, 0.01)

    interior = slice(200, -200)
    assert np.std(v_smoothed[interior]) < 0.5 * np.std(v_raw[interior])
    assert np.mean(v_smoothed[interior]) == pytest.approx(10.0, rel=0.05)


def test_backtracking_gps_still_accumulates_distance():
    """
    Haversine legs are magnitudes, so a GPS point that jumps back still adds to s.

    That is what keeps the derived speed non-negative; nothing clips it.
    """
    gps_time = np.array([0.0, 1.0, 2.0, 3.0])
    gps_lat = 50.0 + np.array([0.0, 10.0, 9.0, 20.0]) / METERS_PER_DEG
    gps_lon = np.full_like(gps_lat, 30.0)
    t_grid = np.arange(0.0, 3.0, 0.01)

    s_grid, v_grid = build_distance_grid(gps_time, gps_lat, gps_lon, t_grid)

    assert np.all(np.diff(s_grid) >= 0.0)
    assert np.all(v_grid[np.isfinite(v_grid)] > 0.0)

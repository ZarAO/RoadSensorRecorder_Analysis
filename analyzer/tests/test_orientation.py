"""
Unit tests for orientation correction (gravity alignment, GPS heading).

The synthetic drives carry real linear motion: a test built on static gravity
alone passes even with an identity rotation matrix and proves nothing.
"""

import numpy as np
import pytest

from road_quality_analyzer.orientation import (
    compute_gps_heading,
    compute_rotation_matrix,
    estimate_gravity,
    transform_to_world,
)
from road_quality_analyzer.orientation.heading import latlon_to_enu

G0 = 9.80665
FS = 100.0
N = 3000
# filtfilt of the 0.3 Hz gravity low-pass needs ~3 s per side to settle
SETTLED = slice(300, -300)


def attitude_matrix(roll_deg: float, pitch_deg: float) -> np.ndarray:
    """Orthonormal world -> body rotation for a phone held at a fixed tilt."""
    r, p = np.deg2rad(roll_deg), np.deg2rad(pitch_deg)
    rx = np.array([[1, 0, 0],
                   [0, np.cos(r), -np.sin(r)],
                   [0, np.sin(r), np.cos(r)]])
    ry = np.array([[np.cos(p), 0, np.sin(p)],
                   [0, 1, 0],
                   [-np.sin(p), 0, np.cos(p)]])
    return rx @ ry


def correct_orientation(a_body: np.ndarray, cutoff_hz: float = 0.3):
    """Run the production orientation chain on an (N, 3) body-frame recording."""
    g_hat = estimate_gravity(a_body[:, 0], a_body[:, 1], a_body[:, 2], FS,
                             cutoff_hz=cutoff_hz)
    rotations = compute_rotation_matrix(*g_hat)
    return transform_to_world(a_body[:, 0], a_body[:, 1], a_body[:, 2],
                              *g_hat, rotations)


def tilted_recording(a_world: np.ndarray, roll_deg=30.0, pitch_deg=20.0) -> np.ndarray:
    """Project a world-frame specific-force history into a tilted phone frame."""
    return a_world @ attitude_matrix(roll_deg, pitch_deg).T


# --- Gravity alignment --------------------------------------------------------

def test_tilted_phone_recovers_known_vertical_bump():
    """
    A 1 m/s^2 vertical bump on a phone tilted 30 deg roll / 20 deg pitch must come
    back at full amplitude. An identity rotation would report only cos(30)cos(20)
    of it (0.575 instead of 0.707).
    """
    amplitude = 1.0
    t = np.arange(N) / FS
    a_world = np.zeros((N, 3))
    a_world[:, 2] = G0 + amplitude * np.sin(2 * np.pi * 2.0 * t)

    a_x, a_y, _, a_vertical = correct_orientation(tilted_recording(a_world))

    assert np.std(a_vertical[SETTLED]) == pytest.approx(amplitude / np.sqrt(2), rel=0.02)
    assert np.std(a_x[SETTLED]) < 0.02 * amplitude
    assert np.std(a_y[SETTLED]) < 0.02 * amplitude


def test_lateral_only_motion_does_not_leak_into_vertical():
    """Cornering must stay horizontal; leakage into a_vertical inflates Grms."""
    amplitude = 1.0
    t = np.arange(N) / FS
    a_world = np.zeros((N, 3))
    a_world[:, 0] = amplitude * np.sin(2 * np.pi * 2.0 * t)
    a_world[:, 2] = G0

    a_x, a_y, _, a_vertical = correct_orientation(tilted_recording(a_world))

    assert np.std(a_vertical[SETTLED]) < 0.02 * amplitude
    # Yaw is unobservable from gravity alone, so the energy splits over x and y
    assert np.hypot(np.std(a_x[SETTLED]), np.std(a_y[SETTLED])) == \
        pytest.approx(amplitude / np.sqrt(2), rel=0.02)


def test_gravity_is_removed_from_the_vertical_channel():
    """The 9.81 m/s^2 offset must not survive into a_vertical."""
    t = np.arange(N) / FS
    a_world = np.zeros((N, 3))
    a_world[:, 2] = G0 + 0.5 * np.sin(2 * np.pi * 2.0 * t)

    *_, a_vertical = correct_orientation(tilted_recording(a_world))

    assert abs(np.mean(a_vertical[SETTLED])) < 0.01


def test_estimate_gravity_recovers_the_tilt_direction():
    """g_hat must point along the body-frame gravity, at magnitude g0."""
    a_world = np.zeros((N, 3))
    a_world[:, 2] = G0
    attitude = attitude_matrix(30.0, 20.0)
    a_body = a_world @ attitude.T

    g_hat = np.stack(estimate_gravity(a_body[:, 0], a_body[:, 1], a_body[:, 2], FS),
                     axis=1)

    expected = attitude @ np.array([0.0, 0.0, G0])
    settled = g_hat[SETTLED]
    np.testing.assert_allclose(settled, np.broadcast_to(expected, settled.shape),
                               rtol=1e-6, atol=1e-6)


def test_rotation_matrix_is_orthonormal(rng):
    """R must be a pure rotation for any attitude, including the degenerate ones."""
    random_directions = rng.normal(size=(50, 3))
    random_directions *= G0 / np.linalg.norm(random_directions, axis=1, keepdims=True)
    special = np.array([
        [0.0, 0.0, G0],    # flat, face up
        [0.0, 0.0, -G0],   # flat, face down (antipodal axis)
        [G0, 0.0, 0.0],    # on its side
        [0.0, 0.0, 0.0],   # free fall / no measurement -> identity
    ])
    g = np.vstack([random_directions, special])

    rotations = compute_rotation_matrix(g[:, 0], g[:, 1], g[:, 2])

    identity = np.broadcast_to(np.eye(3), rotations.shape)
    np.testing.assert_allclose(rotations @ rotations.transpose(0, 2, 1), identity,
                               atol=1e-12)
    np.testing.assert_allclose(np.linalg.det(rotations), 1.0, atol=1e-12)


def test_rotation_matrix_maps_gravity_onto_the_vertical_axis(rng):
    """R applied to -normalize(g_hat) must give [0, 0, 1] for every sample."""
    g = rng.normal(size=(20, 3))
    g *= G0 / np.linalg.norm(g, axis=1, keepdims=True)

    rotations = compute_rotation_matrix(g[:, 0], g[:, 1], g[:, 2])
    up = -g / np.linalg.norm(g, axis=1, keepdims=True)

    rotated = np.einsum('nij,nj->ni', rotations, up)
    np.testing.assert_allclose(rotated, np.broadcast_to([0.0, 0.0, 1.0], rotated.shape),
                               atol=1e-12)


# --- ENU / heading ------------------------------------------------------------

def test_enu_east_component_scaled_by_cos_lat0():
    """0.01 deg of longitude is ~715 m at 50 deg N, not the 1112 m of a raw degree."""
    lat = np.array([50.0, 50.0])
    lon = np.array([30.0, 30.01])

    x, y = latlon_to_enu(lat, lon)

    expected_east = 6371000.0 * np.cos(np.deg2rad(50.0)) * np.deg2rad(0.01)
    assert x[1] == pytest.approx(expected_east, rel=1e-6)
    assert x[1] == pytest.approx(714.8, rel=0.01)
    assert y[1] == pytest.approx(0.0, abs=1e-9)


def test_enu_north_component_is_not_scaled():
    lat = np.array([50.0, 50.01])
    lon = np.array([30.0, 30.0])

    x, y = latlon_to_enu(lat, lon)

    assert y[1] == pytest.approx(6371000.0 * np.deg2rad(0.01), rel=1e-6)
    assert x[1] == pytest.approx(0.0, abs=1e-9)


def test_gps_heading_points_north():
    """Synthetic northbound drive at 10 m/s."""
    gps_time = np.arange(0, 10, 0.5)
    gps_lat = 50.0 + (10.0 * gps_time) / 111000.0
    gps_lon = np.full_like(gps_lat, 30.0)
    t_grid = np.arange(0, 10, 0.1)

    heading_x, heading_y, heading_valid = compute_gps_heading(
        gps_time, gps_lat, gps_lon, t_grid, heading_min_speed_mps=1.0
    )

    valid_idx = np.where(heading_valid)[0]
    assert len(valid_idx) > 0

    assert np.abs(np.mean(heading_x[valid_idx])) < 0.1
    assert np.mean(heading_y[valid_idx]) > 0.9


def test_gps_heading_points_east_with_cos_lat_scaling():
    """An eastbound drive must be recognised as east, despite the cos(lat) squeeze."""
    gps_time = np.arange(0, 10, 0.5)
    gps_lat = np.full_like(gps_time, 50.0)
    east_m = 10.0 * gps_time
    gps_lon = 30.0 + east_m / (6371000.0 * np.cos(np.deg2rad(50.0)) * np.pi / 180.0)
    t_grid = np.arange(0, 10, 0.1)

    heading_x, heading_y, heading_valid = compute_gps_heading(
        gps_time, gps_lat, gps_lon, t_grid, heading_min_speed_mps=1.0
    )

    valid_idx = np.where(heading_valid)[0]
    assert len(valid_idx) > 0
    assert np.mean(heading_x[valid_idx]) > 0.9
    assert np.abs(np.mean(heading_y[valid_idx])) < 0.1


def test_gps_heading_masked_below_min_speed():
    """GPS bearing spins freely when stationary, so it must be marked invalid."""
    gps_time = np.arange(0, 10, 0.5)
    gps_lat = np.full_like(gps_time, 50.0)
    gps_lon = np.full_like(gps_time, 30.0)
    t_grid = np.arange(0, 10, 0.1)

    _, _, heading_valid = compute_gps_heading(
        gps_time, gps_lat, gps_lon, t_grid, heading_min_speed_mps=1.0
    )

    assert not heading_valid.any()

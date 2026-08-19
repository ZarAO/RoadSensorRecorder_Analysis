"""
Gravity alignment and orientation correction
Section B3 - Gravity estimation
"""

import numpy as np
from scipy.signal import butter, filtfilt
from typing import Tuple


def estimate_gravity(
    accel_x: np.ndarray,
    accel_y: np.ndarray,
    accel_z: np.ndarray,
    fs: float,
    cutoff_hz: float = 0.3
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Estimate gravity via a low-pass filter

    Per B3.1: apply a low-pass filter (Butterworth, order 2-4)
    with cutoff ~0.25-0.5 Hz to obtain g_hat(t)

    Args:
        accel_x, accel_y, accel_z: raw accelerometer components (m/s²)
        fs: sampling rate (Hz)
        cutoff_hz: cutoff frequency for the low-pass filter (default 0.3 Hz)

    Returns:
        (g_hat_x, g_hat_y, g_hat_z) - gravity estimate (m/s²)
    """
    # 4th-order Butterworth low-pass
    nyq = 0.5 * fs
    normal_cutoff = cutoff_hz / nyq
    b, a = butter(4, normal_cutoff, btype='low', analog=False)

    # Apply the zero-phase filter
    g_hat_x = filtfilt(b, a, accel_x)
    g_hat_y = filtfilt(b, a, accel_y)
    g_hat_z = filtfilt(b, a, accel_z)
    
    return g_hat_x, g_hat_y, g_hat_z


def _rotation_axis_angle(
    g_hat_x: np.ndarray,
    g_hat_y: np.ndarray,
    g_hat_z: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Rotation axis and angle that map z_phone = -normalize(g_hat) onto world vertical

    Since z_world = [0,0,1], we have cos = u_z and u × z_world = [u_y, -u_x, 0],
    so everything is computed vectorized, without a loop over samples.

    Degenerate cases: |g_hat| ~ 0 and an already-aligned axis both give identity;
    the antiparallel case is a 180° rotation around +y.

    Args:
        g_hat_x, g_hat_y, g_hat_z: gravity estimate for each sample

    Returns:
        (k, sin_theta, cos_theta) - unit axis (N, 3) and sin/cos of the angle
    """
    g = np.stack([g_hat_x, g_hat_y, g_hat_z], axis=1)
    g_norm = np.linalg.norm(g, axis=1)

    u = np.zeros_like(g)
    u[:, 2] = 1.0  # |g_hat| ~ 0 -> identity
    measured = g_norm > 1e-6
    u[measured] = -g[measured] / g_norm[measured, None]

    cos_theta = u[:, 2]
    sin_theta = np.hypot(u[:, 0], u[:, 1])

    k = np.zeros_like(u)
    turning = sin_theta > 1e-9
    k[turning, 0] = u[turning, 1] / sin_theta[turning]
    k[turning, 1] = -u[turning, 0] / sin_theta[turning]
    # u is antiparallel to z_world: any horizontal axis works
    k[~turning & (cos_theta < 0), 1] = 1.0

    return k, sin_theta, cos_theta


def compute_rotation_matrix(
    g_hat_x: np.ndarray,
    g_hat_y: np.ndarray,
    g_hat_z: np.ndarray
) -> np.ndarray:
    """
    Compute the rotation matrices R(t) that align gravity

    Per B3.2: R(t) such that R·z_phone = [0,0,1]
    where z_phone = -normalize(g_hat)

    Args:
        g_hat_x, g_hat_y, g_hat_z: gravity estimate for each sample

    Returns:
        R_matrices: array of rotation matrices (N, 3, 3)
    """
    k, s, c = _rotation_axis_angle(g_hat_x, g_hat_y, g_hat_z)
    t = 1.0 - c
    kx, ky, kz = k[:, 0], k[:, 1], k[:, 2]

    # Rodrigues' formula in matrix form: R = cI + sK + (1-c)kk^T
    R_matrices = np.empty((len(c), 3, 3))
    R_matrices[:, 0, 0] = c + kx * kx * t
    R_matrices[:, 0, 1] = kx * ky * t - kz * s
    R_matrices[:, 0, 2] = kx * kz * t + ky * s
    R_matrices[:, 1, 0] = ky * kx * t + kz * s
    R_matrices[:, 1, 1] = c + ky * ky * t
    R_matrices[:, 1, 2] = ky * kz * t - kx * s
    R_matrices[:, 2, 0] = kz * kx * t - ky * s
    R_matrices[:, 2, 1] = kz * ky * t + kx * s
    R_matrices[:, 2, 2] = c + kz * kz * t

    return R_matrices


def transform_to_world(
    accel_x: np.ndarray,
    accel_y: np.ndarray,
    accel_z: np.ndarray,
    g_hat_x: np.ndarray,
    g_hat_y: np.ndarray,
    g_hat_z: np.ndarray,
    R_matrices: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Transform acceleration into world coordinates and remove gravity

    Per B3.3:
    a_lin_phone = a_raw_phone - g_hat
    a_lin_world = R · a_lin_phone
    a_vertical = a_lin_world.z

    Args:
        accel_x, accel_y, accel_z: raw accelerometer components (m/s²)
        g_hat_x, g_hat_y, g_hat_z: gravity estimate
        R_matrices: rotation matrices (N, 3, 3)

    Returns:
        (a_lin_world_x, a_lin_world_y, a_lin_world_z, a_vertical) - all in m/s²
    """
    # Subtract gravity and rotate into world coordinates (vectorized)
    a_lin_phone = np.stack([
        accel_x - g_hat_x,
        accel_y - g_hat_y,
        accel_z - g_hat_z
    ], axis=1)

    a_lin_world = np.einsum('nij,nj->ni', R_matrices, a_lin_phone)

    a_vertical = a_lin_world[:, 2]  # z component

    return a_lin_world[:, 0], a_lin_world[:, 1], a_lin_world[:, 2], a_vertical

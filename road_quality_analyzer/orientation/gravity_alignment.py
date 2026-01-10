"""
Gravity alignment and orientation correction
Згідно з agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md розділ B3
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
    Оцінити гравітацію через low-pass фільтр
    
    Згідно B3.1: застосувати low-pass (Butterworth 2-4 порядку) 
    з cutoff ~0.25-0.5 Hz для отримання g_hat(t)
    
    Args:
        accel_x, accel_y, accel_z: сирі компоненти акселя (м/с²)
        fs: частота семплювання (Гц)
        cutoff_hz: cutoff частота для low-pass (за замовчуванням 0.3 Hz)
        
    Returns:
        (g_hat_x, g_hat_y, g_hat_z) - оцінка гравітації (м/с²)
    """
    # Butterworth low-pass 4 порядку
    nyq = 0.5 * fs
    normal_cutoff = cutoff_hz / nyq
    b, a = butter(4, normal_cutoff, btype='low', analog=False)
    
    # Застосувати zero-phase фільтр
    g_hat_x = filtfilt(b, a, accel_x)
    g_hat_y = filtfilt(b, a, accel_y)
    g_hat_z = filtfilt(b, a, accel_z)
    
    return g_hat_x, g_hat_y, g_hat_z


def quaternion_from_two_vectors(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """
    Обчислити quaternion обертання від вектора u до вектора v
    
    Згідно B3.2: quaternion "from-to" між двома векторами
    
    Args:
        u: початковий вектор (3,)
        v: цільовий вектор (3,)
        
    Returns:
        q: quaternion [w, x, y, z] (4,)
    """
    # Нормалізувати вектори
    u_norm = u / np.linalg.norm(u)
    v_norm = v / np.linalg.norm(v)
    
    # Обчислити dot product
    c = np.dot(u_norm, v_norm)
    
    # Перевірити на майже протилежні вектори
    if c < -0.9999:
        # Обрати довільну ортогональну вісь
        if abs(u_norm[0]) < 0.9:
            axis = np.cross(np.array([1, 0, 0]), u_norm)
        else:
            axis = np.cross(np.array([0, 1, 0]), u_norm)
        axis = axis / np.linalg.norm(axis)
        # 180° rotation
        q = np.array([0.0, axis[0], axis[1], axis[2]])
        return q
    
    # Загальний випадок
    w_vec = np.cross(u_norm, v_norm)
    q = np.array([1.0 + c, w_vec[0], w_vec[1], w_vec[2]])
    q = q / np.linalg.norm(q)
    
    return q


def quaternion_to_rotation_matrix(q: np.ndarray) -> np.ndarray:
    """
    Перетворити quaternion в матрицю обертання
    
    Args:
        q: quaternion [w, x, y, z]
        
    Returns:
        R: матриця обертання 3x3
    """
    w, x, y, z = q
    
    R = np.array([
        [1 - 2*(y**2 + z**2), 2*(x*y - w*z), 2*(x*z + w*y)],
        [2*(x*y + w*z), 1 - 2*(x**2 + z**2), 2*(y*z - w*x)],
        [2*(x*z - w*y), 2*(y*z + w*x), 1 - 2*(x**2 + y**2)]
    ])
    
    return R


def compute_rotation_matrix(
    g_hat_x: np.ndarray,
    g_hat_y: np.ndarray,
    g_hat_z: np.ndarray
) -> np.ndarray:
    """
    Обчислити матриці обертання R(t), які вирівнюють gravity
    
    Згідно B3.2: R(t) таке що R·z_phone = [0,0,1]
    де z_phone = -normalize(g_hat)
    
    Args:
        g_hat_x, g_hat_y, g_hat_z: оцінка гравітації для кожного семпла
        
    Returns:
        R_matrices: масив матриць обертання (N, 3, 3)
    """
    N = len(g_hat_x)
    R_matrices = np.zeros((N, 3, 3))
    
    # Цільовий вектор (вгору)
    z_world = np.array([0.0, 0.0, 1.0])
    
    for i in range(N):
        # z_phone = -normalize(g_hat) (знак "-" щоб z вгору)
        g_vec = np.array([g_hat_x[i], g_hat_y[i], g_hat_z[i]])
        g_norm = np.linalg.norm(g_vec)
        
        if g_norm < 1e-6:
            # Якщо gravity ~0, використати identity
            R_matrices[i] = np.eye(3)
            continue
        
        z_phone = -g_vec / g_norm
        
        # Обчислити quaternion від z_phone до z_world
        q = quaternion_from_two_vectors(z_phone, z_world)
        
        # Перетворити в матрицю
        R_matrices[i] = quaternion_to_rotation_matrix(q)
    
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
    Перетворити прискорення в world координати та видалити гравітацію
    
    Згідно B3.3:
    a_lin_phone = a_raw_phone - g_hat
    a_lin_world = R · a_lin_phone
    a_vertical = a_lin_world.z
    
    Args:
        accel_x, accel_y, accel_z: сирі компоненти акселя (м/с²)
        g_hat_x, g_hat_y, g_hat_z: оцінка гравітації
        R_matrices: матриці обертання (N, 3, 3)
        
    Returns:
        (a_lin_world_x, a_lin_world_y, a_lin_world_z, a_vertical) - всі в м/с²
    """
    N = len(accel_x)
    
    a_lin_world = np.zeros((N, 3))
    
    for i in range(N):
        # Віднімаємо гравітацію
        a_lin_phone = np.array([
            accel_x[i] - g_hat_x[i],
            accel_y[i] - g_hat_y[i],
            accel_z[i] - g_hat_z[i]
        ])
        
        # Обертаємо в world координати
        a_lin_world[i] = R_matrices[i] @ a_lin_phone
    
    a_vertical = a_lin_world[:, 2]  # z компонента
    
    return a_lin_world[:, 0], a_lin_world[:, 1], a_lin_world[:, 2], a_vertical

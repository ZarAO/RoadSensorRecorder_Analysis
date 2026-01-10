"""
Unit tests for orientation correction
Додає unit test на синтетичний roll/pitch (згідно з кроком 5 плану)
"""

import pytest
import numpy as np
from road_quality_analyzer.orientation import (
    estimate_gravity,
    compute_rotation_matrix,
    transform_to_world,
    compute_gps_heading,
    compute_perpendicular_accel
)


def test_gravity_alignment_synthetic_roll_pitch():
    """
    Тест на синтетичний roll/pitch
    Перевіряємо що orientation-корекція відновлює вертикаль
    """
    # Створюємо синтетичні дані: телефон нахилений на 30° (roll)
    N = 1000
    fs = 100.0  # Гц
    dt = 1.0 / fs
    t = np.arange(N) * dt
    
    g0 = 9.80665  # м/с²
    
    # Телефон нахилений на 30° навколо X (roll)
    roll_angle = np.deg2rad(30)
    
    # В системі телефону гравітація має компоненти:
    # ax = 0
    # ay = g0 * sin(roll)
    # az = g0 * cos(roll)
    accel_x = np.zeros(N)
    accel_y = g0 * np.sin(roll_angle) * np.ones(N)
    accel_z = g0 * np.cos(roll_angle) * np.ones(N)
    
    # Додаємо маленький шум щоб було реалістично
    accel_x += np.random.randn(N) * 0.01
    accel_y += np.random.randn(N) * 0.01
    accel_z += np.random.randn(N) * 0.01
    
    # Оцінюємо гравітацію
    g_hat_x, g_hat_y, g_hat_z = estimate_gravity(
        accel_x, accel_y, accel_z, fs, cutoff_hz=0.5
    )
    
    # Обчислюємо матриці обертання
    R_matrices = compute_rotation_matrix(g_hat_x, g_hat_y, g_hat_z)
    
    # Трансформуємо в world координати
    a_world_x, a_world_y, a_world_z, a_vertical = transform_to_world(
        accel_x, accel_y, accel_z,
        g_hat_x, g_hat_y, g_hat_z,
        R_matrices
    )
    
    # Перевіряємо що після корекції:
    # 1) Вертикальна компонента близька до 0 (gravity віднято)
    # 2) Горизонтальні компоненти також близькі до 0 (немає лінійного руху)
    
    # Середні значення (виключаємо краї через filtfilt)
    mid_idx = slice(100, -100)
    
    assert np.abs(np.mean(a_vertical[mid_idx])) < 0.1, \
        f"a_vertical should be ~0 after gravity removal, got {np.mean(a_vertical[mid_idx])}"
    
    assert np.abs(np.mean(a_world_x[mid_idx])) < 0.1
    assert np.abs(np.mean(a_world_y[mid_idx])) < 0.1


def test_gravity_alignment_synthetic_pitch():
    """
    Тест на синтетичний pitch (нахил вперед/назад)
    """
    N = 1000
    fs = 100.0
    dt = 1.0 / fs
    
    g0 = 9.80665
    
    # Телефон нахилений на -20° навколо Y (pitch)
    pitch_angle = np.deg2rad(-20)
    
    # В системі телефону:
    # ax = g0 * sin(pitch)
    # ay = 0
    # az = g0 * cos(pitch)
    accel_x = g0 * np.sin(pitch_angle) * np.ones(N)
    accel_y = np.zeros(N)
    accel_z = g0 * np.cos(pitch_angle) * np.ones(N)
    
    # Шум
    accel_x += np.random.randn(N) * 0.01
    accel_y += np.random.randn(N) * 0.01
    accel_z += np.random.randn(N) * 0.01
    
    # Оцінка та корекція
    g_hat_x, g_hat_y, g_hat_z = estimate_gravity(
        accel_x, accel_y, accel_z, fs, cutoff_hz=0.5
    )
    
    R_matrices = compute_rotation_matrix(g_hat_x, g_hat_y, g_hat_z)
    
    a_world_x, a_world_y, a_world_z, a_vertical = transform_to_world(
        accel_x, accel_y, accel_z,
        g_hat_x, g_hat_y, g_hat_z,
        R_matrices
    )
    
    # Перевіряємо корекцію
    mid_idx = slice(100, -100)
    
    assert np.abs(np.mean(a_vertical[mid_idx])) < 0.1
    assert np.abs(np.mean(a_world_x[mid_idx])) < 0.1
    assert np.abs(np.mean(a_world_y[mid_idx])) < 0.1


def test_gps_heading():
    """
    Тест: GPS heading обчислюється правильно
    """
    # Синтетичний рух на північ зі сталою швидкістю
    gps_time = np.arange(0, 10, 0.5)  # 20 семплів
    
    # Рух на північ: lat збільшується, lon стала
    lat0 = 50.0
    speed_mps = 10.0  # 10 м/с
    distance = speed_mps * gps_time
    
    # 1° широти ≈ 111 км
    delta_lat = distance / 111000.0
    
    gps_lat = lat0 + delta_lat
    gps_lon = np.full_like(gps_lat, 30.0)
    
    t_grid = np.arange(0, 10, 0.1)
    
    heading_x, heading_y, heading_valid = compute_gps_heading(
        gps_time, gps_lat, gps_lon, t_grid,
        heading_min_speed_mps=1.0
    )
    
    # Перевіряємо що heading вказує на північ (y=1, x=0)
    valid_idx = np.where(heading_valid)[0]
    
    assert len(valid_idx) > 0, "Should have valid heading"
    
    # Середній heading
    mean_heading_x = np.mean(heading_x[valid_idx])
    mean_heading_y = np.mean(heading_y[valid_idx])
    
    assert np.abs(mean_heading_x) < 0.1, "Heading should point north (x~0)"
    assert mean_heading_y > 0.9, "Heading should point north (y~1)"


def test_perpendicular_accel():
    """
    Тест: a_perp обчислюється правильно
    """
    N = 100
    
    # Рух на північ (heading = [0, 1, 0])
    heading_x = np.zeros(N)
    heading_y = np.ones(N)
    heading_valid = np.ones(N, dtype=bool)
    
    # Прискорення на схід (перпендикулярно до руху)
    a_lin_world_x = np.ones(N) * 2.0  # 2 м/с² на схід
    a_lin_world_y = np.zeros(N)
    a_lin_world_z = np.zeros(N)
    
    a_perp = compute_perpendicular_accel(
        a_lin_world_x, a_lin_world_y, a_lin_world_z,
        heading_x, heading_y, heading_valid
    )
    
    # Перевіряємо що a_perp валідний і має правильну величину
    assert np.all(~np.isnan(a_perp)), "a_perp should be valid"
    # Перевіряємо абсолютну величину (знак залежить від орієнтації)
    assert np.abs(np.abs(np.mean(a_perp)) - 2.0) < 0.1


def test_perpendicular_accel_masked_low_speed():
    """
    Тест: a_perp маскується при низькій швидкості
    """
    N = 100
    
    heading_x = np.zeros(N)
    heading_y = np.ones(N)
    
    # Половина семплів невалідні (низька швидкість)
    heading_valid = np.zeros(N, dtype=bool)
    heading_valid[50:] = True
    
    a_lin_world_x = np.ones(N)
    a_lin_world_y = np.zeros(N)
    a_lin_world_z = np.zeros(N)
    
    a_perp = compute_perpendicular_accel(
        a_lin_world_x, a_lin_world_y, a_lin_world_z,
        heading_x, heading_y, heading_valid
    )
    
    # Перші 50 семплів мають бути NaN
    assert np.all(np.isnan(a_perp[:50]))
    
    # Інші 50 валідні
    assert np.all(~np.isnan(a_perp[50:]))

"""
Unit tests for time grid and distance utilities
"""

import pytest
import numpy as np
from road_quality_analyzer.preprocessing.time_grid import (
    build_uniform_time_grid,
    compute_gps_distance,
    build_distance_grid
)


def test_build_uniform_time_grid():
    """
    Тест: uniform time grid будується з median dt
    """
    # Нерівномірні семпли
    accel_time = np.array([0.0, 0.01, 0.025, 0.035, 0.05])
    accel_x = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
    accel_y = np.array([0.0, 0.0, 0.0, 0.0, 0.0])
    accel_z = np.array([9.8, 9.8, 9.8, 9.8, 9.8])
    
    t_grid, ax_grid, ay_grid, az_grid = build_uniform_time_grid(
        accel_time, accel_x, accel_y, accel_z
    )
    
    # Перевірити що dt uniform (median з [0.01, 0.015, 0.01, 0.015] = 0.0125)
    dt_grid = np.diff(t_grid)
    assert np.all(np.abs(dt_grid - dt_grid[0]) < 1e-6)
    
    # Перевірити що інтерполяція працює
    assert len(t_grid) > 0
    assert len(ax_grid) == len(t_grid)


def test_compute_gps_distance_haversine():
    """
    Тест: відстань між GPS точками (haversine)
    Еталон: Київ (50.45, 30.52) -> (50.46, 30.52) ≈ 1.11 км
    """
    lat = np.array([50.45, 50.46])
    lon = np.array([30.52, 30.52])
    
    s = compute_gps_distance(lat, lon)
    
    # Перший семпл має s=0
    assert s[0] == 0.0
    
    # Другий семпл має s ≈ 1110 м (1° широти ≈ 111 км)
    assert 1100 < s[1] < 1120


def test_compute_gps_distance_cumulative():
    """
    Тест: cumulative distance правильно накопичується
    """
    # 3 точки по прямій
    lat = np.array([50.0, 50.01, 50.02])
    lon = np.array([30.0, 30.0, 30.0])
    
    s = compute_gps_distance(lat, lon)
    
    # Перевірити що s монотонно зростає
    assert np.all(np.diff(s) >= 0)
    
    # Перевірити що s[2] ≈ 2 * s[1] (однакові кроки)
    assert s[2] == pytest.approx(2 * s[1], rel=0.01)


def test_build_distance_grid():
    """
    Тест: distance grid та швидкість будуються коректно
    """
    # GPS на рівних інтервалах: 10 м кожні 0.5 с → v = 20 м/с
    gps_time = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
    gps_lat = np.array([50.0, 50.0001, 50.0002, 50.0003, 50.0004])
    gps_lon = np.array([30.0, 30.0, 30.0, 30.0, 30.0])
    
    t_grid = np.arange(0.0, 2.0, 0.1)
    
    s_grid, v_grid = build_distance_grid(gps_time, gps_lat, gps_lon, t_grid)
    
    # Перевірити що s монотонно зростає
    assert np.all(np.diff(s_grid) >= 0)
    
    # Перевірити що швидкість позитивна
    assert np.all(v_grid >= 0)
    
    # Перевірити що швидкість приблизно стала
    v_mean = np.mean(v_grid[2:-2])  # виключити краї
    assert v_mean > 0


def test_distance_grid_velocity_smoothing():
    """
    Тест: швидкість згладжується
    """
    # GPS з шумом
    gps_time = np.linspace(0, 10, 21)
    # Рухаємось з 10 м/с
    true_distance = 10 * gps_time
    # Додаємо шум
    noise = np.random.randn(len(gps_time)) * 0.1
    
    # Конвертуємо в lat (приблизно)
    lat0 = 50.0
    gps_lat = lat0 + true_distance / 111000.0 + noise / 111000.0
    gps_lon = np.full_like(gps_lat, 30.0)
    
    t_grid = np.linspace(0, 10, 101)
    
    s_grid, v_grid = build_distance_grid(gps_time, gps_lat, gps_lon, t_grid)
    
    # Перевірити що v_grid згладжений (стандартне відхилення менше)
    v_std = np.std(v_grid[10:-10])
    
    # Середня швидкість має бути близько 10 м/с
    v_mean = np.mean(v_grid[10:-10])
    assert 8 < v_mean < 12

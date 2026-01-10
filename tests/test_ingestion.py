"""
Unit tests for ingestion module
"""

import pytest
import numpy as np
import pandas as pd
import tempfile
import os
from road_quality_analyzer.io.ingestion import load_sensor_csv, SensorData


def test_load_sensor_csv_separates_streams():
    """
    Тест: CSV правильно розділяється на окремі потоки
    """
    # Створити тестовий CSV
    data = {
        'time': [
            '2025-01-10 10:00:00.000',
            '2025-01-10 10:00:00.010',
            '2025-01-10 10:00:00.020',
            '2025-01-10 10:00:00.030',
            '2025-01-10 10:00:00.040',
            '2025-01-10 10:00:01.000',
        ],
        'sensor_type': ['accelerometer', 'accelerometer', 'gyroscope', 
                       'location', 'accelerometer', 'location'],
        'x': [0.1, 0.2, 0.01, np.nan, 0.3, np.nan],
        'y': [0.2, 0.3, 0.02, np.nan, 0.4, np.nan],
        'z': [9.8, 9.7, 0.03, np.nan, 9.9, np.nan],
        'latitude': [np.nan, np.nan, np.nan, 50.45, np.nan, 50.46],
        'longitude': [np.nan, np.nan, np.nan, 30.52, np.nan, 30.53],
    }
    df = pd.DataFrame(data)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        df.to_csv(f.name, index=False)
        temp_path = f.name
    
    try:
        sensor_data = load_sensor_csv(temp_path)
        
        # Перевірити що акселерометр має 3 семпли (0, 1, 4)
        assert len(sensor_data.accel_time) == 3
        assert len(sensor_data.accel_x) == 3
        assert len(sensor_data.accel_y) == 3
        assert len(sensor_data.accel_z) == 3
        
        # Перевірити що GPS має 2 семпли
        assert len(sensor_data.gps_time) == 2
        assert len(sensor_data.gps_lat) == 2
        assert len(sensor_data.gps_lon) == 2
        
        # Перевірити що час відсортовано
        assert np.all(np.diff(sensor_data.accel_time) >= 0)
        assert np.all(np.diff(sensor_data.gps_time) >= 0)
        
    finally:
        os.unlink(temp_path)


def test_load_sensor_csv_no_ffill():
    """
    Тест: НЕ робиться ffill/bfill акселя через GPS рядки
    """
    data = {
        'time': [
            '2025-01-10 10:00:00.000',
            '2025-01-10 10:00:00.010',
            '2025-01-10 10:00:00.020',
        ],
        'sensor_type': ['accelerometer', 'location', 'accelerometer'],
        'x': [0.1, np.nan, 0.3],
        'y': [0.2, np.nan, 0.4],
        'z': [9.8, np.nan, 9.9],
        'latitude': [np.nan, 50.45, np.nan],
        'longitude': [np.nan, 30.52, np.nan],
    }
    df = pd.DataFrame(data)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        df.to_csv(f.name, index=False)
        temp_path = f.name
    
    try:
        sensor_data = load_sensor_csv(temp_path)
        
        # Має бути тільки 2 семпли акселя (0, 2), НЕ 3
        assert len(sensor_data.accel_time) == 2
        
        # Перевірити значення
        np.testing.assert_array_almost_equal(sensor_data.accel_x, [0.1, 0.3])
        np.testing.assert_array_almost_equal(sensor_data.accel_z, [9.8, 9.9])
        
    finally:
        os.unlink(temp_path)


def test_time_conversion_to_seconds():
    """
    Тест: час правильно конвертується в секунди від початку
    """
    data = {
        'time': [
            '2025-01-10 10:00:00.000',
            '2025-01-10 10:00:00.500',
            '2025-01-10 10:00:01.000',
        ],
        'sensor_type': ['accelerometer', 'accelerometer', 'accelerometer'],
        'x': [0.1, 0.2, 0.3],
        'y': [0.1, 0.2, 0.3],
        'z': [9.8, 9.8, 9.8],
        'latitude': [np.nan, np.nan, np.nan],
        'longitude': [np.nan, np.nan, np.nan],
    }
    df = pd.DataFrame(data)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        df.to_csv(f.name, index=False)
        temp_path = f.name
    
    try:
        sensor_data = load_sensor_csv(temp_path)
        
        # Перевірити що перший семпл має час ~0
        assert sensor_data.accel_time[0] == pytest.approx(0.0, abs=0.001)
        
        # Перевірити інтервали
        assert sensor_data.accel_time[1] == pytest.approx(0.5, abs=0.001)
        assert sensor_data.accel_time[2] == pytest.approx(1.0, abs=0.001)
        
    finally:
        os.unlink(temp_path)

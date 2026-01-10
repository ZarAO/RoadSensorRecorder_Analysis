"""
Data ingestion module
Строго розділяє потоки accelerometer/gyroscope/location
Забороняє ffill/bfill акселя через GPS рядки
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np


@dataclass
class SensorData:
    """
    Контейнер для розділених сенсорних потоків
    """
    # Accelerometer stream (м/с²)
    accel_time: np.ndarray  # секунди
    accel_x: np.ndarray
    accel_y: np.ndarray
    accel_z: np.ndarray
    
    # Gyroscope stream (рад/с)
    gyro_time: Optional[np.ndarray] = None
    gyro_x: Optional[np.ndarray] = None
    gyro_y: Optional[np.ndarray] = None
    gyro_z: Optional[np.ndarray] = None
    
    # Location stream
    gps_time: Optional[np.ndarray] = None
    gps_lat: Optional[np.ndarray] = None
    gps_lon: Optional[np.ndarray] = None
    gps_altitude: Optional[np.ndarray] = None
    gps_accuracy: Optional[np.ndarray] = None


def load_sensor_csv(filepath: str) -> SensorData:
    """
    Завантажує CSV з сенсорними даними та розділяє на окремі потоки.
    
    Правила (згідно з кроком 3):
    1) Розділити на accelerometer/gyroscope/location потоки
    2) НЕ робити ffill/bfill акселя через GPS рядки
    3) Перевести час у секунди від початку
    4) Відсортувати кожен потік
    
    Args:
        filepath: шлях до CSV файлу
        
    Returns:
        SensorData з розділеними потоками
    """
    df = pd.read_csv(filepath)
    
    # Нормалізувати назви колонок
    df.columns = df.columns.str.lower()
    
    # Підтримка різних назв для type колонки
    if 'sensor_type' in df.columns:
        df['type'] = df['sensor_type']
    
    # Перевести час у секунди від початку
    # Час може бути в різних форматах: timestamp (мс) або ISO string
    if 'time' in df.columns:
        # Якщо це число (timestamp в мс)
        if pd.api.types.is_numeric_dtype(df['time']):
            t0 = df['time'].min()
            df['time_sec'] = (df['time'] - t0) / 1000.0  # конвертувати мс -> с
        else:
            # Якщо це строка (ISO datetime)
            df['timestamp'] = pd.to_datetime(df['time'])
            t0 = df['timestamp'].min()
            df['time_sec'] = (df['timestamp'] - t0).dt.total_seconds()
    
    # Розділити на потоки за type
    # Accelerometer stream
    accel_df = df[df['type'].str.lower() == 'accelerometer'].copy()
    accel_df = accel_df.sort_values('time_sec').reset_index(drop=True)
    
    # Виключити NaN з акселя (не робимо ffill!)
    accel_mask = (
        accel_df['x'].notna() & 
        accel_df['y'].notna() & 
        accel_df['z'].notna()
    )
    accel_df = accel_df[accel_mask].reset_index(drop=True)
    
    # Gyroscope stream (опціонально)
    gyro_df = df[df['type'].str.lower() == 'gyroscope'].copy()
    gyro_df = gyro_df.sort_values('time_sec').reset_index(drop=True)
    
    gyro_mask = (
        gyro_df['x'].notna() & 
        gyro_df['y'].notna() & 
        gyro_df['z'].notna()
    )
    gyro_df = gyro_df[gyro_mask].reset_index(drop=True)
    
    # Location stream
    loc_df = df[df['type'].str.lower() == 'location'].copy()
    loc_df = loc_df.sort_values('time_sec').reset_index(drop=True)
    
    loc_mask = (
        loc_df['latitude'].notna() & 
        loc_df['longitude'].notna()
    )
    loc_df = loc_df[loc_mask].reset_index(drop=True)
    
    # Створити SensorData
    sensor_data = SensorData(
        accel_time=accel_df['time_sec'].values,
        accel_x=accel_df['x'].values,
        accel_y=accel_df['y'].values,
        accel_z=accel_df['z'].values,
    )
    
    if len(gyro_df) > 0:
        sensor_data.gyro_time = gyro_df['time_sec'].values
        sensor_data.gyro_x = gyro_df['x'].values
        sensor_data.gyro_y = gyro_df['y'].values
        sensor_data.gyro_z = gyro_df['z'].values
    
    if len(loc_df) > 0:
        sensor_data.gps_time = loc_df['time_sec'].values
        sensor_data.gps_lat = loc_df['latitude'].values
        sensor_data.gps_lon = loc_df['longitude'].values
        sensor_data.gps_altitude = loc_df['altitude'].values if 'altitude' in loc_df else None
        sensor_data.gps_accuracy = loc_df['accuracy'].values if 'accuracy' in loc_df else None
    
    return sensor_data

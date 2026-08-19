"""
Data ingestion module
Strictly separates accelerometer/gyroscope/location streams
Prohibits ffill/bfill of accelerometer values across GPS rows
"""

from dataclasses import dataclass
from typing import List, Optional
import pandas as pd
import numpy as np


# CSV contract v2: header is fixed, an optional '#' metadata preamble may precede it
EXPECTED_COLUMNS = ['Time', 'Type', 'X', 'Y', 'Z', 'Latitude', 'Longitude']


@dataclass
class SensorData:
    """
    Container for the separated sensor streams
    """
    # Accelerometer stream (m/s²)
    accel_time: np.ndarray  # seconds
    accel_x: np.ndarray
    accel_y: np.ndarray
    accel_z: np.ndarray

    # Gyroscope stream (rad/s)
    gyro_time: Optional[np.ndarray] = None
    gyro_x: Optional[np.ndarray] = None
    gyro_y: Optional[np.ndarray] = None
    gyro_z: Optional[np.ndarray] = None

    # Location stream
    gps_time: Optional[np.ndarray] = None
    gps_lat: Optional[np.ndarray] = None
    gps_lon: Optional[np.ndarray] = None

    # Detected unit of the Time column ('ms' / 's' / 'iso')
    time_unit: str = 'ms'


def _detect_time_unit(time_values: np.ndarray) -> str:
    """
    Determine the unit of the numeric Time column from its magnitude.

    Epoch in milliseconds is ~1.7e12, epoch in seconds is ~1.7e9. Relative time
    (from the start of the recording) is small, so for it we rely on the sampling
    step: in ms it is >= 1, in seconds it is << 1.
    """
    t_max = float(np.nanmax(np.abs(time_values)))
    if t_max >= 1e11:
        return 'ms'
    if t_max >= 1e8:
        return 's'

    dt = np.diff(np.sort(time_values))
    dt = dt[dt > 0]
    if len(dt) > 0 and float(np.median(dt)) >= 0.5:
        return 'ms'
    return 's'


def _prepare_stream(df: pd.DataFrame, value_columns: List[str]) -> pd.DataFrame:
    """
    Prepare a single stream: stable sort by time, drop rows with NaN,
    and collapse duplicate timestamps by averaging.

    Collapsing duplicates is mandatory: interp1d requires a strictly increasing x,
    and a recorder with 1 ms clock resolution produces ties.
    """
    stream = df[['time_sec'] + value_columns].dropna()
    stream = stream.sort_values('time_sec', kind='mergesort')
    if len(stream) == 0:
        return stream
    return stream.groupby('time_sec', as_index=False).mean()


def load_sensor_csv(filepath: str) -> SensorData:
    """
    Loads a CSV with sensor data and splits it into separate streams.

    Rules (per step 3):
    1) Split into accelerometer/gyroscope/location streams
    2) Do NOT ffill/bfill accelerometer values across GPS rows
    3) Convert time to seconds from the start
    4) Sort each stream (stably) and collapse duplicate timestamps

    Args:
        filepath: path to the CSV file

    Returns:
        SensorData with the separated streams

    Raises:
        ValueError: if the header does not match the contract or there are no
                    accelerometer rows
    """
    # comment='#' - optional metadata preamble of the v2 contract;
    # index_col=False - a row with an extra field must fail, not shift columns
    df = pd.read_csv(filepath, comment='#', index_col=False)

    if list(df.columns) != EXPECTED_COLUMNS:
        raise ValueError(
            f"Unexpected CSV header in {filepath}: expected {EXPECTED_COLUMNS}, "
            f"found {list(df.columns)}"
        )

    df.columns = df.columns.str.lower()

    # Convert time to seconds from the start
    # Time can be in different formats: timestamp (ms/s) or ISO string
    if pd.api.types.is_numeric_dtype(df['time']):
        time_unit = _detect_time_unit(df['time'].values)
        divisor = 1000.0 if time_unit == 'ms' else 1.0
        t0 = df['time'].min()
        df['time_sec'] = (df['time'] - t0) / divisor
    else:
        # ISO datetime
        time_unit = 'iso'
        timestamp = pd.to_datetime(df['time'])
        df['time_sec'] = (timestamp - timestamp.min()).dt.total_seconds()

    # Split into streams by type
    type_lower = df['type'].astype(str).str.lower()
    accel_df = _prepare_stream(df[type_lower == 'accelerometer'], ['x', 'y', 'z'])
    gyro_df = _prepare_stream(df[type_lower == 'gyroscope'], ['x', 'y', 'z'])
    loc_df = _prepare_stream(df[type_lower == 'location'], ['latitude', 'longitude'])

    if len(accel_df) == 0:
        found = sorted(df['type'].dropna().astype(str).unique().tolist())
        raise ValueError(
            f"No usable Accelerometer rows in {filepath}: "
            f"Type values found = {found or 'none (empty file)'}"
        )

    sensor_data = SensorData(
        accel_time=accel_df['time_sec'].values,
        accel_x=accel_df['x'].values,
        accel_y=accel_df['y'].values,
        accel_z=accel_df['z'].values,
        time_unit=time_unit,
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

    return sensor_data

"""
Unit tests for ingestion module
"""

import pytest
import numpy as np
import pandas as pd
import tempfile
import os
from road_quality_analyzer.io.ingestion import load_sensor_csv, SensorData


def write_csv(rows: dict, preamble: str = "") -> str:
    """Write a CSV with the contract header and return the path"""
    df = pd.DataFrame(rows)
    fd, temp_path = tempfile.mkstemp(suffix='.csv')
    os.close(fd)
    with open(temp_path, 'w', encoding='utf-8', newline='') as f:
        if preamble:
            f.write(preamble)
        df.to_csv(f, index=False)
    return temp_path


def test_load_sensor_csv_separates_streams():
    """
    Test: CSV is correctly split into separate streams
    """
    temp_path = write_csv({
        'Time': [
            '2025-01-10 10:00:00.000',
            '2025-01-10 10:00:00.010',
            '2025-01-10 10:00:00.020',
            '2025-01-10 10:00:00.030',
            '2025-01-10 10:00:00.040',
            '2025-01-10 10:00:01.000',
        ],
        'Type': ['Accelerometer', 'Accelerometer', 'Gyroscope',
                 'Location', 'Accelerometer', 'Location'],
        'X': [0.1, 0.2, 0.01, np.nan, 0.3, np.nan],
        'Y': [0.2, 0.3, 0.02, np.nan, 0.4, np.nan],
        'Z': [9.8, 9.7, 0.03, np.nan, 9.9, np.nan],
        'Latitude': [np.nan, np.nan, np.nan, 50.45, np.nan, 50.46],
        'Longitude': [np.nan, np.nan, np.nan, 30.52, np.nan, 30.53],
    })

    try:
        sensor_data = load_sensor_csv(temp_path)

        # Verify the accelerometer has 3 samples (0, 1, 4)
        assert len(sensor_data.accel_time) == 3
        assert len(sensor_data.accel_x) == 3
        assert len(sensor_data.accel_y) == 3
        assert len(sensor_data.accel_z) == 3

        # Verify GPS has 2 samples
        assert len(sensor_data.gps_time) == 2
        assert len(sensor_data.gps_lat) == 2
        assert len(sensor_data.gps_lon) == 2

        # Verify time is sorted
        assert np.all(np.diff(sensor_data.accel_time) >= 0)
        assert np.all(np.diff(sensor_data.gps_time) >= 0)

    finally:
        os.unlink(temp_path)


def test_load_sensor_csv_no_ffill():
    """
    Test: accelerometer values are NOT ffill/bfill'd across GPS rows
    """
    temp_path = write_csv({
        'Time': [
            '2025-01-10 10:00:00.000',
            '2025-01-10 10:00:00.010',
            '2025-01-10 10:00:00.020',
        ],
        'Type': ['Accelerometer', 'Location', 'Accelerometer'],
        'X': [0.1, np.nan, 0.3],
        'Y': [0.2, np.nan, 0.4],
        'Z': [9.8, np.nan, 9.9],
        'Latitude': [np.nan, 50.45, np.nan],
        'Longitude': [np.nan, 30.52, np.nan],
    })

    try:
        sensor_data = load_sensor_csv(temp_path)

        # Should be only 2 accelerometer samples (0, 2), NOT 3
        assert len(sensor_data.accel_time) == 2

        # Verify values
        np.testing.assert_array_almost_equal(sensor_data.accel_x, [0.1, 0.3])
        np.testing.assert_array_almost_equal(sensor_data.accel_z, [9.8, 9.9])

    finally:
        os.unlink(temp_path)


def test_time_conversion_to_seconds():
    """
    Test: time is correctly converted to seconds from the start
    """
    temp_path = write_csv({
        'Time': [
            '2025-01-10 10:00:00.000',
            '2025-01-10 10:00:00.500',
            '2025-01-10 10:00:01.000',
        ],
        'Type': ['Accelerometer', 'Accelerometer', 'Accelerometer'],
        'X': [0.1, 0.2, 0.3],
        'Y': [0.1, 0.2, 0.3],
        'Z': [9.8, 9.8, 9.8],
        'Latitude': [np.nan, np.nan, np.nan],
        'Longitude': [np.nan, np.nan, np.nan],
    })

    try:
        sensor_data = load_sensor_csv(temp_path)

        # Verify the first sample has time ~0
        assert sensor_data.accel_time[0] == pytest.approx(0.0, abs=0.001)

        # Verify the intervals
        assert sensor_data.accel_time[1] == pytest.approx(0.5, abs=0.001)
        assert sensor_data.accel_time[2] == pytest.approx(1.0, abs=0.001)
        assert sensor_data.time_unit == 'iso'

    finally:
        os.unlink(temp_path)


def test_epoch_ms_preamble_and_duplicates():
    """
    Test: '#' preamble is skipped, epoch-ms is detected,
    duplicate timestamps are collapsed by averaging
    """
    preamble = (
        "# schema=2\n"
        "# units: accel=m/s^2 (includes gravity), time=ms epoch anchored monotonic\n"
        "# nominal_rate_hz=100\n"
    )
    temp_path = write_csv({
        'Time': [1753796576180, 1753796576180, 1753796576190],
        'Type': ['Accelerometer', 'Accelerometer', 'Accelerometer'],
        'X': [0.1, 0.3, 0.5],
        'Y': [0.0, 0.0, 0.0],
        'Z': [9.8, 9.8, 9.8],
        'Latitude': [np.nan, np.nan, np.nan],
        'Longitude': [np.nan, np.nan, np.nan],
    }, preamble=preamble)

    try:
        sensor_data = load_sensor_csv(temp_path)

        assert sensor_data.time_unit == 'ms'
        # Duplicate collapsed: 2 unique timestamps, x averaged
        assert len(sensor_data.accel_time) == 2
        assert np.all(np.diff(sensor_data.accel_time) > 0)
        np.testing.assert_array_almost_equal(sensor_data.accel_x, [0.2, 0.5])

    finally:
        os.unlink(temp_path)


def test_invalid_header_raises():
    """
    Test: a header outside the contract fails with a message about the found columns
    """
    temp_path = write_csv({
        'time': [1753796576180],
        'sensor_type': ['Accelerometer'],
        'x': [0.1],
        'y': [0.0],
        'z': [9.8],
        'latitude': [np.nan],
        'longitude': [np.nan],
    })

    try:
        with pytest.raises(ValueError, match="Unexpected CSV header"):
            load_sensor_csv(temp_path)
    finally:
        os.unlink(temp_path)


def test_empty_accelerometer_stream_raises():
    """
    Test: a CSV with no accelerometer rows fails with a list of found Type values
    """
    temp_path = write_csv({
        'Time': [1753796576180],
        'Type': ['Location'],
        'X': [np.nan],
        'Y': [np.nan],
        'Z': [np.nan],
        'Latitude': [50.45],
        'Longitude': [30.52],
    })

    try:
        with pytest.raises(ValueError, match="No usable Accelerometer rows"):
            load_sensor_csv(temp_path)
    finally:
        os.unlink(temp_path)


def test_header_only_csv_raises_clear_error():
    """
    Test: a header-only file fails immediately, not somewhere in time_grid
    """
    fd, temp_path = tempfile.mkstemp(suffix='.csv')
    os.close(fd)
    with open(temp_path, 'w', encoding='utf-8', newline='') as f:
        f.write("Time,Type,X,Y,Z,Latitude,Longitude\n")

    try:
        with pytest.raises(ValueError, match="No usable Accelerometer rows"):
            load_sensor_csv(temp_path)
    finally:
        os.unlink(temp_path)


def test_row_with_extra_field_raises_parser_error():
    """
    Test: an extra field in a row fails pointing to the row, not shifting columns
    """
    fd, temp_path = tempfile.mkstemp(suffix='.csv')
    os.close(fd)
    with open(temp_path, 'w', encoding='utf-8', newline='') as f:
        f.write("Time,Type,X,Y,Z,Latitude,Longitude\n")
        f.write("1753796576180,Accelerometer,0.1,0.2,9.8,,\n")
        f.write("1753796576190,Accelerometer,0.1,0.2,9.8,,,42\n")

    try:
        with pytest.raises(pd.errors.ParserError):
            load_sensor_csv(temp_path)
    finally:
        os.unlink(temp_path)


def test_no_location_rows_leaves_gps_none():
    """
    Test: with no Location rows, the GPS stream stays None (the pipeline must fail loudly)
    """
    temp_path = write_csv({
        'Time': [1753796576180, 1753796576190, 1753796576200],
        'Type': ['Accelerometer', 'Accelerometer', 'Gyroscope'],
        'X': [0.1, 0.2, 0.01],
        'Y': [0.0, 0.0, 0.02],
        'Z': [9.8, 9.8, 0.03],
        'Latitude': [np.nan, np.nan, np.nan],
        'Longitude': [np.nan, np.nan, np.nan],
    })

    try:
        sensor_data = load_sensor_csv(temp_path)

        assert sensor_data.gps_time is None
        assert sensor_data.gps_lat is None
        assert sensor_data.gps_lon is None
        # The other streams should still be populated
        assert len(sensor_data.accel_time) == 2
        assert len(sensor_data.gyro_time) == 1
    finally:
        os.unlink(temp_path)


def test_numeric_millisecond_timestamps_converted_to_seconds():
    """
    Test: relative time in milliseconds is divided by 1000
    """
    temp_path = write_csv({
        'Time': [1000, 1500, 2000],
        'Type': ['Accelerometer', 'Accelerometer', 'Accelerometer'],
        'X': [0.1, 0.2, 0.3],
        'Y': [0.0, 0.0, 0.0],
        'Z': [9.8, 9.8, 9.8],
        'Latitude': [np.nan, np.nan, np.nan],
        'Longitude': [np.nan, np.nan, np.nan],
    })

    try:
        sensor_data = load_sensor_csv(temp_path)

        assert sensor_data.time_unit == 'ms'
        np.testing.assert_allclose(sensor_data.accel_time, [0.0, 0.5, 1.0])
    finally:
        os.unlink(temp_path)


def test_relative_second_timestamps_detected_by_sampling_step():
    """
    Test: relative time in seconds is not divided by 1000 (step < 0.5)
    """
    temp_path = write_csv({
        'Time': [0.0, 0.01, 0.02],
        'Type': ['Accelerometer', 'Accelerometer', 'Accelerometer'],
        'X': [0.1, 0.2, 0.3],
        'Y': [0.0, 0.0, 0.0],
        'Z': [9.8, 9.8, 9.8],
        'Latitude': [np.nan, np.nan, np.nan],
        'Longitude': [np.nan, np.nan, np.nan],
    })

    try:
        sensor_data = load_sensor_csv(temp_path)

        assert sensor_data.time_unit == 's'
        np.testing.assert_allclose(sensor_data.accel_time, [0.0, 0.01, 0.02])
    finally:
        os.unlink(temp_path)


def test_epoch_seconds_detected_by_magnitude():
    """
    Test: epoch in seconds (~1.7e9) is recognized by magnitude, not by step
    """
    temp_path = write_csv({
        'Time': [1753796576.0, 1753796576.5, 1753796577.0],
        'Type': ['Accelerometer', 'Accelerometer', 'Accelerometer'],
        'X': [0.1, 0.2, 0.3],
        'Y': [0.0, 0.0, 0.0],
        'Z': [9.8, 9.8, 9.8],
        'Latitude': [np.nan, np.nan, np.nan],
        'Longitude': [np.nan, np.nan, np.nan],
    })

    try:
        sensor_data = load_sensor_csv(temp_path)

        assert sensor_data.time_unit == 's'
        np.testing.assert_allclose(sensor_data.accel_time, [0.0, 0.5, 1.0])
    finally:
        os.unlink(temp_path)


def test_unsorted_rows_are_sorted_by_time():
    """
    Test: out-of-order rows are sorted, values stay attached to their own time
    """
    temp_path = write_csv({
        'Time': [1753796576200, 1753796576180, 1753796576190],
        'Type': ['Accelerometer', 'Accelerometer', 'Accelerometer'],
        'X': [0.3, 0.1, 0.2],
        'Y': [0.0, 0.0, 0.0],
        'Z': [9.8, 9.8, 9.8],
        'Latitude': [np.nan, np.nan, np.nan],
        'Longitude': [np.nan, np.nan, np.nan],
    })

    try:
        sensor_data = load_sensor_csv(temp_path)

        np.testing.assert_allclose(sensor_data.accel_time, [0.0, 0.01, 0.02])
        np.testing.assert_allclose(sensor_data.accel_x, [0.1, 0.2, 0.3])
    finally:
        os.unlink(temp_path)

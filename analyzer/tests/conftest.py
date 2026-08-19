"""
Shared pytest fixtures and synthetic-data builders.

Reproducibility (research-python.md): every test that needs noise draws it from the
`rng` fixture, a `default_rng` seeded with SEED, so two runs of the suite produce
identical numbers. Nothing in the suite or the package touches the legacy global
`np.random` state, so there is no global seeding here.
"""

import numpy as np
import pandas as pd
import pytest

SEED = 20260101

G0 = 9.80665  # m/s^2

# CSV contract v2
CSV_HEADER = ['Time', 'Type', 'X', 'Y', 'Z', 'Latitude', 'Longitude']
CSV_PREAMBLE = (
    "# schema=2\n"
    "# units: accel=m/s^2 (includes gravity), gyro=rad/s, latlon=deg WGS84, "
    "time=ms epoch anchored monotonic\n"
    "# anchor: elapsedRealtimeNanos=1000000000, currentTimeMillis=1753796576000\n"
    "# device: SYNTHETIC TEST, android=14\n"
    "# nominal_rate_hz=100\n"
)
ANCHOR_MS = 1753796576000

# Same Earth radius as compute_gps_distance, so a synthetic north-bound drive has
# exactly the distance the haversine implementation reconstructs from it
METERS_PER_DEG_LAT = 6371000.0 * np.pi / 180.0


@pytest.fixture
def rng():
    """The suite's only randomness source: explicit, independent of global state."""
    return np.random.default_rng(SEED)


def write_drive_csv(
    path,
    *,
    duration_s: float = 20.0,
    fs: float = 100.0,
    speed_mps: float = 15.0,
    a_vert=None,
    gps: bool = True,
    gps_rate_hz: float = 1.0,
    lat0: float = 50.4,
    lon0: float = 30.5,
    preamble: bool = True,
) -> str:
    """
    Write a small contract-v2 CSV for a phone lying flat in a car driving due north.

    The phone is flat, so the body-frame accelerometer reads (0, 0, g0 + a_vert):
    the world-frame vertical excitation is recoverable in closed form and pipeline
    metrics can be pinned to hand-computed values.

    Args:
        path: destination file
        duration_s: recording length (seconds)
        fs: accelerometer rate (Hz)
        speed_mps: constant ground speed
        a_vert: callable(t) -> vertical excitation in m/s^2 (default: none)
        gps: emit Location rows at all (False reproduces a permission-denied recording)
        gps_rate_hz: Location row rate
        lat0, lon0: start coordinate (deg WGS84)
        preamble: emit the optional '#' metadata preamble

    Returns:
        path as str
    """
    accel_t = np.arange(0.0, duration_s, 1.0 / fs)
    excitation = np.zeros_like(accel_t) if a_vert is None else np.asarray(a_vert(accel_t), float)

    frames = [pd.DataFrame({
        'Time': ANCHOR_MS + np.round(accel_t * 1000.0).astype(np.int64),
        'Type': 'Accelerometer',
        'X': 0.0,
        'Y': 0.0,
        'Z': G0 + excitation,
        'Latitude': np.nan,
        'Longitude': np.nan,
    })]

    if gps:
        gps_t = np.arange(0.0, duration_s + 1e-9, 1.0 / gps_rate_hz)
        frames.append(pd.DataFrame({
            'Time': ANCHOR_MS + np.round(gps_t * 1000.0).astype(np.int64),
            'Type': 'Location',
            'X': np.nan,
            'Y': np.nan,
            'Z': np.nan,
            'Latitude': lat0 + speed_mps * gps_t / METERS_PER_DEG_LAT,
            'Longitude': lon0,
        }))

    df = pd.concat(frames, ignore_index=True).sort_values('Time', kind='mergesort')

    with open(path, 'w', encoding='utf-8', newline='') as f:
        if preamble:
            f.write(CSV_PREAMBLE)
        df[CSV_HEADER].to_csv(f, index=False)

    return str(path)


@pytest.fixture
def drive_csv(tmp_path):
    """Factory writing a synthetic drive CSV into the test's tmp_path."""
    def _factory(name: str = 'drive.csv', **kwargs) -> str:
        return write_drive_csv(tmp_path / name, **kwargs)
    return _factory

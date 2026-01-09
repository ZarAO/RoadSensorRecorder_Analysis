import numpy as np
import pandas as pd
from scipy.signal import find_peaks, savgol_filter

def compute_rmsa(df, accel_z_series, window_size=10):
    df['accel_z_filtered'] = savgol_filter(accel_z_series.interpolate(), window_length=11, polyorder=2)
    z = df['accel_z_filtered'].fillna(0)
    z = z - z.mean()

    smoothed = z.rolling(window=window_size, center=True).median()
    rmsa = smoothed.rolling(window=window_size, center=True).apply(lambda x: np.sqrt(np.mean(x**2)))

    return rmsa

def detect_peaks(accel_z_series, threshold):
    return find_peaks(accel_z_series.fillna(0), height=threshold)

def segment_data(df, rmsa, segment_length=30):
    df['segment'] = (np.arange(len(df)) // segment_length).astype(int)
    segments = []
    for segment_id, group in df.groupby('segment'):
        gps_only = group[group['Type'] == 'Location']
        avg_lat = gps_only['Latitude'].mean() if not gps_only.empty else None
        avg_lon = gps_only['Longitude'].mean() if not gps_only.empty else None
        segment_rmsa = rmsa.loc[group.index].dropna()
        avg_rmsa = segment_rmsa.mean() if not segment_rmsa.empty else None

        segments.append({
            "segment": segment_id,
            "avg_latitude": avg_lat,
            "avg_longitude": avg_lon,
            "avg_rmsa": avg_rmsa
        })

    return pd.DataFrame(segments).dropna(subset=["avg_latitude", "avg_longitude"])

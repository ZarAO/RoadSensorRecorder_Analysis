import pandas as pd
import numpy as np
import pytz

kyiv_tz = pytz.timezone("Europe/Kyiv")

def preprocess_data(df):
    if 'Time' not in df.columns:
        raise ValueError("Стовпець 'Time' відсутній у CSV. Перевірте структуру файлу.")

    if pd.api.types.is_numeric_dtype(df['Time']):
        df['Time'] = pd.to_datetime(df['Time'], unit='ms', utc=True).dt.tz_convert(kyiv_tz)
    else:
        df['Time'] = pd.to_datetime(df['Time'], errors='coerce', utc=True).dt.tz_convert(kyiv_tz)
    
    df = df.dropna(subset=['Time'])

    df_filtered = df.copy()
    df_filtered['accel_x'] = np.where(df_filtered['Type'] == 'Accelerometer', df_filtered['X'], np.nan)
    df_filtered['accel_y'] = np.where(df_filtered['Type'] == 'Accelerometer', df_filtered['Y'], np.nan)
    df_filtered['accel_z'] = np.where(df_filtered['Type'] == 'Accelerometer', df_filtered['Z'], np.nan)

    df_filtered['gyro_x'] = np.where(df_filtered['Type'] == 'Gyroscope', df_filtered['X'], np.nan)
    df_filtered['gyro_y'] = np.where(df_filtered['Type'] == 'Gyroscope', df_filtered['Y'], np.nan)
    df_filtered['gyro_z'] = np.where(df_filtered['Type'] == 'Gyroscope', df_filtered['Z'], np.nan)
    
    return df_filtered

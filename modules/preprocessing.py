import pandas as pd
import numpy as np
import pytz
from scipy.signal import butter, filtfilt

kyiv_tz = pytz.timezone("Europe/Kyiv")

def calibrate_accelerometer(accel_x, accel_y, accel_z):
    """
    Калібрування акселерометра з компенсацією гравітації.
    Віднімає гравітаційний вектор для отримання чистих вібрацій.
    
    Параметри:
    - accel_x, accel_y, accel_z: pandas Series з даними акселерометра (м/с²)
    
    Повертає:
    - Відкалібровані значення без впливу гравітації
    """
    # Працюємо тільки з не-NaN значеннями
    # Обчислюємо середній вектор гравітації (припускаємо, що пристрій переважно горизонтальний)
    gravity_x = accel_x.rolling(window=50, center=True, min_periods=1).mean()
    gravity_y = accel_y.rolling(window=50, center=True, min_periods=1).mean()
    gravity_z = accel_z.rolling(window=50, center=True, min_periods=1).mean()
    
    # Віднімаємо гравітацію (результат буде NaN там, де були NaN в оригіналі)
    linear_accel_x = accel_x - gravity_x
    linear_accel_y = accel_y - gravity_y
    linear_accel_z = accel_z - gravity_z
    
    return linear_accel_x, linear_accel_y, linear_accel_z

def remove_outliers(series, threshold=3.0):
    """
    Видаляє викиди з даних використовуючи метод Z-score.
    
    Параметри:
    - series: pandas Series з даними
    - threshold: поріг Z-score для визначення викидів
    
    Повертає:
    - Series з видаленими викидами (заміненими на NaN)
    """
    # Обчислюємо статистику тільки для не-NaN значень
    valid_data = series.dropna()
    if len(valid_data) == 0:
        return series
    
    mean = valid_data.mean()
    std = valid_data.std()
    
    # Якщо немає варіації, повертаємо без змін
    if std == 0:
        return series
    
    # Обчислюємо Z-scores тільки для не-NaN
    z_scores = np.abs((series - mean) / std)
    return series.where(z_scores < threshold, np.nan)

def apply_highpass_filter(data, cutoff=0.5, fs=50, order=4):
    """
    Застосовує високочастотний фільтр Баттерворта для видалення
    низькочастотних компонентів (шум від двигуна, тощо).
    
    Параметри:
    - data: pandas Series з даними
    - cutoff: частота зрізу (Гц)
    - fs: частота дискретизації (Гц)
    - order: порядок фільтра
    
    Повертає:
    - Відфільтровані дані
    """
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype='high', analog=False)
    filtered_data = filtfilt(b, a, data.fillna(0))
    return pd.Series(filtered_data, index=data.index)

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
    
    # Калібрування акселерометра (видалення гравітації)
    df_filtered['accel_x_cal'], df_filtered['accel_y_cal'], df_filtered['accel_z_cal'] = calibrate_accelerometer(
        df_filtered['accel_x'], 
        df_filtered['accel_y'], 
        df_filtered['accel_z']
    )
    
    # Видалення викидів (тільки для не-NaN значень)
    df_filtered['accel_x_cal'] = remove_outliers(df_filtered['accel_x_cal'])
    df_filtered['accel_y_cal'] = remove_outliers(df_filtered['accel_y_cal'])
    df_filtered['accel_z_cal'] = remove_outliers(df_filtered['accel_z_cal'])
    
    # ПРИМІТКА: Високочастотний фільтр не застосовується до розріджених даних
    # Замість цього фільтрація відбувається в compute_rmsa() через Savitzky-Golay
    
    return df_filtered

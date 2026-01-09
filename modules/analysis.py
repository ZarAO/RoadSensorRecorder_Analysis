import numpy as np
import pandas as pd
from scipy.signal import find_peaks, savgol_filter

def compute_rmsa(df, accel_x_series, accel_y_series, accel_z_series, window_size=10):
    """
    Обчислює тривісне середньоквадратичне прискорення (3D RMSA).
    
    Формула: RMSA = sqrt(RMS_x² + RMS_y² + RMS_z²)
    де RMS_i = sqrt(mean(a_i²))
    
    Параметри:
    - df: DataFrame з даними
    - accel_x_series, accel_y_series, accel_z_series: відкалібровані дані акселерометра
    - window_size: розмір ковзного вікна для згладжування
    
    Повертає:
    - pandas Series з значеннями RMSA (м/с²)
    """
    # Заповнюємо пропуски та згладжуємо дані
    x_filled = accel_x_series.ffill().bfill().fillna(0)
    y_filled = accel_y_series.ffill().bfill().fillna(0)
    z_filled = accel_z_series.ffill().bfill().fillna(0)
    
    # Згладжування даних фільтром Савіцького-Голея
    x_filtered = savgol_filter(x_filled, window_length=11, polyorder=2)
    y_filtered = savgol_filter(y_filled, window_length=11, polyorder=2)
    z_filtered = savgol_filter(z_filled, window_length=11, polyorder=2)
    
    # Центрування навколо середнього
    x = x_filtered - np.mean(x_filtered)
    y = y_filtered - np.mean(y_filtered)
    z = z_filtered - np.mean(z_filtered)
    
    # Обчислення RMS для кожної осі
    rms_x = pd.Series(x).rolling(window=window_size, center=True).apply(lambda vals: np.sqrt(np.mean(vals**2)))
    rms_y = pd.Series(y).rolling(window=window_size, center=True).apply(lambda vals: np.sqrt(np.mean(vals**2)))
    rms_z = pd.Series(z).rolling(window=window_size, center=True).apply(lambda vals: np.sqrt(np.mean(vals**2)))
    
    # Тривісний RMSA
    rmsa = np.sqrt(rms_x**2 + rms_y**2 + rms_z**2)
    
    return rmsa

def classify_road_quality(rmsa_value):
    """
    Класифікує якість дорожнього покриття на основі RMSA.
    
    Шкала відповідає приблизно IRI (International Roughness Index):
    - Відмінно: RMSA < 0.5 м/с² (IRI < 2 м/км)
    - Добре: 0.5 ≤ RMSA < 1.0 м/с² (IRI 2-4 м/км)
    - Задовільно: 1.0 ≤ RMSA < 2.0 м/с² (IRI 4-8 м/км)
    - Погано: RMSA ≥ 2.0 м/с² (IRI > 8 м/км)
    
    Параметри:
    - rmsa_value: значення RMSA (м/с²)
    
    Повертає:
    - tuple: (категорія, колір для візуалізації)
    """
    if pd.isna(rmsa_value):
        return ('Невідомо', 'gray')
    elif rmsa_value < 0.5:
        return ('Відмінно', 'green')
    elif rmsa_value < 1.0:
        return ('Добре', 'lightgreen')
    elif rmsa_value < 2.0:
        return ('Задовільно', 'orange')
    else:
        return ('Погано', 'red')

def detect_peaks(accel_z_series, threshold):
    """
    Виявляє піки прискорення.
    
    Параметри:
    - accel_z_series: дані акселерометра (вісь Z)
    - threshold: поріг для виявлення піків
    
    Повертає:
    - індекси піків та їх властивості
    """
    # Заповнюємо пропуски
    data = accel_z_series.ffill().bfill().fillna(0)
    return find_peaks(data, height=threshold)

def segment_data(df, rmsa, segment_length=30):
    """
    Сегментує дорогу на ділянки та обчислює середній RMSA для кожної.
    
    Параметри:
    - df: DataFrame з даними
    - rmsa: Series з значеннями RMSA
    - segment_length: довжина сегмента (кількість записів)
    
    Повертає:
    - DataFrame з інформацією про кожен сегмент
    """
    df['segment'] = (np.arange(len(df)) // segment_length).astype(int)
    segments = []
    for segment_id, group in df.groupby('segment'):
        gps_only = group[group['Type'] == 'Location']
        avg_lat = gps_only['Latitude'].mean() if not gps_only.empty else None
        avg_lon = gps_only['Longitude'].mean() if not gps_only.empty else None
        segment_rmsa = rmsa.loc[group.index].dropna()
        avg_rmsa = segment_rmsa.mean() if not segment_rmsa.empty else None
        
        # Класифікація якості дороги
        quality, color = classify_road_quality(avg_rmsa)

        segments.append({
            "segment": segment_id,
            "avg_latitude": avg_lat,
            "avg_longitude": avg_lon,
            "avg_rmsa": avg_rmsa,
            "quality": quality,
            "color": color
        })

    return pd.DataFrame(segments).dropna(subset=["avg_latitude", "avg_longitude"])

"""
Головний файл для аналізу даних дорожніх сенсорів
Автоматично завантажує найновіший CSV-файл з папки data,
обробляє дані, аналізує і будує візуалізації.
"""

from modules.io_utils import load_data, create_results_directory
from modules.preprocessing import preprocess_data
from modules.analysis import compute_rmsa, detect_peaks
from modules.visualization import (
    plot_accel_z, 
    plot_gyro_y, 
    plot_rmsa, 
    plot_peaks,
    plot_gps_map,
    segment_and_export
)

def main():
    """
    Головна функція для аналізу даних сенсорів
    """
    print("=" * 60)
    print("Аналіз даних дорожніх сенсорів")
    print("=" * 60)
    
    # 1. Завантаження даних
    print("\n[1/7] Завантаження даних...")
    df = load_data()  # Автоматично завантажить найновіший файл з папки data
    print(f"Завантажено {len(df)} записів")
    
    # 2. Попередня обробка
    print("\n[2/7] Попередня обробка даних...")
    df = preprocess_data(df)
    print(f"Оброблено {len(df)} записів")
    
    # 3. Створення директорії для результатів
    print("\n[3/7] Створення директорії для результатів...")
    results_dir = create_results_directory()
    print(f"Результати будуть збережені у: {results_dir}")
    
    # 4. Обчислення тривісного RMSA
    print("\n[4/7] Обчислення тривісного RMSA...")
    rmsa = compute_rmsa(df, df['accel_x_cal'], df['accel_y_cal'], df['accel_z_cal'])
    print(f"RMSA обчислено для {len(rmsa.dropna())} точок")
    
    # 5. Виявлення піків
    print("\n[5/7] Виявлення піків прискорення...")
    peaks, _ = detect_peaks(df['accel_z_cal'].fillna(0), threshold=0.5)
    print(f"Виявлено {len(peaks)} піків")
    
    # 6. Побудова графіків
    print("\n[6/7] Побудова графіків...")
    plot_accel_z(df, results_dir)
    print("  ✓ Графік акселерометра збережено")
    
    plot_gyro_y(df, results_dir)
    print("  ✓ Графік гіроскопа збережено")
    
    plot_rmsa(df['Time'], rmsa, results_dir)
    print("  ✓ Графік RMSA збережено")
    
    plot_peaks(df['Time'], df['accel_z_cal'], peaks, results_dir)
    print("  ✓ Графік піків збережено")
    
    # 7. Побудова GPS мапи та сегментація
    print("\n[7/7] Побудова GPS мапи та сегментація...")
    plot_gps_map(df, results_dir)
    segment_and_export(df, rmsa, results_dir)
    
    print("\n" + "=" * 60)
    print(f"✅ Аналіз завершено! Результати у: {results_dir}")
    print("=" * 60)

if __name__ == "__main__":
    main()

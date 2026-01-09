import json
import matplotlib
matplotlib.use('Agg')  # Використовуємо non-interactive backend
import matplotlib.pyplot as plt
import os
import folium
import pandas as pd

from modules.analysis import segment_data

def plot_accel_z(df, results_dir):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    # Оригінальні дані
    ax1.plot(df['Time'], df['accel_x'], label='X', alpha=0.7)
    ax1.plot(df['Time'], df['accel_y'], label='Y', alpha=0.7)
    ax1.plot(df['Time'], df['accel_z'], label='Z', alpha=0.7)
    ax1.set_title('Прискорення (оригінальні дані)')
    ax1.set_xlabel('Час')
    ax1.set_ylabel('Прискорення, m/s²')
    ax1.legend()
    ax1.grid(True)
    
    # Калібровані дані (без гравітації)
    ax2.plot(df['Time'], df['accel_x_cal'], label='X (калібр.)', alpha=0.7)
    ax2.plot(df['Time'], df['accel_y_cal'], label='Y (калібр.)', alpha=0.7)
    ax2.plot(df['Time'], df['accel_z_cal'], label='Z (калібр.)', alpha=0.7)
    ax2.set_title('Прискорення (калібровані, без гравітації)')
    ax2.set_xlabel('Час')
    ax2.set_ylabel('Прискорення, m/s²')
    ax2.legend()
    ax2.grid(True)
    
    plt.tight_layout()
    fig.savefig(os.path.join(results_dir, 'accelerometer.png'))
    plt.close(fig)

def plot_gyro_y(df, results_dir):
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(df['Time'], df['gyro_y'], label='Y')
    ax.plot(df['Time'], df['gyro_x'], label='X')
    ax.plot(df['Time'], df['gyro_z'], label='Z')
    ax.set_title('Гіроскоп (Gyroscope)')
    ax.set_xlabel('Час')
    ax.set_ylabel('Кутова швидкість, rad/s')
    ax.legend()
    ax.grid(True)
    plt.tight_layout()
    fig.savefig(os.path.join(results_dir, 'gyroscope.png'))
    plt.close(fig)

def plot_rmsa(time, rmsa, results_dir):
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(time, rmsa, label='RMSA (Z)', color='red')
    ax.set_title('Середньоквадратичне прискорення (RMSA)')
    ax.set_xlabel('Час')
    ax.set_ylabel('RMSA (m/s²)')
    ax.legend()
    ax.grid(True)
    plt.tight_layout()
    fig.savefig(os.path.join(results_dir, 'rmsa.png'))
    plt.close(fig)

def plot_peaks(time, accel_z, peaks, results_dir):
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(time, accel_z, label='Вібрації (Z)', color='gray')
    ax.plot(time.iloc[peaks], accel_z.iloc[peaks], "rx", label='Піки')
    ax.set_title('Виявлення піків прискорення')
    ax.set_xlabel('Час')
    ax.set_ylabel('Прискорення (m/s²)')
    ax.legend()
    ax.grid(True)
    plt.tight_layout()
    fig.savefig(os.path.join(results_dir, 'peaks.png'))
    plt.close(fig)

def plot_gps_map(df, results_dir):
    gps_data = df[df['Type'] == 'Location'][['Latitude', 'Longitude']].dropna()
    if not gps_data.empty:
        map_center = [gps_data['Latitude'].iloc[0], gps_data['Longitude'].iloc[0]]
        road_map = folium.Map(location=map_center, zoom_start=16)
        coords = list(zip(gps_data['Latitude'], gps_data['Longitude']))
        folium.PolyLine(coords, color='blue', weight=4.5, opacity=0.7).add_to(road_map)
        gps_file = os.path.join(results_dir, "gps_track.html")
        road_map.save(gps_file)
        print(f"Мапа з GPS-треком збережена у файл {gps_file}")
    else:
        print("Недостатньо GPS-даних для побудови мапи.")

def segment_and_export(df, rmsa, results_dir):
    segments_df = segment_data(df, rmsa)
    segments_csv = os.path.join(results_dir, "road_segments.csv")
    segments_df.to_csv(segments_csv, index=False)
    print(f"Сегменти дороги збережено у файл {segments_csv}")

    road_map = folium.Map(
        location=[segments_df['avg_latitude'].mean(), segments_df['avg_longitude'].mean()],
        zoom_start=14
    )

    # Додаємо легенду
    legend_html = '''
    <div style="position: fixed; 
                top: 10px; right: 10px; width: 200px; height: 150px; 
                background-color: white; border:2px solid grey; z-index:9999; 
                font-size:14px; padding: 10px">
    <p><strong>Якість дороги</strong></p>
    <p><span style="color:green;">●</span> Відмінно (< 0.5 m/s²)</p>
    <p><span style="color:lightgreen;">●</span> Добре (0.5-1.0 m/s²)</p>
    <p><span style="color:orange;">●</span> Задовільно (1.0-2.0 m/s²)</p>
    <p><span style="color:red;">●</span> Погано (≥ 2.0 m/s²)</p>
    </div>
    '''
    road_map.get_root().html.add_child(folium.Element(legend_html))

    for _, row in segments_df.iterrows():
        folium.CircleMarker(
            location=(row['avg_latitude'], row['avg_longitude']),
            radius=6,
            color=row['color'],
            fill=True,
            fill_opacity=0.8,
            popup=f"Сегмент {int(row['segment'])}<br>"
                  f"RMSA: {row['avg_rmsa']:.2f} m/s²<br>"
                  f"Якість: {row['quality']}" if pd.notna(row['avg_rmsa']) else f"Сегмент {int(row['segment'])}: RMSA=NaN"
        ).add_to(road_map)

    segments_map_file = os.path.join(results_dir, "segments_map.html")
    road_map.save(segments_map_file)
    print(f"Мапу з сегментами збережено у файл {segments_map_file}")
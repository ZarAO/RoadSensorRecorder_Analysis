import json
import matplotlib.pyplot as plt
import os
import folium
import pandas as pd

from modules.analysis import segment_data

def plot_accel_z(df, results_dir):
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(df['Time'], df['accel_x'], label='X')
    ax.plot(df['Time'], df['accel_y'], label='Y')
    ax.plot(df['Time'], df['accel_z'], label='Z')
    ax.set_title('Прискорення (Accelerometer)')
    ax.set_xlabel('Час')
    ax.set_ylabel('Прискорення, m/s^2')
    ax.legend()
    ax.grid(True)
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

    for _, row in segments_df.iterrows():
        if row['avg_rmsa'] is not None and row['avg_rmsa'] >= 2.0:
            color = 'red'
        elif row['avg_rmsa'] is not None and row['avg_rmsa'] >= 0.5 and row['avg_rmsa'] < 1.0:
            color = 'yellow'
        elif row['avg_rmsa'] is not None and row['avg_rmsa'] >= 1.0 and row['avg_rmsa'] < 2.0:
            color = 'orange'
        elif row['avg_rmsa'] is not None and row['avg_rmsa'] < 0.5:
            color = 'green'

        folium.CircleMarker(
            location=(row['avg_latitude'], row['avg_longitude']),
            radius=6,
            color=color,
            fill=True,
            fill_opacity=0.8,
            popup=f"Segment {int(row['segment'])}: RMSA={row['avg_rmsa']:.2f}" if row['avg_rmsa'] is not None else f"Segment {int(row['segment'])}: RMSA=NaN"
        ).add_to(road_map)

    segments_map_file = os.path.join(results_dir, "segments_map.html")
    road_map.save(segments_map_file)
    print(f"Мапу з сегментами збережено у файл {segments_map_file}")
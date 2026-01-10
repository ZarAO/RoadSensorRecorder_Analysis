"""
Експорт артефактів: GeoJSON, HTML maps, plots
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional, Tuple


def export_segments_geojson(
    segments_df: pd.DataFrame,
    s_grid: np.ndarray,
    gps_time: np.ndarray,
    gps_lat: np.ndarray,
    gps_lon: np.ndarray,
    t_grid: np.ndarray,
    output_path: str
) -> None:
    """
    Експортувати сегменти як GeoJSON LineString features
    
    Args:
        segments_df: DataFrame сегментів з метриками
        s_grid: distance grid
        gps_time, gps_lat, gps_lon: GPS траєкторія
        t_grid: uniform time grid
        output_path: шлях до GeoJSON файлу
    """
    from scipy.interpolate import interp1d
    
    # Інтерполювати GPS координати на time grid
    lat_interp = interp1d(gps_time, gps_lat, kind='linear', fill_value='extrapolate')
    lon_interp = interp1d(gps_time, gps_lon, kind='linear', fill_value='extrapolate')
    
    lat_grid = lat_interp(t_grid)
    lon_grid = lon_interp(t_grid)
    
    features = []
    
    for _, row in segments_df.iterrows():
        # Знайти індекси для цього сегменту
        seg_mask = (s_grid >= row['s_start']) & (s_grid < row['s_end'])
        seg_indices = np.where(seg_mask)[0]
        
        if len(seg_indices) < 2:
            # Якщо менше 2 точок, створимо Point на середині
            s_mid_idx = np.argmin(np.abs(s_grid - (row['s_start'] + row['s_end']) / 2))
            coordinates = [float(lon_grid[s_mid_idx]), float(lat_grid[s_mid_idx])]
            geometry = {"type": "Point", "coordinates": coordinates}
        else:
            # Створимо LineString
            coordinates = [
                [float(lon_grid[i]), float(lat_grid[i])]
                for i in seg_indices
            ]
            geometry = {"type": "LineString", "coordinates": coordinates}
        
        # Properties з усіма метриками
        properties = {
            "seg_id": int(row['seg_id']),
            "s_start": float(row['s_start']),
            "s_end": float(row['s_end']),
            "length_m": float(row['length_m']),
            "iri_multi": float(row['iri_multi']),
            "iri_psd_raw": float(row['iri_psd_raw']),
            "iri_psd": float(row['iri_psd']),
            "grms": float(row['grms']),
            "mean_speed_kmh": float(row['mean_speed_kmh']),
            "valid_ratio": float(row['valid_ratio']),
            "anomaly_count": int(row['anomaly_count'])
        }
        
        # Debug поля (опціонально)
        if 'psd_sqrt_scalar' in row:
            properties['psd_sqrt_scalar'] = float(row['psd_sqrt_scalar'])
        if 'psd_scalar_mode' in row:
            properties['psd_scalar_mode'] = str(row['psd_scalar_mode'])
        if 'psd_band_power' in row:
            properties['psd_band_power'] = float(row['psd_band_power'])
        
        feature = {
            "type": "Feature",
            "geometry": geometry,
            "properties": properties
        }
        features.append(feature)
    
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, indent=2, ensure_ascii=False)


def export_events_geojson(
    s_grid: np.ndarray,
    anomaly_mask: np.ndarray,
    gps_time: np.ndarray,
    gps_lat: np.ndarray,
    gps_lon: np.ndarray,
    t_grid: np.ndarray,
    output_path: str
) -> None:
    """
    Експортувати аномалії як GeoJSON Point features
    
    Args:
        s_grid: distance grid
        anomaly_mask: boolean mask аномалій
        gps_time, gps_lat, gps_lon: GPS траєкторія
        t_grid: uniform time grid
        output_path: шлях до GeoJSON файлу
    """
    from scipy.interpolate import interp1d
    
    # Інтерполювати GPS на time grid
    lat_interp = interp1d(gps_time, gps_lat, kind='linear', fill_value='extrapolate')
    lon_interp = interp1d(gps_time, gps_lon, kind='linear', fill_value='extrapolate')
    
    lat_grid = lat_interp(t_grid)
    lon_grid = lon_interp(t_grid)
    
    # Знайти індекси аномалій
    anomaly_indices = np.where(anomaly_mask)[0]
    
    features = []
    
    for idx in anomaly_indices:
        lat = float(lat_grid[idx])
        lon = float(lon_grid[idx])
        distance = float(s_grid[idx])
        time = float(t_grid[idx])
        
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat]
            },
            "properties": {
                "event_type": "threshold_10ms2",
                "distance_m": distance,
                "time_s": time
            }
        }
        features.append(feature)
    
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, indent=2, ensure_ascii=False)


def create_segments_map_html(
    segments_df: pd.DataFrame,
    s_grid: np.ndarray,
    gps_time: np.ndarray,
    gps_lat: np.ndarray,
    gps_lon: np.ndarray,
    t_grid: np.ndarray,
    output_path: str
) -> None:
    """
    Створити folium карту з сегментами
    
    Args:
        segments_df: DataFrame сегментів
        s_grid: distance grid
        gps_time, gps_lat, gps_lon: GPS траєкторія
        t_grid: uniform time grid
        output_path: шлях до HTML файлу
    """
    import folium
    from scipy.interpolate import interp1d
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors
    
    # Інтерполювати GPS на time grid
    lat_interp = interp1d(gps_time, gps_lat, kind='linear', fill_value='extrapolate')
    lon_interp = interp1d(gps_time, gps_lon, kind='linear', fill_value='extrapolate')
    
    lat_grid = lat_interp(t_grid)
    lon_grid = lon_interp(t_grid)
    
    # Центр карти
    center_lat = np.mean(gps_lat)
    center_lon = np.mean(gps_lon)
    
    # Створити карту
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=13,
        tiles='OpenStreetMap'
    )
    
    # Додати повну GPS траєкторію (сіра лінія)
    gps_track = [[float(lat), float(lon)] for lat, lon in zip(gps_lat, gps_lon)]
    folium.PolyLine(
        gps_track,
        color='gray',
        weight=2,
        opacity=0.5,
        popup='GPS Track'
    ).add_to(m)
    
    # Кольорова шкала по IRI_multi
    if len(segments_df) > 0 and 'iri_multi' in segments_df.columns:
        # Визначити min/max для кольорової шкали
        iri_values = segments_df['iri_multi'].replace([np.inf, -np.inf], np.nan).dropna()
        if len(iri_values) > 0:
            vmin = iri_values.min()
            vmax = iri_values.max()
            
            # Нормалізувати
            norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
            cmap = cm.get_cmap('RdYlGn_r')  # Червоний=високий IRI (поганий), зелений=низький (добрий)
            
            for _, row in segments_df.iterrows():
                # Знайти індекси для сегменту
                seg_mask = (s_grid >= row['s_start']) & (s_grid < row['s_end'])
                seg_indices = np.where(seg_mask)[0]
                
                if len(seg_indices) < 2:
                    continue
                
                # LineString coordinates
                coordinates = [
                    [float(lat_grid[i]), float(lon_grid[i])]
                    for i in seg_indices
                ]
                
                # Колір по IRI_multi
                iri_val = row['iri_multi']
                if np.isfinite(iri_val):
                    rgba = cmap(norm(iri_val))
                    color = mcolors.to_hex(rgba)
                else:
                    color = 'black'
                
                # Tooltip
                tooltip_html = f"""
                <b>Segment {row['seg_id']}</b><br>
                Distance: {row['s_start']:.0f} - {row['s_end']:.0f} m<br>
                IRI_multi: {row['iri_multi']:.2f} m/km<br>
                IRI_psd: {row['iri_psd']:.2f} m/km<br>
                Grms: {row['grms']:.4f} g<br>
                Speed: {row['mean_speed_kmh']:.1f} km/h<br>
                Anomalies: {row['anomaly_count']}
                """
                
                folium.PolyLine(
                    coordinates,
                    color=color,
                    weight=5,
                    opacity=0.8,
                    tooltip=tooltip_html
                ).add_to(m)
    
    # Зберегти
    m.save(output_path)


def create_plots(
    s_grid: np.ndarray,
    v_grid: np.ndarray,
    a_vertical_g: np.ndarray,
    segments_df: pd.DataFrame,
    output_dir: str
) -> None:
    """
    Створити діагностичні графіки
    
    Args:
        s_grid: distance grid (м)
        v_grid: velocity grid (м/с)
        a_vertical_g: vertical accel в g
        segments_df: DataFrame сегментів
        output_dir: директорія для PNG файлів
    """
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 1. Speed vs distance
    plt.figure(figsize=(12, 4))
    plt.plot(s_grid, v_grid * 3.6, 'b-', linewidth=0.5, alpha=0.7)
    plt.xlabel('Distance (m)')
    plt.ylabel('Speed (km/h)')
    plt.title('Speed vs Distance')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path / 'speed_vs_distance.png', dpi=150)
    plt.close()
    
    # 2. Vertical acceleration vs distance
    plt.figure(figsize=(12, 4))
    plt.plot(s_grid, a_vertical_g, 'g-', linewidth=0.5, alpha=0.7)
    plt.xlabel('Distance (m)')
    plt.ylabel('Vertical acceleration (g)')
    plt.title('Vertical Acceleration vs Distance')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path / 'accel_vs_distance.png', dpi=150)
    plt.close()
    
    # 3. Grms and IRI_multi vs distance (bar plot)
    if len(segments_df) > 0:
        plt.figure(figsize=(12, 6))
        
        plt.subplot(2, 1, 1)
        seg_centers = (segments_df['s_start'] + segments_df['s_end']) / 2
        plt.bar(seg_centers, segments_df['grms'], width=80, color='orange', alpha=0.7, edgecolor='black', linewidth=0.5)
        plt.xlabel('Distance (m)')
        plt.ylabel('Grms (g)')
        plt.title('Grms per 100m Segment')
        plt.grid(True, alpha=0.3, axis='y')
        
        plt.subplot(2, 1, 2)
        plt.bar(seg_centers, segments_df['iri_multi'], width=80, color='purple', alpha=0.7, edgecolor='black', linewidth=0.5)
        plt.xlabel('Distance (m)')
        plt.ylabel('IRI_multi (m/km)')
        plt.title('IRI_multi per 100m Segment')
        plt.grid(True, alpha=0.3, axis='y')
        
        plt.tight_layout()
        plt.savefig(output_path / 'metrics_vs_distance.png', dpi=150)
        plt.close()
    
    # 4. IRI_psd_raw vs distance
    if len(segments_df) > 0:
        plt.figure(figsize=(12, 4))
        seg_centers = (segments_df['s_start'] + segments_df['s_end']) / 2
        
        # Показати raw (може бути негативний) і clipped
        plt.plot(seg_centers, segments_df['iri_psd_raw'], 'ro-', label='IRI_psd_raw', markersize=3, alpha=0.7)
        plt.plot(seg_centers, segments_df['iri_psd'], 'bs-', label='IRI_psd (clipped)', markersize=3, alpha=0.7)
        plt.axhline(0, color='black', linestyle='--', linewidth=0.5, alpha=0.5)
        plt.xlabel('Distance (m)')
        plt.ylabel('IRI_psd (m/km)')
        plt.title('IRI_psd (raw and clipped) vs Distance')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(output_path / 'iri_psd_vs_distance.png', dpi=150)
        plt.close()

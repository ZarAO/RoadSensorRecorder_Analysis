"""
Export artifacts: GeoJSON, HTML maps, plots
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional, Tuple

# Low-speed segments are drawn off the IRI colour scale entirely: magenta does not
# occur anywhere in the green-blue-orange-red ramp, so a Class 1/2 candidate cannot
# be mistaken for a graded segment.
LOW_SPEED_COLOR = '#FF00FF'
LOW_SPEED_LEGEND_LABEL = 'Потребує обстеження профілометром (клас 1/2)'


def _json_num(value) -> Optional[float]:
    """
    Number for GeoJSON: NaN/Inf are serialized as null.

    Strict parsers (JSON.parse, QGIS) reject a bare NaN token, so a
    missing metric must be null.
    """
    if value is None:
        return None
    number = float(value)
    return number if np.isfinite(number) else None


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
    Export segments as GeoJSON LineString features

    Args:
        segments_df: segments DataFrame with metrics
        s_grid: distance grid
        gps_time, gps_lat, gps_lon: GPS track
        t_grid: uniform time grid
        output_path: path to the GeoJSON file
    """
    from scipy.interpolate import interp1d

    # Interpolate GPS coordinates onto the time grid
    lat_interp = interp1d(gps_time, gps_lat, kind='linear', fill_value='extrapolate')
    lon_interp = interp1d(gps_time, gps_lon, kind='linear', fill_value='extrapolate')
    
    lat_grid = lat_interp(t_grid)
    lon_grid = lon_interp(t_grid)
    
    features = []
    
    for _, row in segments_df.iterrows():
        # Find indices for this segment
        seg_mask = (s_grid >= row['s_start']) & (s_grid < row['s_end'])
        seg_indices = np.where(seg_mask)[0]

        if len(seg_indices) < 2:
            # If fewer than 2 points, create a Point at the midpoint
            s_mid_idx = np.argmin(np.abs(s_grid - (row['s_start'] + row['s_end']) / 2))
            coordinates = [float(lon_grid[s_mid_idx]), float(lat_grid[s_mid_idx])]
            geometry = {"type": "Point", "coordinates": coordinates}
        else:
            # Create a LineString
            coordinates = [
                [float(lon_grid[i]), float(lat_grid[i])]
                for i in seg_indices
            ]
            geometry = {"type": "LineString", "coordinates": coordinates}
        
        # Properties with all metrics
        properties = {
            "seg_id": int(row['seg_id']),
            "s_start": _json_num(row['s_start']),
            "s_end": _json_num(row['s_end']),
            "length_m": _json_num(row['length_m']),
            "partial": bool(row['partial']),
            "iri_multi": _json_num(row['iri_multi']),
            "iri_psd_raw": _json_num(row['iri_psd_raw']),
            "iri_psd": _json_num(row['iri_psd']),
            "grms": _json_num(row['grms']),
            "mean_speed_kmh": _json_num(row['mean_speed_kmh']),
            "speed_valid": bool(row['speed_valid']),
            "low_speed_class": str(row['low_speed_class']),
            "needs_class12_survey": bool(row['needs_class12_survey']),
            "dx_le_03_share": _json_num(row['dx_le_03_share']),
            "anomaly_count": int(row['anomaly_count']),
            "events_per_km": _json_num(row['events_per_km'])
        }

        # Debug fields (optional)
        if 'psd_sqrt_scalar' in row:
            properties['psd_sqrt_scalar'] = _json_num(row['psd_sqrt_scalar'])
        if 'psd_scalar_mode' in row:
            properties['psd_scalar_mode'] = str(row['psd_scalar_mode'])
        if 'psd_band_power' in row:
            properties['psd_band_power'] = _json_num(row['psd_band_power'])
        
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
        json.dump(geojson, f, indent=2, ensure_ascii=False, allow_nan=False)


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
    Export anomalies as GeoJSON Point features

    Args:
        s_grid: distance grid
        anomaly_mask: boolean anomaly mask
        gps_time, gps_lat, gps_lon: GPS track
        t_grid: uniform time grid
        output_path: path to the GeoJSON file
    """
    from scipy.interpolate import interp1d

    # Interpolate GPS onto the time grid
    lat_interp = interp1d(gps_time, gps_lat, kind='linear', fill_value='extrapolate')
    lon_interp = interp1d(gps_time, gps_lon, kind='linear', fill_value='extrapolate')

    lat_grid = lat_interp(t_grid)
    lon_grid = lon_interp(t_grid)

    # Find anomaly indices
    anomaly_indices = np.where(anomaly_mask)[0]
    
    features = []
    
    for idx in anomaly_indices:
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [_json_num(lon_grid[idx]), _json_num(lat_grid[idx])]
            },
            "properties": {
                "event_type": "threshold_10ms2",
                "distance_m": _json_num(s_grid[idx]),
                "time_s": _json_num(t_grid[idx])
            }
        }
        features.append(feature)

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, indent=2, ensure_ascii=False, allow_nan=False)


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
    Create a folium map with segments

    Args:
        segments_df: segments DataFrame
        s_grid: distance grid
        gps_time, gps_lat, gps_lon: GPS track
        t_grid: uniform time grid
        output_path: path to the HTML file
    """
    import folium
    from scipy.interpolate import interp1d
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors
    
    # Visual constants for improved visibility
    LINE_WEIGHT = 8          # Color line width
    OUTLINE_WEIGHT = 12      # Black outline width
    LOW_SPEED_WEIGHT_BONUS = 2  # Low-speed segments are drawn thicker than the rest
    LINE_OPACITY = 1.0       # Color line opacity
    OUTLINE_OPACITY = 0.9    # Outline opacity
    GPS_TRACK_WEIGHT = 3     # Background GPS track width
    GPS_TRACK_OPACITY = 0.4  # Background track opacity

    # Interpolate GPS onto the time grid
    lat_interp = interp1d(gps_time, gps_lat, kind='linear', fill_value='extrapolate')
    lon_interp = interp1d(gps_time, gps_lon, kind='linear', fill_value='extrapolate')
    
    lat_grid = lat_interp(t_grid)
    lon_grid = lon_interp(t_grid)
    
    # Map center
    center_lat = np.mean(gps_lat)
    center_lon = np.mean(gps_lon)

    # Create the map
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=13,
        tiles='OpenStreetMap'
    )
    
    
    # Add the full GPS track (gray line)
    gps_track = [[float(lat), float(lon)] for lat, lon in zip(gps_lat, gps_lon)]
    folium.PolyLine(
        gps_track,
        color='gray',
        weight=GPS_TRACK_WEIGHT,
        opacity=GPS_TRACK_OPACITY,
        popup='GPS Track'
    ).add_to(m)
    
    
    has_low_speed = False

    # Color scale by IRI_multi
    if len(segments_df) > 0 and 'iri_multi' in segments_df.columns:
        # Determine min/max for the color scale
        iri_values = segments_df['iri_multi'].replace([np.inf, -np.inf], np.nan).dropna()

        # High-contrast palette: from saturated green through blue and orange to red
        # (avoids pale yellow shades)
        def get_contrast_color(normalized_value):
            """
            Returns a high-contrast color for normalized_value in [0, 1]
            0.0 = green (good road), 1.0 = red (bad road)
            """
            if normalized_value < 0.33:
                # Good: saturated green
                return '#1A9641'
            elif normalized_value < 0.66:
                # Fair: saturated blue
                return '#2C7BB6'
            elif normalized_value < 0.85:
                # Poor: orange
                return '#FF7F00'
            else:
                # Very poor: saturated red
                return '#D7191C'

        # A drive that never cleared the survey speed range has no IRI_multi at all,
        # so there is no scale to normalize against - the segments are still drawn,
        # otherwise the worst road in the dataset would come out as an empty map
        norm = (
            mcolors.Normalize(vmin=iri_values.min(), vmax=iri_values.max())
            if len(iri_values) > 0 else None
        )

        for _, row in segments_df.iterrows():
            # Find indices for the segment
            seg_mask = (s_grid >= row['s_start']) & (s_grid < row['s_end'])
            seg_indices = np.where(seg_mask)[0]

            if len(seg_indices) < 2:
                continue

            # LineString coordinates
            coordinates = [
                [float(lat_grid[i]), float(lon_grid[i])]
                for i in seg_indices
            ]

            # Low-speed segments carry no IRI number at all, so they are taken off
            # the IRI ramp and drawn thicker in magenta
            low_speed = bool(row['needs_class12_survey'])
            if low_speed:
                has_low_speed = True
                color = LOW_SPEED_COLOR
                line_weight = LINE_WEIGHT + LOW_SPEED_WEIGHT_BONUS
                outline_weight = OUTLINE_WEIGHT + LOW_SPEED_WEIGHT_BONUS
            else:
                line_weight, outline_weight = LINE_WEIGHT, OUTLINE_WEIGHT
                iri_val = row['iri_multi']
                if norm is not None and np.isfinite(iri_val):
                    color = get_contrast_color(norm(iri_val))
                else:
                    color = 'black'

            # Tooltip
            tooltip_html = f"""
            <b>Сегмент {row['seg_id']}</b><br>
            Відстань: {row['s_start']:.0f} - {row['s_end']:.0f} м<br>
            IRI_multi: {row['iri_multi']:.2f} м/км<br>
            IRI_psd: {row['iri_psd']:.2f} м/км<br>
            Grms: {row['grms']:.4f} g<br>
            Швидкість: {row['mean_speed_kmh']:.1f} км/год<br>
            Аномалії: {row['anomaly_count']}<br>
            Подій/км: {row['events_per_km']:.2f}
            """
            if low_speed:
                tooltip_html += f"""<br>
                Клас низької швидкості: {row['low_speed_class']}<br>
                <b>{LOW_SPEED_LEGEND_LABEL}</b>
                """

            # Outline: draw a thick black line first
            folium.PolyLine(
                coordinates,
                color='#000000',
                weight=outline_weight,
                opacity=OUTLINE_OPACITY,
                line_cap='round',
                line_join='round'
            ).add_to(m)

            # Color line on top of the outline
            folium.PolyLine(
                coordinates,
                color=color,
                weight=line_weight,
                opacity=LINE_OPACITY,
                line_cap='round',
                line_join='round',
                tooltip=tooltip_html
            ).add_to(m)

    # Legend: only meaningful when the map actually shows such a segment
    if has_low_speed:
        legend_html = f"""
        <div style="position: fixed; bottom: 24px; left: 24px; z-index: 9999;
                    background: white; padding: 10px 12px; border: 2px solid #333333;
                    border-radius: 4px; font-family: sans-serif; font-size: 13px;">
          <span style="display: inline-block; width: 24px; height: 6px;
                       background: {LOW_SPEED_COLOR}; vertical-align: middle;"></span>
          {LOW_SPEED_LEGEND_LABEL}
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

    # Save
    m.save(output_path)


def create_plots(
    s_grid: np.ndarray,
    v_grid: np.ndarray,
    a_vertical_g: np.ndarray,
    segments_df: pd.DataFrame,
    output_dir: str
) -> None:
    """
    Create diagnostic plots

    Args:
        s_grid: distance grid (m)
        v_grid: velocity grid (m/s)
        a_vertical_g: vertical accel in g
        segments_df: segments DataFrame
        output_dir: directory for PNG/PDF files
    """
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    import scienceplots  # noqa: F401  - registers the 'science' style

    # 'no-latex': no local LaTeX installation required
    plt.style.use(['science', 'no-latex'])

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    def save_figure(name: str) -> None:
        """PNG for viewing + PDF (vector) for the dissertation text"""
        plt.savefig(output_path / f'{name}.png', dpi=150)
        plt.savefig(output_path / f'{name}.pdf')
        plt.close()

    # 1. Speed vs distance
    plt.figure(figsize=(12, 4))
    plt.plot(s_grid, v_grid * 3.6, 'b-', linewidth=0.5, alpha=0.7)
    plt.xlabel('Distance (m)')
    plt.ylabel('Speed (km/h)')
    plt.title('Speed vs Distance')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    save_figure('speed_vs_distance')
    
    # 2. Vertical acceleration vs distance
    plt.figure(figsize=(12, 4))
    plt.plot(s_grid, a_vertical_g, 'g-', linewidth=0.5, alpha=0.7)
    plt.xlabel('Distance (m)')
    plt.ylabel('Vertical acceleration (g)')
    plt.title('Vertical Acceleration vs Distance')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    save_figure('accel_vs_distance')
    
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
        save_figure('metrics_vs_distance')
    
    # 4. IRI_psd_raw vs distance
    if len(segments_df) > 0:
        plt.figure(figsize=(12, 4))
        seg_centers = (segments_df['s_start'] + segments_df['s_end']) / 2
        
        # Show raw (can be negative) and clipped
        plt.plot(seg_centers, segments_df['iri_psd_raw'], 'ro-', label='IRI_psd_raw', markersize=3, alpha=0.7)
        plt.plot(seg_centers, segments_df['iri_psd'], 'bs-', label='IRI_psd (clipped)', markersize=3, alpha=0.7)
        plt.axhline(0, color='black', linestyle='--', linewidth=0.5, alpha=0.5)
        plt.xlabel('Distance (m)')
        plt.ylabel('IRI_psd (m/km)')
        plt.title('IRI_psd (raw and clipped) vs Distance')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        save_figure('iri_psd_vs_distance')

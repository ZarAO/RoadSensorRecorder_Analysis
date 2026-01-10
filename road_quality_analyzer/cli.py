"""
CLI для road_quality_analyzer
"""

import argparse
import sys
from pathlib import Path


def main():
    """
    Головна функція CLI
    """
    parser = argparse.ArgumentParser(
        description='Road Quality Analyzer - аналіз дорожнього полотна зі смартфонних сенсорів'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Команди')
    
    # analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Аналізувати сенсорні дані')
    analyze_parser.add_argument('--input', required=True, help='Шлях до CSV файлу')
    analyze_parser.add_argument('--out', required=True, help='Директорія для результатів')
    analyze_parser.add_argument('--config', help='Шлях до YAML конфігу (опціонально)')
    
    args = parser.parse_args()
    
    if args.command == 'analyze':
        analyze(args.input, args.out, args.config)
    else:
        parser.print_help()
        sys.exit(1)


def analyze(input_path: str, output_dir: str, config_path: str = None):
    """
    Повний аналіз сенсорних даних
    
    Args:
        input_path: шлях до CSV
        output_dir: директорія для результатів
        config_path: шлях до конфігу (опціонально)
    """
    import numpy as np
    from pathlib import Path
    
    from road_quality_analyzer.io import load_sensor_csv
    from road_quality_analyzer.preprocessing import build_uniform_time_grid, build_distance_grid
    from road_quality_analyzer.orientation import (
        estimate_gravity, compute_rotation_matrix, transform_to_world,
        compute_gps_heading, compute_perpendicular_accel
    )
    from road_quality_analyzer.anomaly import detect_threshold_anomalies
    from road_quality_analyzer.segmentation import create_segments_dataframe
    
    g0 = 9.80665  # m/s^2
    
    print("="*60)
    print("Road Quality Analyzer - Повний пайплайн")
    print("="*60)
    
    # 1. Завантаження
    print(f"\n[1/8] Завантаження даних з {input_path}...")
    sensor_data = load_sensor_csv(input_path)
    print(f"  Accel samples: {len(sensor_data.accel_time)}")
    if sensor_data.gps_time is not None:
        print(f"  GPS samples: {len(sensor_data.gps_time)}")
    
    # 2. Uniform time grid
    print("\n[2/8] Побудова uniform time grid...")
    t_grid, ax_grid, ay_grid, az_grid = build_uniform_time_grid(
        sensor_data.accel_time,
        sensor_data.accel_x,
        sensor_data.accel_y,
        sensor_data.accel_z
    )
    dt = np.median(np.diff(t_grid))
    fs = 1.0 / dt
    print(f"  Time grid: {len(t_grid)} samples, fs={fs:.1f} Hz")
    
    # 3. Distance grid
    print("\n[3/8] Обчислення distance grid...")
    if sensor_data.gps_time is None:
        print("  УВАГА: Немає GPS даних, пропускаємо distance grid")
        s_grid = np.arange(len(t_grid)) * 0.1  # Заглушка
        v_grid = np.ones(len(t_grid)) * 10.0
    else:
        s_grid, v_grid = build_distance_grid(
            sensor_data.gps_time,
            sensor_data.gps_lat,
            sensor_data.gps_lon,
            t_grid
        )
        print(f"  Total distance: {s_grid[-1]:.1f} m")
        print(f"  Mean speed: {v_grid.mean():.1f} m/s ({v_grid.mean()*3.6:.1f} km/h)")
    
    # 4. Orientation correction
    print("\n[4/8] Orientation-correction (gravity alignment)...")
    g_hat_x, g_hat_y, g_hat_z = estimate_gravity(
        ax_grid, ay_grid, az_grid, fs, cutoff_hz=0.3
    )
    print(f"  Gravity estimated (mean magnitude: {np.mean(np.sqrt(g_hat_x**2 + g_hat_y**2 + g_hat_z**2)):.2f} m/s^2)")
    
    R_matrices = compute_rotation_matrix(g_hat_x, g_hat_y, g_hat_z)
    print(f"  Rotation matrices computed")
    
    a_world_x, a_world_y, a_world_z, a_vertical = transform_to_world(
        ax_grid, ay_grid, az_grid,
        g_hat_x, g_hat_y, g_hat_z,
        R_matrices
    )
    print(f"  Vertical acceleration: mean={np.mean(a_vertical):.3f} m/s^2, std={np.std(a_vertical):.3f} m/s^2)")
    
    # Конвертувати в g
    a_vertical_g = a_vertical / g0
    
    # 5. GPS heading та a_perp
    print("\n[5/8] GPS heading та a_perp...")
    if sensor_data.gps_time is not None:
        heading_x, heading_y, heading_valid = compute_gps_heading(
            sensor_data.gps_time,
            sensor_data.gps_lat,
            sensor_data.gps_lon,
            t_grid,
            heading_min_speed_mps=1.0
        )
        print(f"  Heading valid: {np.sum(heading_valid)} / {len(heading_valid)} samples")
        
        a_perp = compute_perpendicular_accel(
            a_world_x, a_world_y, a_world_z,
            heading_x, heading_y, heading_valid
        )
        print(f"  a_perp computed")
    else:
        a_perp = np.full(len(t_grid), np.nan)
    
    # 6. Anomaly detection
    print("\n[6/8] Anomaly detection (threshold 10 m/s^2)...")
    anomaly_mask = detect_threshold_anomalies(a_vertical, threshold_ms2=10.0)
    n_anomalies = np.sum(anomaly_mask)
    print(f"  Anomalies detected: {n_anomalies} ({100*n_anomalies/len(anomaly_mask):.2f}%)")
    
    # 7. Segmentation 100m
    print("\n[7/8] Сегментація по 100 м...")
    
    # Спробуємо різні scalar modes для діагностики
    scalar_modes = ['band_power_sqrt', 'mean_psd_sqrt', 'median_psd_sqrt', 'peak_psd_sqrt']
    segments_by_mode = {}
    
    for mode in scalar_modes:
        segments_df_mode = create_segments_dataframe(
            s_grid, a_vertical_g, v_grid, fs, anomaly_mask, 
            segment_length_m=100.0, scalar_mode=mode
        )
        segments_by_mode[mode] = segments_df_mode
    
    # За замовчуванням використовуємо band_power_sqrt
    segments_df = segments_by_mode['band_power_sqrt']
    
    print(f"  Segments created: {len(segments_df)}")
    if len(segments_df) > 0:
        print(f"  Mean IRI_psd_raw: {segments_df['iri_psd_raw'].mean():.2f} m/km")
        print(f"  Mean IRI_psd (clipped): {segments_df['iri_psd'].mean():.2f} m/km")
        print(f"  Mean IRI_multi: {segments_df['iri_multi'].mean():.2f} m/km")
    
    # 8. Зберегти результати
    print(f"\n[8/8] Збереження результатів у {output_dir}...")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # CSV сегментів
    segments_csv = output_path / "road_segments.csv"
    segments_df.to_csv(segments_csv, index=False)
    print(f"  ✓ {segments_csv}")
    
    # GeoJSON артефакти
    if sensor_data.gps_time is not None:
        from road_quality_analyzer.artifacts import (
            export_segments_geojson, export_events_geojson, 
            create_segments_map_html, create_plots
        )
        
        # roughness.geojson
        roughness_geojson = output_path / "roughness.geojson"
        export_segments_geojson(
            segments_df, s_grid, 
            sensor_data.gps_time, sensor_data.gps_lat, sensor_data.gps_lon,
            t_grid, str(roughness_geojson)
        )
        print(f"  ✓ {roughness_geojson}")
        
        # events.geojson
        events_geojson = output_path / "events.geojson"
        export_events_geojson(
            s_grid, anomaly_mask,
            sensor_data.gps_time, sensor_data.gps_lat, sensor_data.gps_lon,
            t_grid, str(events_geojson)
        )
        print(f"  ✓ {events_geojson}")
        
        # segments_map.html
        segments_map = output_path / "segments_map.html"
        create_segments_map_html(
            segments_df, s_grid,
            sensor_data.gps_time, sensor_data.gps_lat, sensor_data.gps_lon,
            t_grid, str(segments_map)
        )
        print(f"  ✓ {segments_map}")
        
        # plots/
        plots_dir = output_path / "plots"
        create_plots(s_grid, v_grid, a_vertical_g, segments_df, str(plots_dir))
        print(f"  ✓ {plots_dir}/ (4 PNG files)")
    else:
        print("  ⚠ GPS дані відсутні, GeoJSON/HTML артефакти пропущено")
    
    # Базовий звіт
    report_path = output_path / "report.md"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# Road Quality Analysis Report\n\n")
        f.write(f"**Input:** {input_path}\n\n")
        f.write(f"**Date:** {Path(input_path).name}\n\n")
        
        # Артефакти
        f.write("## Generated Artifacts\n\n")
        f.write("- `road_segments.csv` - метрики 100м сегментів (CSV)\n")
        if sensor_data.gps_time is not None:
            f.write("- `roughness.geojson` - сегменти з геометрією та метриками (GeoJSON)\n")
            f.write("- `events.geojson` - аномалії як точки (GeoJSON)\n")
            f.write("- `segments_map.html` - інтерактивна карта сегментів (відкрийте в браузері)\n")
            f.write("- `plots/` - діагностичні графіки (PNG):\n")
            f.write("  - `speed_vs_distance.png`\n")
            f.write("  - `accel_vs_distance.png`\n")
            f.write("  - `metrics_vs_distance.png` (Grms + IRI_multi)\n")
            f.write("  - `iri_psd_vs_distance.png`\n\n")
        
        f.write("## Summary\n\n")
        f.write(f"- Total distance: {s_grid[-1]:.1f} m\n")
        f.write(f"- Mean speed: {v_grid.mean()*3.6:.1f} km/h\n")
        f.write(f"- Sampling rate: {fs:.1f} Hz\n")
        f.write(f"- Segments (100m): {len(segments_df)}\n")
        f.write(f"- Anomalies: {n_anomalies}\n\n")
        
        # Configuration
        f.write("## Configuration\n\n")
        f.write("Параметри аналізу згідно з `agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md`:\n\n")
        f.write("**Segmentation:**\n")
        f.write("- Segment length: 100 m\n")
        f.write("- Method: cumulative distance grid (B7)\n\n")
        f.write("**IRI_psd (Eq.3):**\n")
        f.write("- PSD method: Welch (scipy.signal.welch)\n")
        f.write("- Frequency band: [0.5, 6.0] Hz (B4)\n")
        f.write("- Scalar mode: band_power_sqrt (default)\n")
        f.write("- Coefficients: A=0.774, B=-0.825 (book values, not modified)\n\n")
        f.write("**IRI_multi (Eq.4/5/6):**\n")
        f.write("- Vehicle type: GENERIC (B5)\n")
        f.write("- Coefficients: a=1.63, b=63.3, c=1.0\n\n")
        f.write("**Anomaly Detection:**\n")
        f.write("- Method: threshold on |a_vertical| (B8)\n")
        f.write("- Threshold: 10 m/s^2 (book baseline)\n\n")
        f.write("**Orientation Correction:**\n")
        f.write("- Gravity alignment: lowpass filter 0.3 Hz (A3)\n")
        f.write("- GPS heading: minimum speed 1.0 m/s (A4)\n\n")
        
        # Sampling compliance (F)
        f.write("## Sampling Compliance\n\n")
        dt_grid = np.median(np.diff(t_grid))
        dx_grid = v_grid * dt_grid
        dx_mean = np.mean(dx_grid)
        dx_p95 = np.percentile(dx_grid, 95)
        share_dx_le_03 = np.sum(dx_grid <= 0.3) / len(dx_grid) * 100
        
        f.write(f"- Median dt: {dt_grid:.4f} s\n")
        f.write(f"- Mean dx: {dx_mean:.3f} m\n")
        f.write(f"- P95 dx: {dx_p95:.3f} m\n")
        f.write(f"- Share dx≤0.3m: {share_dx_le_03:.1f}%\n")
        f.write(f"- Recommended: dx≤0.3m, fs=80-120Hz\n")
        f.write(f"- Current fs: {fs:.1f} Hz {'✓' if 80 <= fs <= 120 else '⚠'}\n\n")
        
        if len(segments_df) > 0:
            f.write("## IRI Statistics (default: band_power_sqrt mode)\n\n")
            f.write(f"- Mean IRI_psd_raw: {segments_df['iri_psd_raw'].mean():.2f} m/km\n")
            f.write(f"- Mean IRI_psd (clipped): {segments_df['iri_psd'].mean():.2f} m/km\n")
            f.write(f"- Mean IRI_multi: {segments_df['iri_multi'].mean():.2f} m/km\n\n")
            
            # PSD scalar diagnostic (D)
            f.write("## PSD Scalar Mode Diagnostic\n\n")
            f.write("Порівняння різних методів скаляризації PSD до sqrt(PSD) для Eq.3:\n\n")
            
            for mode in scalar_modes:
                df_mode = segments_by_mode[mode]
                f.write(f"### Mode: {mode}\n\n")
                f.write(f"- Mean IRI_psd_raw: {df_mode['iri_psd_raw'].mean():.2f} m/km\n")
                f.write(f"- Median IRI_psd_raw: {df_mode['iri_psd_raw'].median():.2f} m/km\n")
                f.write(f"- Mean IRI_psd (clipped): {df_mode['iri_psd'].mean():.2f} m/km\n")
                f.write(f"- % negative raw: {(df_mode['iri_psd_raw'] < 0).sum() / len(df_mode) * 100:.1f}%\n\n")
                
                # Top-5 сегментів для цього режиму
                top5 = df_mode.nlargest(5, 'iri_psd_raw')[['seg_id', 'iri_psd_raw', 'iri_psd', 'grms']]
                f.write("Top 5 segments (by iri_psd_raw):\n\n")
                f.write("| seg_id | iri_psd_raw | iri_psd | grms |\n")
                f.write("|--------|-------------|---------|------|\n")
                for _, row in top5.iterrows():
                    f.write(f"| {row['seg_id']} | {row['iri_psd_raw']:.2f} | {row['iri_psd']:.2f} | {row['grms']:.4f} |\n")
                f.write("\n")
            
            f.write("## Top 10 Worst Segments (by IRI_psd, band_power_sqrt)\n\n")
            top10 = segments_df.nlargest(10, 'iri_psd')[['seg_id', 's_start', 's_end', 'iri_psd_raw', 'iri_psd', 'iri_multi', 'grms']]
            f.write("| seg_id | s_start | s_end | iri_psd_raw | iri_psd | iri_multi | grms |\n")
            f.write("|--------|---------|-------|-------------|---------|-----------|------|\n")
            for _, row in top10.iterrows():
                f.write(f"| {row['seg_id']} | {row['s_start']:.1f} | {row['s_end']:.1f} | {row['iri_psd_raw']:.2f} | {row['iri_psd']:.2f} | {row['iri_multi']:.2f} | {row['grms']:.4f} |\n")
        
        # Assumptions & Limitations
        f.write("\n## Assumptions & Limitations\n\n")
        f.write("**IRI_psd (Eq.3) обмеження:**\n")
        f.write("- Використовує PSD вертикального прискорення, а не профіль дороги (як у книзі)\n")
        f.write("- Коефіцієнти A=0.774, B=-0.825 калібровані для конкретних умов і можуть давати негативні значення на чистих даних\n")
        f.write("- Clipping до 0 застосовується для фінального IRI_psd (raw значення зберігаються для діагностики)\n\n")
        f.write("**Quarter-car IRI:**\n")
        f.write("- Класичний quarter-car IRI потребує профілю дороги та симуляції підвіски (як описано в книзі)\n")
        f.write("- Поточна реалізація використовує спрощені емпіричні формули (Eq.3, Eq.4/5/6)\n\n")
        f.write("**Wheel size:**\n")
        f.write("- Розмір колеса не входить у формули книги (згадується лише як метадані)\n")
        f.write("- Впливає на реальне сприйняття нерівностей, але не на розрахунок IRI в даній реалізації\n\n")
        f.write("**GPS дані:**\n")
        f.write("- GPS heading валідний лише при швидкості > 1.0 m/s\n")
        f.write("- Точність залежить від якості GPS сигналу (indoor/urban canyon можуть погіршити результати)\n\n")
    
    print(f"  ✓ {report_path}")
    
    print(f"\n{'='*60}")
    print("✓ Аналіз завершено успішно!")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()

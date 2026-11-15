"""
CLI for road_quality_analyzer
"""

import argparse
import sys
from pathlib import Path

from road_quality_analyzer.segmentation.segment_100m import (
    DEFAULT_LOW_SPEED_POLICY, LOW_SPEED_CLASS_BY_POLICY, LOW_SPEED_MAX_KMH
)


def main():
    """
    Main CLI entry function
    """
    # Progress output contains Cyrillic and ✓/⚠: without UTF-8 any redirected
    # stdout on Windows crashes with UnicodeEncodeError
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(
        description='Road Quality Analyzer - аналіз дорожнього полотна зі смартфонних сенсорів'
    )

    subparsers = parser.add_subparsers(dest='command', help='Команди')

    # analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Аналізувати сенсорні дані')
    analyze_parser.add_argument('--input', required=True, help='Шлях до CSV файлу')
    analyze_parser.add_argument('--out', required=True, help='Директорія для результатів')
    analyze_parser.add_argument(
        '--iri-psd-A', type=float, default=None, metavar='A',
        help='Калібрований коефіцієнт A для Eq.3 (IRI = A*sqrtPSD + B). '
             'Без прапорця — книжкове значення; книжкові константи в коді незмінні.'
    )
    analyze_parser.add_argument(
        '--iri-psd-B', type=float, default=None, metavar='B',
        help='Калібрований коефіцієнт B для Eq.3 (разом із --iri-psd-A).'
    )
    analyze_parser.add_argument(
        '--low-speed-policy',
        choices=sorted(LOW_SPEED_CLASS_BY_POLICY),
        default=DEFAULT_LOW_SPEED_POLICY,
        help=(
            f'Що робити із сегментами, пройденими повільніше за {LOW_SPEED_MAX_KMH:.0f} км/год: '
            'very-poor/poor/invalid — позначити класом (числовий IRI_multi лишається NaN '
            'за будь-якої політики), ignore — виключити з CSV, GeoJSON і карти '
            f'(у звіті вони все одно враховані). За замовчуванням: {DEFAULT_LOW_SPEED_POLICY}'
        )
    )
    # Experimental ablations (base vs improved method on the same data): opt-in,
    # recorded in recording_meta.json and report.md; the output is not a measurement
    analyze_parser.add_argument(
        '--ablate-orientation', action='store_true',
        help='АБЛЯЦІЯ (лише для дослідження): без gravity alignment — вертикаль = вісь '
             'пристрою з найбільшим |середнім| мінус це середнє.'
    )
    analyze_parser.add_argument(
        '--ablate-segmentation-time', action='store_true',
        help='АБЛЯЦІЯ: замість 100 м сегментів — фіксовані часові вікна тривалістю '
             '100 м / медіанна швидкість руху (v > 1 м/с).'
    )
    analyze_parser.add_argument(
        '--ablate-speed-gate', action='store_true',
        help='АБЛЯЦІЯ: iri_multi рахується для всіх сегментів, також поза 20–100 км/год '
             '(speed_valid зберігає справжнє значення).'
    )

    args = parser.parse_args()

    if args.command == 'analyze':
        analyze(args.input, args.out, low_speed_policy=args.low_speed_policy,
                iri_psd_A=getattr(args, 'iri_psd_A'), iri_psd_B=getattr(args, 'iri_psd_B'),
                ablate_orientation=args.ablate_orientation,
                ablate_segmentation_time=args.ablate_segmentation_time,
                ablate_speed_gate=args.ablate_speed_gate)
    else:
        parser.print_help()
        sys.exit(1)


def analyze(input_path: str, output_dir: str,
            low_speed_policy: str = DEFAULT_LOW_SPEED_POLICY,
            iri_psd_A: float = None, iri_psd_B: float = None,
            ablate_orientation: bool = False,
            ablate_segmentation_time: bool = False,
            ablate_speed_gate: bool = False):
    """
    Full analysis of sensor data

    Args:
        input_path: path to the CSV
        output_dir: directory for results
        low_speed_policy: how to treat segments below LOW_SPEED_MAX_KMH -
            'very-poor'/'poor'/'invalid' label them, 'ignore' drops their rows
            from the CSV/GeoJSON/map (the report still counts them)
        iri_psd_A, iri_psd_B: optional calibrated Eq.3 coefficients (a named,
            provenance-documented set); None -> the book values, unchanged
        ablate_orientation, ablate_segmentation_time, ablate_speed_gate:
            EXPERIMENTAL ablations for the base-vs-improved study, default off
            (output then byte-identical to a run without them). Each one
            switches a step of the method off - naive device-axis vertical,
            fixed time windows instead of 100 m segments, iri_multi outside the
            20-100 km/h range - and is recorded under 'ablations' in
            recording_meta.json and at the top of report.md
    """
    import numpy as np
    from pathlib import Path

    from road_quality_analyzer.io import load_sensor_csv
    from road_quality_analyzer.preprocessing import build_uniform_time_grid, build_distance_grid
    from road_quality_analyzer.filtering import apply_bandpass
    from road_quality_analyzer.orientation import (
        estimate_gravity, compute_rotation_matrix, transform_to_world,
        compute_gps_heading, naive_device_vertical
    )
    from road_quality_analyzer.anomaly import detect_threshold_anomalies, remove_distress_windows
    from road_quality_analyzer.segmentation import create_segments_dataframe
    from road_quality_analyzer.metrics.iri import (
        VehicleType, IRI_PSD_COEFFICIENTS, IRI_MULTI_COEFFICIENTS, IRI_MULTI_DEFAULT_PARAMS
    )

    g0 = 9.80665  # m/s^2

    # Pipeline parameters
    FS_MIN_HZ, FS_MAX_HZ = 5.0, 1000.0
    GRAVITY_TOLERANCE = 0.10
    GRAVITY_CUTOFF_HZ = 0.3
    BAND_LOW_HZ, BAND_HIGH_HZ = 0.5, 6.0
    HEADING_MIN_SPEED_MPS = 1.0
    # Edge trim, applied AFTER every filter has run on the full covered window.
    # Sized by the slowest filter in the chain - the GRAVITY_CUTOFF_HZ low-pass,
    # whose filtfilt start-up transient needs ~3 s to settle (the band-pass is faster).
    EDGE_TRIM_SEC = 3.0
    # filtfilt rejects a signal no longer than its padlen; the widest filter is the
    # 4th-order band-pass (order 8 -> len(b) = len(a) = 9 -> padlen = 3*9 = 27)
    FILTFILT_MIN_SAMPLES = 28
    ANOMALY_THRESHOLD_MS2 = 10.0
    DISTRESS_WINDOW_SEC = 0.5
    SEGMENT_LENGTH_M = 100.0
    DEFAULT_SCALAR_MODE = 'mean_psd_sqrt'
    # --ablate-segmentation-time: the median speed that sizes the windows is
    # taken over moving samples only
    TIME_WINDOW_MOVING_MIN_MPS = 1.0

    # Applied ablations: name -> details, filled as each switched-off step runs;
    # stays empty on a default run, so no artifact changes
    if ablate_speed_gate and low_speed_policy == 'ignore':
        # 'ignore' deletes exactly the low-speed segments the gate ablation gives
        # numbers to, while the report would claim they were computed
        raise ValueError("--ablate-speed-gate cannot be combined with "
                         "--low-speed-policy ignore")
    ablations = {}

    print("="*60)
    print("Road Quality Analyzer - Повний пайплайн")
    print("="*60)
    for flag, on in (('--ablate-orientation', ablate_orientation),
                     ('--ablate-segmentation-time', ablate_segmentation_time),
                     ('--ablate-speed-gate', ablate_speed_gate)):
        if on:
            print(f"⚠ ABLATION {flag}: експериментальний запуск, не вимірювання")

    # 1. Loading
    print(f"\n[1/9] Завантаження даних з {input_path}...")
    sensor_data = load_sensor_csv(input_path)
    print(f"  Accel samples: {len(sensor_data.accel_time)} (time unit: {sensor_data.time_unit})")
    if sensor_data.gps_time is not None:
        print(f"  GPS samples: {len(sensor_data.gps_time)}")

    from road_quality_analyzer.io import parse_recording_metadata, RecordingMetadata
    try:
        recording_meta = parse_recording_metadata(input_path)
    except Exception as exc:  # the comment layer must never fail the analysis
        recording_meta = RecordingMetadata()
        recording_meta.warnings.append(f"metadata parsing failed: {exc}")
    print(f"  Metadata: schema={recording_meta.schema}, "
          f"vehicle={'yes' if recording_meta.vehicle else 'no'}, "
          f"events={len(recording_meta.events)}, "
          f"{'clean stop' if recording_meta.clean_stop else 'truncated or pre-v2.1'}")

    # The passport selects the Eq.4/5/6 set for the additional iri_multi_vehicle
    # column; an empty passport resolves to the generic Eq.6 with book defaults
    from road_quality_analyzer.metrics.vehicle_params import resolve_vehicle_params
    vehicle_params = resolve_vehicle_params(recording_meta.vehicle)
    print(f"  Vehicle params: {vehicle_params.equation} {vehicle_params.params} "
          f"(provenance: {vehicle_params.provenance})")
    for warning in vehicle_params.warnings:
        print(f"  ⚠ {warning}")

    # 2. Uniform time grid
    print("\n[2/9] Побудова uniform time grid...")
    t_grid, ax_grid, ay_grid, az_grid = build_uniform_time_grid(
        sensor_data.accel_time,
        sensor_data.accel_x,
        sensor_data.accel_y,
        sensor_data.accel_z
    )
    dt = np.median(np.diff(t_grid))
    fs = 1.0 / dt
    if not FS_MIN_HZ <= fs <= FS_MAX_HZ:
        raise ValueError(
            f"Derived sampling rate {fs:.1f} Hz is outside the plausible band "
            f"{FS_MIN_HZ:.0f}-{FS_MAX_HZ:.0f} Hz (detected Time unit: "
            f"{sensor_data.time_unit}). Check the Time column of {input_path}."
        )
    print(f"  Time grid: {len(t_grid)} samples, fs={fs:.1f} Hz")

    # 3. Distance grid
    print("\n[3/9] Обчислення distance grid...")
    if sensor_data.gps_time is None:
        raise ValueError(
            f"No Location rows in {input_path}: distance-based analysis requires GPS. "
            "Re-record with location permission granted."
        )

    s_grid, v_grid = build_distance_grid(
        sensor_data.gps_time,
        sensor_data.gps_lat,
        sensor_data.gps_lon,
        t_grid
    )

    # Outside GPS coverage the distance is unknown (extrapolation would give negative s)
    covered = np.isfinite(s_grid) & np.isfinite(v_grid)
    n_outside_gps = int(np.sum(~covered))

    # The filters below run on the whole covered window; the edges they cannot be
    # trusted on are dropped afterwards (see the edge trim after step 6)
    trim_samples = int(round(EDGE_TRIM_SEC * fs))
    keep = slice(trim_samples, -trim_samples)
    n_covered = int(np.sum(covered))
    min_covered = max(2 * trim_samples + 2, FILTFILT_MIN_SAMPLES)
    if n_covered < min_covered:
        raise ValueError(
            f"Only {n_covered} samples fall inside the GPS time span; at least "
            f"{min_covered} are needed to run the filters (filtfilt padlen "
            f"{FILTFILT_MIN_SAMPLES - 1}) and still keep samples after trimming "
            f"{trim_samples} off each end."
        )

    t_grid, ax_grid, ay_grid, az_grid, s_grid, v_grid = (
        arr[covered]
        for arr in (t_grid, ax_grid, ay_grid, az_grid, s_grid, v_grid)
    )

    print(f"  Dropped outside GPS span: {n_outside_gps} samples")
    print(f"  Covered window: {n_covered} samples")

    # 4. Orientation correction
    print("\n[4/9] Orientation-correction (gravity alignment)...")
    g_hat_x, g_hat_y, g_hat_z = estimate_gravity(
        ax_grid, ay_grid, az_grid, fs, cutoff_hz=GRAVITY_CUTOFF_HZ
    )
    # The unit/fs sanity check judges the window that actually feeds the metrics:
    # the trimmed edges still carry the low-pass start-up transient
    g_magnitude = np.sqrt(g_hat_x**2 + g_hat_y**2 + g_hat_z**2)
    g_mean = float(np.mean(g_magnitude[keep]))
    if abs(g_mean - g0) > GRAVITY_TOLERANCE * g0:
        raise ValueError(
            f"Estimated gravity magnitude {g_mean:.3f} m/s^2 deviates more than "
            f"{GRAVITY_TOLERANCE*100:.0f}% from {g0} m/s^2 — accelerometer units "
            f"or the derived sampling rate (fs={fs:.1f} Hz) are inconsistent with "
            "the CSV contract, so gravity removal cannot be trusted."
        )
    print(f"  Gravity estimated (mean magnitude: {g_mean:.2f} m/s^2)")

    if ablate_orientation:
        # ABLATION: no rotation; the gravity estimate above still guards the
        # units/fs contract but does not shape the signal
        a_vertical, naive_axis, naive_axis_mean = naive_device_vertical(
            ax_grid, ay_grid, az_grid
        )
        # tilt of the mount against that axis, over the SAME window the ablation
        # used: the part of the vertical the naive axis cannot see is 1 - cos(tilt)
        axis_means = np.array([np.mean(ax_grid), np.mean(ay_grid), np.mean(az_grid)])
        ablations['orientation'] = {
            'vertical_axis': naive_axis,
            'axis_mean_ms2': naive_axis_mean,
            'tilt_deg': float(np.degrees(np.arccos(
                min(1.0, abs(naive_axis_mean) / float(np.linalg.norm(axis_means)))))),
        }
        print(f"  ⚠ ABLATION: device axis {naive_axis} as vertical "
              f"(axis mean {naive_axis_mean:.3f} m/s^2 removed), no rotation")
    else:
        R_matrices = compute_rotation_matrix(g_hat_x, g_hat_y, g_hat_z)
        print(f"  Rotation matrices computed")

        # Only the world-frame vertical feeds the metrics; the horizontal components
        # are not exported
        *_, a_vertical = transform_to_world(
            ax_grid, ay_grid, az_grid,
            g_hat_x, g_hat_y, g_hat_z,
            R_matrices
        )
    print(f"  Vertical acceleration: mean={np.mean(a_vertical):.3f} m/s^2, std={np.std(a_vertical):.3f} m/s^2)")

    # 5. Band-pass filtering (0.5-6 Hz) before metrics
    print(f"\n[5/9] Band-pass фільтр {BAND_LOW_HZ}-{BAND_HIGH_HZ} Hz...")
    a_vertical_g = apply_bandpass(a_vertical / g0, fs, BAND_LOW_HZ, BAND_HIGH_HZ)
    print(f"  Filtered vertical: std={np.std(a_vertical_g):.5f} g")

    # 6. GPS heading quality
    print("\n[6/9] GPS heading...")
    *_, heading_valid = compute_gps_heading(
        sensor_data.gps_time,
        sensor_data.gps_lat,
        sensor_data.gps_lon,
        t_grid,
        heading_min_speed_mps=HEADING_MIN_SPEED_MPS
    )

    # Edge trim: every filter has now run on the full covered window, so the
    # settling regions are cut once, from every derived array at the same time -
    # trimming the inputs first would only re-create the transients inside the
    # analysis window
    t_grid, s_grid, v_grid, a_vertical, a_vertical_g, heading_valid = (
        arr[keep]
        for arr in (t_grid, s_grid, v_grid, a_vertical, a_vertical_g, heading_valid)
    )
    n_heading_valid = int(np.sum(heading_valid))
    print(f"  Heading valid: {n_heading_valid} / {len(heading_valid)} samples")
    print(f"  Edge trim: {trim_samples} samples ({EDGE_TRIM_SEC:.0f} s) per side, after filtering")
    print(f"  Analysis window: {len(t_grid)} samples")
    print(f"  Total distance: {s_grid[-1] - s_grid[0]:.1f} m")
    print(f"  Mean speed: {v_grid.mean():.1f} m/s ({v_grid.mean()*3.6:.1f} km/h)")

    # 7. Anomaly detection + distress removal for PSD
    print(f"\n[7/9] Anomaly detection (threshold {ANOMALY_THRESHOLD_MS2:.0f} m/s^2)...")
    anomaly_mask = detect_threshold_anomalies(a_vertical, threshold_ms2=ANOMALY_THRESHOLD_MS2)
    n_anomalies = int(np.sum(anomaly_mask))
    print(f"  Anomalies detected: {n_anomalies} ({100*n_anomalies/len(anomaly_mask):.2f}%)")

    # Eq.3 is calibrated on a signal without major defects (B8)
    a_vertical_g_psd = remove_distress_windows(
        a_vertical_g, anomaly_mask, fs, window_sec=DISTRESS_WINDOW_SEC
    )
    n_masked = int(np.sum(~np.isfinite(a_vertical_g_psd)))
    print(f"  Distress removal: {n_masked} samples masked for PSD (±{DISTRESS_WINDOW_SEC} s)")

    # 8. Segmentation 100m
    time_window_samples = None
    if ablate_segmentation_time:
        # ABLATION: fixed time windows sized to 100 m at the recording's median
        # moving speed, so their spatial length varies with the speed
        moving = v_grid > TIME_WINDOW_MOVING_MIN_MPS
        if not np.any(moving):
            raise ValueError(
                f"--ablate-segmentation-time needs moving samples (v > "
                f"{TIME_WINDOW_MOVING_MIN_MPS} m/s) to size the time windows; "
                f"{input_path} has none in the analysis window."
            )
        median_moving_speed_mps = float(np.median(v_grid[moving]))
        time_window_samples = max(1, int(round(SEGMENT_LENGTH_M / median_moving_speed_mps * fs)))
        ablations['segmentation_time'] = {
            'window_s': time_window_samples / fs,
            'window_samples': time_window_samples,
            'median_moving_speed_mps': median_moving_speed_mps,
            'moving_min_speed_mps': TIME_WINDOW_MOVING_MIN_MPS,
        }
        print(f"\n[8/9] ⚠ ABLATION: часові вікна {time_window_samples / fs:.2f} с "
              f"({time_window_samples} samples) = {SEGMENT_LENGTH_M:.0f} м / "
              f"{median_moving_speed_mps:.2f} м/с...")
    else:
        print("\n[8/9] Сегментація по 100 м...")

    # Try different scalar modes for diagnostics
    scalar_modes = ['mean_psd_sqrt', 'band_power_sqrt', 'median_psd_sqrt', 'peak_psd_sqrt']
    segments_by_mode = {}

    for mode in scalar_modes:
        segments_by_mode[mode] = create_segments_dataframe(
            s_grid, a_vertical_g, a_vertical_g_psd, v_grid, fs, anomaly_mask,
            segment_length_m=SEGMENT_LENGTH_M, scalar_mode=mode,
            f_low=BAND_LOW_HZ, f_high=BAND_HIGH_HZ,
            low_speed_policy=low_speed_policy,
            iri_psd_A=iri_psd_A, iri_psd_B=iri_psd_B,
            vehicle_params=vehicle_params,
            time_window_samples=time_window_samples,
            speed_gate=not ablate_speed_gate
        )

    # Low-speed segments are captured before any exclusion: under the 'ignore'
    # policy their rows leave the artifacts, but the report still accounts for them
    all_segments_df = segments_by_mode[DEFAULT_SCALAR_MODE]
    if ablate_speed_gate:
        ablations['speed_gate'] = {
            'n_segments_outside_speed_valid': int((~all_segments_df['speed_valid']).sum())
            if len(all_segments_df) > 0 else 0,
        }
    low_speed_df = all_segments_df[all_segments_df['needs_class12_survey']]
    n_low_speed = len(low_speed_df)
    n_low_speed_excluded = n_low_speed if low_speed_policy == 'ignore' else 0

    if n_low_speed_excluded:
        segments_by_mode = {
            mode: df[~df['needs_class12_survey']]
            for mode, df in segments_by_mode.items()
        }

    segments_df = segments_by_mode[DEFAULT_SCALAR_MODE]

    # Partial segments (recording tail) are exported with a flag but excluded
    # from report means
    full_df = segments_df[~segments_df['partial']] if len(segments_df) > 0 else segments_df
    n_partial = len(segments_df) - len(full_df)

    print(f"  Segments created: {len(segments_df)} ({n_partial} partial, excluded from means)")
    print(f"  Low-speed (< {LOW_SPEED_MAX_KMH:.0f} km/h): {n_low_speed} "
          f"[policy: {low_speed_policy}"
          + (f", {n_low_speed_excluded} excluded from artifacts]" if n_low_speed_excluded
             else "]"))
    if len(full_df) > 0:
        print(f"  Mean IRI_psd_raw: {full_df['iri_psd_raw'].mean():.2f} m/km")
        print(f"  Mean IRI_psd (clipped): {full_df['iri_psd'].mean():.2f} m/km")
        print(f"  Mean IRI_multi: {full_df['iri_multi'].mean():.2f} m/km")

    # 9. Save results
    print(f"\n[9/9] Збереження результатів у {output_dir}...")
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Segment CSV
    segments_csv = output_path / "road_segments.csv"
    segments_df.to_csv(segments_csv, index=False)
    print(f"  ✓ {segments_csv}")

    # Recording metadata (structured feed for the web admin, Stage D)
    import dataclasses
    import json
    meta_json = output_path / "recording_meta.json"
    meta_payload = dataclasses.asdict(recording_meta)
    # VehicleType is an Enum: JSON gets its machine token (lev/dsd/generic)
    vehicle_params_payload = dataclasses.asdict(vehicle_params)
    vehicle_params_payload['vehicle_type'] = vehicle_params.vehicle_type.value
    meta_payload.update(source_file=str(input_path),
                        clean_stop=recording_meta.clean_stop,
                        vehicle_params=vehicle_params_payload)
    if ablations:
        meta_payload['ablations'] = ablations
    with open(meta_json, 'w', encoding='utf-8') as jf:
        json.dump(meta_payload, jf, ensure_ascii=False, indent=2)
    print(f"  ✓ {meta_json}")

    # GeoJSON artifacts
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
    print(f"  ✓ {plots_dir}/ (4 figures, PNG + PDF)")

    # Basic report
    report_path = output_path / "report.md"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# Road Quality Analysis Report\n\n")
        f.write(f"**Input:** {input_path}\n\n")
        f.write(f"**Date:** {Path(input_path).name}\n\n")

        # Ablations come first, so an ablated output cannot pass for a real one
        if ablations:
            f.write("## ⚠ ABLATION RUN — експериментальний запуск, не вимірювання\n\n")
            f.write("Крок(и) методу навмисно вимкнено для порівняння «базовий vs "
                    "покращений метод» на тих самих даних (`ablations` у "
                    "`recording_meta.json`). Числа цього запуску не є результатом "
                    "обстеження; описи вимкненого кроку нижче замінено.\n\n")
            if 'orientation' in ablations:
                orient = ablations['orientation']
                f.write(f"- `--ablate-orientation`: gravity alignment вимкнено — вертикаль = "
                        f"вісь пристрою `{orient['vertical_axis']}` (найбільше |середнє|, "
                        f"{orient['axis_mean_ms2']:.3f} m/s^2, віднято), без повороту у "
                        "світову систему координат\n")
            if 'segmentation_time' in ablations:
                seg_time = ablations['segmentation_time']
                f.write(f"- `--ablate-segmentation-time`: замість 100 м сегментів — часові "
                        f"вікна {seg_time['window_s']:.3f} s ({seg_time['window_samples']} "
                        f"samples) = {SEGMENT_LENGTH_M:.0f} m / медіанна швидкість руху "
                        f"{seg_time['median_moving_speed_mps']:.3f} m/s (v > "
                        f"{seg_time['moving_min_speed_mps']} m/s); просторова довжина вікна "
                        "(`length_m`) залежить від швидкості; `partial` = неповне "
                        "хвостове вікно\n")
            if 'speed_gate' in ablations:
                f.write("- `--ablate-speed-gate`: `iri_multi`, `iri_multi_vehicle`, "
                        "`iri_multi_raw` обчислено для всіх сегментів, також поза "
                        "20–100 km/h "
                        f"({ablations['speed_gate']['n_segments_outside_speed_valid']} "
                        "сегм.); `speed_valid`, `low_speed_class`, `needs_class12_survey` "
                        "мають справжні значення\n")
            f.write("\n")

        # Artifacts
        f.write("## Generated Artifacts\n\n")
        if ablate_segmentation_time:
            f.write("- `road_segments.csv` - метрики часових вікон (ABLATION) (CSV)\n")
        else:
            f.write("- `road_segments.csv` - метрики 100м сегментів (CSV)\n")
        f.write("- `recording_meta.json` - метадані запису: преамбула, профіль авто, "
                "події, футер (JSON)\n")
        f.write("- `roughness.geojson` - сегменти з геометрією та метриками (GeoJSON)\n")
        f.write("- `events.geojson` - аномалії як точки (GeoJSON)\n")
        f.write("- `segments_map.html` - інтерактивна карта сегментів (відкрийте в браузері)\n")
        f.write("- `plots/` - діагностичні графіки (PNG + PDF):\n")
        f.write("  - `speed_vs_distance`\n")
        f.write("  - `accel_vs_distance`\n")
        f.write("  - `metrics_vs_distance` (Grms + IRI_multi)\n")
        f.write("  - `iri_psd_vs_distance`\n\n")

        f.write("## Summary\n\n")
        f.write(f"- Total distance: {s_grid[-1] - s_grid[0]:.1f} m\n")
        f.write(f"- Mean speed: {v_grid.mean()*3.6:.1f} km/h\n")
        f.write(f"- Sampling rate: {fs:.1f} Hz\n")
        if ablate_segmentation_time:
            f.write(f"- Segments (ABLATION, {time_window_samples / fs:.3f} s time windows): "
                    f"{len(segments_df)} ({n_partial} partial, excluded from means)\n")
        else:
            f.write(f"- Segments (100m): {len(segments_df)} ({n_partial} partial, excluded from means)\n")
        f.write(f"- Anomalies: {n_anomalies}\n\n")

        # Recording metadata (Stage C): the CSV comment layer, v2.1/v3 contract
        def _pct(value):
            """Render a battery percent; the contract uses -1 for 'unavailable'."""
            if value is None or str(value) == '-1':
                return "недоступно"
            return f"{value}%"

        f.write("## Recording Metadata\n\n")
        if recording_meta.schema is None and not recording_meta.preamble:
            f.write("- Преамбули немає: файл записаний до контракту v2 або без неї\n")
        else:
            f.write(f"- Schema: {recording_meta.schema}\n")
            for key in ('device', 'app_version', 'nominal_rate_hz', 'anchor', 'units'):
                if key in recording_meta.preamble:
                    f.write(f"- {key}: {recording_meta.preamble[key]}\n")
            f.write(f"- Battery: {_pct(recording_meta.preamble.get('battery_start_pct'))}"
                    f" → {_pct((recording_meta.footer or {}).get('battery_end_pct'))}\n")
        if recording_meta.clean_stop:
            footer = recording_meta.footer
            f.write(f"- Зупинка: чиста (reason={footer.get('reason', '?')}), "
                    f"duration_ms={footer.get('duration_ms', '?')}\n")
            f.write(f"- Футер rows (queue-time, верхня межа): "
                    f"accel={footer.get('rows_accel')}, gyro={footer.get('rows_gyro')}, "
                    f"gps={footer.get('rows_gps')}; фактично розпарсено: "
                    f"accel={len(sensor_data.accel_time)}, "
                    f"gyro={0 if sensor_data.gyro_time is None else len(sensor_data.gyro_time)}, "
                    f"gps={0 if sensor_data.gps_time is None else len(sensor_data.gps_time)}\n")
        else:
            f.write("- Зупинка: футера `# end:` немає — запис обірваний або записаний "
                    "до контракту v2.1; файл валідний до останнього рядка, але "
                    "неповний\n")
        for warning in recording_meta.warnings:
            f.write(f"- ⚠ {warning}\n")

        f.write("\n## Vehicle Profile\n\n")
        if recording_meta.vehicle:
            f.write("| Параметр | Значення |\n|---|---|\n")
            for key, value in recording_meta.vehicle.items():
                f.write(f"| `{key}` | {value} |\n")
            f.write("\nПараметри профілю підставляються у рівняння Eq.4/5/6 "
                    "(колонка `iri_multi_vehicle`); опублікована колонка `iri_multi` "
                    "залишається узагальненим Eq.6 з книжковими номіналами, щоб обидві "
                    "оцінки можна було порівняти посегментно.\n")
        else:
            f.write("Немає блоку профілю (запис до v3 або без активного профілю): "
                    "`iri_multi_vehicle` збігається з `iri_multi` (Eq.6, номінали).\n")

        equation_label = {'eq4': 'Eq.4 (LEV)', 'eq5': 'Eq.5 (DSD)', 'eq6': 'Eq.6 (GENERIC)'}
        f.write(f"\n**Набір для `iri_multi_vehicle`:** "
                f"{equation_label[vehicle_params.equation]} — походження: "
                f"{vehicle_params.provenance['equation']}\n\n")
        f.write("| Параметр рівняння | Значення | Походження |\n|---|---|---|\n")
        for name, value in vehicle_params.params.items():
            f.write(f"| `{name}` | {value} | {vehicle_params.provenance[name]} |\n")
        for warning in vehicle_params.warnings:
            f.write(f"- ⚠ {warning}\n")

        f.write("\n## Recording Events\n\n")
        if recording_meta.events:
            from collections import Counter
            counts = Counter(e.type for e in recording_meta.events)
            f.write("| Тип | Кількість |\n|---|---|\n")
            for etype, count in sorted(counts.items()):
                f.write(f"| `{etype}` | {count} |\n")
            f.write(f"\n- Інцидентів (без `accuracy_changed`, як лічильник у "
                    f"застосунку): {recording_meta.incident_count}\n")
            if recording_meta.footer and 'events' in recording_meta.footer:
                f.write(f"- Футер events={recording_meta.footer['events']} "
                        f"(queue-time, верхня межа; розпарсено "
                        f"{len(recording_meta.events)})\n")
            f.write("\n| t, с від старту даних | Тип | Атрибути |\n|---|---|---|\n")
            for event in recording_meta.events[:50]:
                t_rel = ('?' if event.t_ms < 0 or sensor_data.t0_ms is None
                         else f"{(event.t_ms - sensor_data.t0_ms) / 1000.0:.1f}")
                attrs = ', '.join(f"{k}={v}" for k, v in event.attrs.items())
                f.write(f"| {t_rel} | `{event.type}` | {attrs} |\n")
            if len(recording_meta.events) > 50:
                f.write(f"\n…і ще {len(recording_meta.events) - 50} подій "
                        "(повний список у recording_meta.json)\n")
        else:
            f.write("Рядків `# event:` немає.\n")
        f.write("\n")

        # Data window (E)
        f.write("## Data Window\n\n")
        f.write(f"- Detected Time unit: {sensor_data.time_unit}\n")
        f.write(f"- Samples dropped outside GPS time span: {n_outside_gps}\n")
        f.write(f"- Edge trim: {trim_samples} samples ({EDGE_TRIM_SEC:.0f} s) per side, "
                "applied AFTER filtering\n")
        f.write(f"  (sized by the slowest filter in the chain, the {GRAVITY_CUTOFF_HZ} Hz "
                "gravity low-pass: trimming the filter input instead would leave each "
                "filtfilt start-up transient inside the analysis window)\n")
        f.write(f"- Samples used for metrics: {len(t_grid)}\n")
        f.write(f"- GPS heading valid (>= {HEADING_MIN_SPEED_MPS} m/s): "
                f"{n_heading_valid} / {len(heading_valid)} samples\n")
        f.write(f"- Samples masked for PSD by distress removal: {n_masked}\n\n")

        # Configuration
        f.write("## Configuration\n\n")
        f.write("Параметри аналізу:\n\n")
        f.write("**Segmentation:**\n")
        if ablate_segmentation_time:
            f.write(f"- ABLATION: fixed time windows of {time_window_samples} samples "
                    f"({time_window_samples / fs:.3f} s), NOT {SEGMENT_LENGTH_M:.0f} m "
                    "distance segments (B7)\n")
            f.write("- Window extent in metres (`s_start`/`s_end`/`length_m`) from the "
                    "cumulative distance grid\n")
            f.write("- Partial = the recording tail window (fewer samples than a full "
                    "window), flagged `partial=True` and excluded from means\n")
        else:
            f.write(f"- Segment length: {SEGMENT_LENGTH_M:.0f} m\n")
            f.write("- Method: cumulative distance grid (B7)\n")
            f.write("- Partial segments (< 90 m) flagged `partial=True` and excluded from means\n")
        if ablate_speed_gate:
            f.write("- Speed validity: 20-100 km/h (`speed_valid`); ABLATION: `iri_multi` "
                    "is computed outside it too.\n")
        else:
            f.write("- Speed validity: 20-100 km/h (`speed_valid`); `iri_multi` is NaN "
                    "outside it.\n")
        f.write("  Eq.3 has no speed term, so `iri_psd` is kept for every segment "
                "where Welch could run\n")
        f.write(f"- Low-speed policy (`--low-speed-policy`): `{low_speed_policy}` "
                f"— сегменти < {LOW_SPEED_MAX_KMH:.0f} км/год дістають "
                "`low_speed_class` і `needs_class12_survey`; "
                + ("ABLATION: `iri_multi` для них обчислено попри це\n\n" if ablate_speed_gate
                   else "`iri_multi` для них лишається NaN за будь-якої політики\n\n"))
        f.write("**Filtering:**\n")
        f.write(f"- Zero-phase Butterworth band-pass {BAND_LOW_HZ}-{BAND_HIGH_HZ} Hz (filtfilt)\n")
        if ablate_orientation:
            f.write("- Applied to the ABLATION vertical (device axis, mean removed, no "
                    "rotation) before Grms/PSD\n\n")
        else:
            f.write("- Applied to the gravity-removed world-frame vertical before Grms/PSD\n\n")
        f.write("**IRI_psd (Eq.3):**\n")
        f.write("- PSD method: Welch (scipy.signal.welch), only when n >= fs*2\n")
        f.write(f"- Frequency band: [{BAND_LOW_HZ}, {BAND_HIGH_HZ}] Hz (B4)\n")
        f.write(f"- Scalar mode: {DEFAULT_SCALAR_MODE} (sqrt of mean PSD density, g/sqrt(Hz))\n")
        if iri_psd_A is not None or iri_psd_B is not None:
            f.write("- Coefficients: CUSTOM calibrated set "
                    f"(A={iri_psd_A if iri_psd_A is not None else IRI_PSD_COEFFICIENTS['A_sqrt_psd']}, "
                    f"B={iri_psd_B if iri_psd_B is not None else IRI_PSD_COEFFICIENTS['B_const']}) "
                    "— книжкові значення в коді незмінні; провенанс набору див. у "
                    "документі калібрувального дослідження\n")
        else:
            f.write("- Coefficients (from `metrics/iri.py`, book values, not modified):\n")
            for name, value in IRI_PSD_COEFFICIENTS.items():
                f.write(f"  - {name} = {value}\n")
        f.write("\n")
        f.write("**IRI_multi (Eq.4/5/6):**\n")
        f.write(f"- Vehicle type: {VehicleType.GENERIC.name} (Eq.6)\n")
        f.write("- Coefficients (from `metrics/iri.py`, book values, not modified):\n")
        for name, value in IRI_MULTI_COEFFICIENTS[VehicleType.GENERIC].items():
            f.write(f"  - {name}: {value}\n")
        f.write("- Vehicle parameters (assumed, not measured): "
                f"{IRI_MULTI_DEFAULT_PARAMS}\n\n")
        f.write("**Anomaly Detection:**\n")
        f.write("- Method: threshold on |a_vertical| (B8)\n")
        if ablate_orientation:
            f.write("- Signal: ABLATION vertical (device axis, mean removed, no rotation)\n")
        else:
            f.write("- Signal: gravity-removed world-frame vertical acceleration "
                    "(NOT the raw accelerometer reading the guidebook thresholds)\n")
        f.write(f"- Threshold: {ANOMALY_THRESHOLD_MS2:.0f} m/s^2 "
                "(guidebook baseline, applied uncalibrated to this signal)\n")
        f.write(f"- Distress removal for PSD: ±{DISTRESS_WINDOW_SEC} s around each anomaly\n\n")
        f.write("**Orientation Correction:**\n")
        if ablate_orientation:
            f.write(f"- Gravity alignment: OFF (ABLATION) — device axis "
                    f"`{ablations['orientation']['vertical_axis']}`; the {GRAVITY_CUTOFF_HZ} Hz "
                    "gravity estimate only checks the units/fs contract\n")
        else:
            f.write(f"- Gravity alignment: lowpass filter {GRAVITY_CUTOFF_HZ} Hz (A3)\n")
        f.write(f"- GPS heading: minimum speed {HEADING_MIN_SPEED_MPS} m/s (A4)\n\n")

        # Sampling compliance (F)
        f.write("## Sampling Compliance\n\n")
        dx_grid = v_grid / fs
        dx_mean = np.mean(dx_grid)
        dx_p95 = np.percentile(dx_grid, 95)
        share_dx_le_03 = np.sum(dx_grid <= 0.3) / len(dx_grid) * 100

        f.write(f"- Median dt: {dt:.4f} s\n")
        f.write(f"- Mean dx: {dx_mean:.3f} m\n")
        f.write(f"- P95 dx: {dx_p95:.3f} m\n")
        f.write(f"- Share dx≤0.3m: {share_dx_le_03:.1f}%\n")
        f.write(f"- Per-segment share is exported as `dx_le_03_share`\n")
        f.write(f"- Recommended: dx≤0.3m, fs=80-120Hz\n")
        f.write(f"- Current fs: {fs:.1f} Hz {'✓' if 80 <= fs <= 120 else '⚠'}\n\n")

        if len(full_df) > 0:
            f.write("## IRI Statistics (full segments only, default: "
                    f"{DEFAULT_SCALAR_MODE} mode)\n\n")
            f.write(f"- Mean IRI_psd_raw: {full_df['iri_psd_raw'].mean():.2f} m/km\n")
            f.write(f"- Mean IRI_psd (clipped): {full_df['iri_psd'].mean():.2f} m/km\n")
            f.write(f"- Mean IRI_multi: {full_df['iri_multi'].mean():.2f} m/km\n")
            if ablate_speed_gate:
                f.write(f"- Segments with invalid survey speed (ABLATION: IRI_multi "
                        f"computed anyway): {int((~full_df['speed_valid']).sum())} / "
                        f"{len(full_df)}\n")
            else:
                f.write(f"- Segments with invalid survey speed (IRI_multi = NaN): "
                        f"{int((~full_df['speed_valid']).sum())} / {len(full_df)}\n")
            share_negative = float((full_df['iri_psd_raw'] < 0).mean()) * 100
            f.write(f"- Full segments with negative IRI_psd_raw: {share_negative:.1f}% "
                    "— негативний raw означає, що виміряна густина PSD нижча за поріг\n"
                    "  калібрування Eq.3 (сигнал некаліброваного пристрою), а не ідеальну дорогу\n\n")

            # PSD scalar diagnostic (D)
            f.write("## PSD Scalar Mode Diagnostic\n\n")
            f.write("Порівняння різних методів скаляризації PSD до sqrt(PSD) для Eq.3\n")
            f.write("(лише повні сегменти):\n\n")

            for mode in scalar_modes:
                df_mode = segments_by_mode[mode]
                df_mode = df_mode[~df_mode['partial']]
                f.write(f"### Mode: {mode}\n\n")
                f.write(f"- Mean IRI_psd_raw: {df_mode['iri_psd_raw'].mean():.2f} m/km\n")
                f.write(f"- Median IRI_psd_raw: {df_mode['iri_psd_raw'].median():.2f} m/km\n")
                f.write(f"- Mean IRI_psd (clipped): {df_mode['iri_psd'].mean():.2f} m/km\n")
                f.write(f"- % negative raw: {(df_mode['iri_psd_raw'] < 0).sum() / len(df_mode) * 100:.1f}%\n\n")

                # Top-5 segments for this mode
                top5 = df_mode.nlargest(5, 'iri_psd_raw')[['seg_id', 'iri_psd_raw', 'iri_psd', 'grms']]
                f.write("Top 5 segments (by iri_psd_raw):\n\n")
                f.write("| seg_id | iri_psd_raw | iri_psd | grms |\n")
                f.write("|--------|-------------|---------|------|\n")
                for _, row in top5.iterrows():
                    f.write(f"| {row['seg_id']} | {row['iri_psd_raw']:.2f} | {row['iri_psd']:.2f} | {row['grms']:.4f} |\n")
                f.write("\n")

            f.write(f"## Top 10 Worst Segments (by IRI_psd, {DEFAULT_SCALAR_MODE})\n\n")
            top10 = full_df.nlargest(10, 'iri_psd')[['seg_id', 's_start', 's_end', 'iri_psd_raw', 'iri_psd', 'iri_multi', 'grms']]
            f.write("| seg_id | s_start | s_end | iri_psd_raw | iri_psd | iri_multi | grms |\n")
            f.write("|--------|---------|-------|-------------|---------|-----------|------|\n")
            for _, row in top10.iterrows():
                f.write(f"| {row['seg_id']} | {row['s_start']:.1f} | {row['s_end']:.1f} | {row['iri_psd_raw']:.2f} | {row['iri_psd']:.2f} | {row['iri_multi']:.2f} | {row['grms']:.4f} |\n")

        # Low-speed segments (policy accounting)
        f.write(f"\n## Сегменти з низькою швидкістю (< {LOW_SPEED_MAX_KMH:.0f} км/год)\n\n")
        f.write(f"- Політика (`--low-speed-policy`): `{low_speed_policy}`\n")
        f.write(f"- Виявлено: {n_low_speed} з {len(all_segments_df)} сегментів\n")
        if n_low_speed_excluded:
            f.write(f"- Політика `ignore`: {n_low_speed_excluded} сегментів "
                    "виключено з `road_segments.csv`, `roughness.geojson` та карти; "
                    "у цьому звіті вони враховані повністю\n")
        f.write("\n")

        if n_low_speed > 0:
            f.write("| seg_id | length_m | mean_speed_kmh | events_per_km | low_speed_class |\n")
            f.write("|--------|----------|----------------|---------------|------------------|\n")
            for _, row in low_speed_df.iterrows():
                f.write(f"| {row['seg_id']} | {row['length_m']:.1f} | "
                        f"{row['mean_speed_kmh']:.1f} | {row['events_per_km']:.1f} | "
                        f"{row['low_speed_class']} |\n")
            f.write("\n")

            f.write("**Чому для цих сегментів не наводимо числовий IRI:**\n\n")
            f.write("- Частота збудження підвіски дорівнює швидкість / довжина хвилі "
                    f"нерівності. Нижче {LOW_SPEED_MAX_KMH:.0f} км/год вона падає під "
                    f"смугу {BAND_LOW_HZ}–{BAND_HIGH_HZ} Hz, у якій визначені Eq.3 та "
                    "Grms, тому дорожній сигнал просто виходить за межі вимірюваної смуги\n")
            f.write("- Eq.4/5/6 (`iri_multi`) містять speed-член і калібровані для "
                    "діапазону зйомки 20–100 км/год (опорні швидкості 30/50/80 км/год); "
                    "поза ним формула не визначена, тому `iri_multi` = NaN за будь-якої "
                    "політики — ставимо мітку, а не вигадуємо число\n")
            if ablate_speed_gate:
                f.write("- ⚠ ABLATION `--ablate-speed-gate`: у цьому запуску числовий "
                        "`iri_multi` для цих сегментів обчислено попри сказане вище — "
                        "лише для порівняння методів, не як оцінку стану\n")
            f.write("- Guidebook: запис зі швидкістю < 20 км/год вважається неповним "
                    "набором даних (incomplete dataset), робочий діапазон зйомки — "
                    "20–100 км/год\n\n")
            f.write("**Що це означає практично:** стійко низька швидкість — сама по собі "
                    "сильний індикатор стану (Eq.10/11: FFS/V50 vs IRI). Такі ділянки "
                    "позначені `needs_class12_survey = True`: **Потребує обстеження "
                    "профілометром (клас 1/2)** — лазерний профілометр, а не смартфон.\n")
            f.write("Пороговий детектор подій працює й на низькій швидкості, тому для цих "
                    "сегментів показником стану служить `events_per_km` (кількість "
                    "перевищень порогу на кілометр), а не IRI.\n\n")
        else:
            f.write("Сегментів із низькою швидкістю не виявлено — "
                    "`needs_class12_survey = False` для всіх сегментів.\n\n")

        # Assumptions & Limitations
        f.write("\n## Assumptions & Limitations\n\n")
        f.write("**IRI_psd (Eq.3) обмеження:**\n")
        f.write("- Використовує PSD вертикального прискорення, а не профіль дороги (як у книзі)\n")
        f.write(f"- Коефіцієнти A={IRI_PSD_COEFFICIENTS['A_sqrt_psd']}, "
                f"B={IRI_PSD_COEFFICIENTS['B_const']} калібровані для конкретних умов "
                "і можуть давати негативні значення на чистих даних\n")
        f.write("- Clipping до 0 застосовується для фінального IRI_psd (raw значення зберігаються для діагностики)\n\n")
        f.write("**Quarter-car IRI:**\n")
        f.write("- Класичний quarter-car IRI потребує профілю дороги та симуляції підвіски (як описано в книзі)\n")
        f.write("- Поточна реалізація використовує спрощені емпіричні формули (Eq.3, Eq.4/5/6)\n\n")
        f.write("**Anomaly threshold:**\n")
        f.write("- 10 м/с² застосовано до gravity-removed вертикального прискорення, тоді як\n")
        f.write("  guidebook задає поріг для сирого показу акселерометра; поріг не калібрований\n")
        f.write("  під цей пристрій, тому кількість подій може бути заниженою\n\n")
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

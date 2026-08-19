# Road Quality Analysis Report

**Input:** data\sensor_data_20250729_163334.csv

**Date:** sensor_data_20250729_163334.csv

## Generated Artifacts

- `road_segments.csv` - метрики 100м сегментів (CSV)
- `roughness.geojson` - сегменти з геометрією та метриками (GeoJSON)
- `events.geojson` - аномалії як точки (GeoJSON)
- `segments_map.html` - інтерактивна карта сегментів (відкрийте в браузері)
- `plots/` - діагностичні графіки (PNG):
  - `speed_vs_distance.png`
  - `accel_vs_distance.png`
  - `metrics_vs_distance.png` (Grms + IRI_multi)
  - `iri_psd_vs_distance.png`

## Summary

- Total distance: 15140.7 m
- Mean speed: 30.3 km/h
- Sampling rate: 52.6 Hz
- Segments (100m): 153
- Anomalies: 0

## Configuration

Параметри аналізу:

**Segmentation:**
- Segment length: 100 m
- Method: cumulative distance grid (B7)

**IRI_psd (Eq.3):**
- PSD method: Welch (scipy.signal.welch)
- Frequency band: [0.5, 6.0] Hz (B4)
- Scalar mode: band_power_sqrt (default)
- Coefficients: A=0.774, B=-0.825 (book values, not modified)

**IRI_multi (Eq.4/5/6):**
- Vehicle type: GENERIC (B5)
- Coefficients: a=1.63, b=63.3, c=1.0

**Anomaly Detection:**
- Method: threshold on |a_vertical| (B8)
- Threshold: 10 m/s^2 (book baseline)

**Orientation Correction:**
- Gravity alignment: lowpass filter 0.3 Hz (A3)
- GPS heading: minimum speed 1.0 m/s (A4)

## Sampling Compliance

- Median dt: 0.0190 s
- Mean dx: 0.160 m
- P95 dx: 0.342 m
- Share dx≤0.3m: 90.4%
- Recommended: dx≤0.3m, fs=80-120Hz
- Current fs: 52.6 Hz ⚠

## IRI Statistics (default: band_power_sqrt mode)

- Mean IRI_psd_raw: -0.79 m/km
- Mean IRI_psd (clipped): 0.00 m/km
- Mean IRI_multi: 3.78 m/km

## PSD Scalar Mode Diagnostic

Порівняння різних методів скаляризації PSD до sqrt(PSD) для Eq.3:

### Mode: band_power_sqrt

- Mean IRI_psd_raw: -0.79 m/km
- Median IRI_psd_raw: -0.79 m/km
- Mean IRI_psd (clipped): 0.00 m/km
- % negative raw: 99.3%

Top 5 segments (by iri_psd_raw):

| seg_id | iri_psd_raw | iri_psd | grms |
|--------|-------------|---------|------|
| 107.0 | -0.71 | 0.00 | 0.1081 |
| 98.0 | -0.72 | 0.00 | 0.1449 |
| 131.0 | -0.72 | 0.00 | 0.1303 |
| 99.0 | -0.73 | 0.00 | 0.1093 |
| 92.0 | -0.73 | 0.00 | 0.1261 |

### Mode: mean_psd_sqrt

- Mean IRI_psd_raw: -0.81 m/km
- Median IRI_psd_raw: -0.81 m/km
- Mean IRI_psd (clipped): 0.00 m/km
- % negative raw: 99.3%

Top 5 segments (by iri_psd_raw):

| seg_id | iri_psd_raw | iri_psd | grms |
|--------|-------------|---------|------|
| 107.0 | -0.78 | 0.00 | 0.1081 |
| 98.0 | -0.78 | 0.00 | 0.1449 |
| 131.0 | -0.78 | 0.00 | 0.1303 |
| 99.0 | -0.79 | 0.00 | 0.1093 |
| 92.0 | -0.79 | 0.00 | 0.1261 |

### Mode: median_psd_sqrt

- Mean IRI_psd_raw: -0.82 m/km
- Median IRI_psd_raw: -0.82 m/km
- Mean IRI_psd (clipped): 0.00 m/km
- % negative raw: 99.3%

Top 5 segments (by iri_psd_raw):

| seg_id | iri_psd_raw | iri_psd | grms |
|--------|-------------|---------|------|
| 0.0 | -0.80 | 0.00 | 0.1283 |
| 91.0 | -0.81 | 0.00 | 0.1094 |
| 92.0 | -0.81 | 0.00 | 0.1261 |
| 151.0 | -0.81 | 0.00 | 0.0960 |
| 11.0 | -0.81 | 0.00 | 0.1044 |

### Mode: peak_psd_sqrt

- Mean IRI_psd_raw: -0.79 m/km
- Median IRI_psd_raw: -0.79 m/km
- Mean IRI_psd (clipped): 0.00 m/km
- % negative raw: 99.3%

Top 5 segments (by iri_psd_raw):

| seg_id | iri_psd_raw | iri_psd | grms |
|--------|-------------|---------|------|
| 107.0 | -0.68 | 0.00 | 0.1081 |
| 131.0 | -0.69 | 0.00 | 0.1303 |
| 92.0 | -0.71 | 0.00 | 0.1261 |
| 98.0 | -0.71 | 0.00 | 0.1449 |
| 91.0 | -0.73 | 0.00 | 0.1094 |

## Top 10 Worst Segments (by IRI_psd, band_power_sqrt)

| seg_id | s_start | s_end | iri_psd_raw | iri_psd | iri_multi | grms |
|--------|---------|-------|-------------|---------|-----------|------|
| 0.0 | 0.1 | 99.9 | -0.77 | 0.00 | 7.67 | 0.1283 |
| 1.0 | 100.1 | 200.0 | -0.80 | 0.00 | 4.95 | 0.0777 |
| 2.0 | 200.2 | 299.9 | -0.78 | 0.00 | 4.98 | 0.0619 |
| 3.0 | 300.1 | 400.0 | -0.80 | 0.00 | 3.19 | 0.0400 |
| 4.0 | 400.2 | 499.9 | -0.77 | 0.00 | 5.29 | 0.0864 |
| 5.0 | 500.1 | 599.9 | -0.82 | 0.00 | 3.64 | 0.0141 |
| 6.0 | 600.0 | 699.8 | -0.80 | 0.00 | 3.97 | 0.0506 |
| 7.0 | 700.0 | 799.8 | -0.76 | 0.00 | 5.80 | 0.1064 |
| 8.0 | 800.1 | 899.9 | -0.75 | 0.00 | 6.35 | 0.1180 |
| 9.0 | 900.2 | 999.9 | -0.76 | 0.00 | 5.59 | 0.1025 |

## Assumptions & Limitations

**IRI_psd (Eq.3) обмеження:**
- Використовує PSD вертикального прискорення, а не профіль дороги (як у книзі)
- Коефіцієнти A=0.774, B=-0.825 калібровані для конкретних умов і можуть давати негативні значення на чистих даних
- Clipping до 0 застосовується для фінального IRI_psd (raw значення зберігаються для діагностики)

**Quarter-car IRI:**
- Класичний quarter-car IRI потребує профілю дороги та симуляції підвіски (як описано в книзі)
- Поточна реалізація використовує спрощені емпіричні формули (Eq.3, Eq.4/5/6)

**Wheel size:**
- Розмір колеса не входить у формули книги (згадується лише як метадані)
- Впливає на реальне сприйняття нерівностей, але не на розрахунок IRI в даній реалізації

**GPS дані:**
- GPS heading валідний лише при швидкості > 1.0 m/s
- Точність залежить від якості GPS сигналу (indoor/urban canyon можуть погіршити результати)


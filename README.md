# Road Quality Analyzer

Система аналізу якості дорожнього покриття на основі даних з сенсорів смартфона (акселерометр, GPS).

## Призначення

Проект призначений для оцінки стану доріг методом вимірювання вібрацій транспортного засобу через датчики смартфона. Результати відповідають міжнародному стандарту IRI (International Roughness Index).

## Quick Start

### 1. Встановлення

```bash
# Створити virtual environment
python -m venv .venv

# Активувати (Windows)
.venv\Scripts\activate

# Активувати (Linux/macOS)
source .venv/bin/activate

# Встановити залежності
pip install -r requirements.txt
```

### 2. Запуск аналізу

```bash
# Основна команда
python -m road_quality_analyzer analyze --input data/sensor_data_20250729_163334.csv --out results/my_analysis

# Або через main.py wrapper
python main.py --input data/sensor_data_20250729_163334.csv --out results/my_analysis
```

### 3. Результати

Після завершення аналізу у вказаній директорії будуть створені:

```
results/my_analysis/
├── road_segments.csv          # Метрики по 100м сегментах
├── roughness.geojson          # Сегменти з геометрією (GeoJSON)
├── events.geojson             # Виявлені аномалії (точки)
├── segments_map.html          # Інтерактивна карта (відкрити у браузері)
├── report.md                  # Технічний звіт
└── plots/                     # Діагностичні графіки (PNG)
    ├── speed_vs_distance.png
    ├── accel_vs_distance.png
    ├── metrics_vs_distance.png
    └── iri_psd_vs_distance.png
```

**Основні метрики:**
- **IRI (International Roughness Index)** - м/км (стандарт WorldBank/ASTM)
- **Grms** - RMS вертикального прискорення (gravity-corrected), g
- **Speed profile** - швидкість по дистанції, км/год
- **Anomalies** - виявлені дефекти/аномалії

## Формат вхідних даних

CSV файл з колонками (RoadSensorRecorder format):
```csv
Time,Type,X,Y,Z,Latitude,Longitude
1722272000123,Accelerometer,0.12,-0.45,9.78,,,
1722272000456,Location,,,,,50.4501,30.5234
1722272000789,Gyroscope,0.01,0.02,-0.01,,,
```

**Типи записів:**
- `Accelerometer` - прискорення (м/с²), колонки X,Y,Z
- `Location` - GPS координати, колонки Latitude,Longitude
- `Gyroscope` - кутова швидкість (рад/с), не обов'язково

## Outputs

### 1. road_segments.csv

Таблиця метрик для кожного 100м сегмента:

| Column | Description |
|--------|-------------|
| `seg_id` | ID сегмента (0, 1, 2, ...) |
| `s_start`, `s_end` | Початок/кінець сегмента (м) |
| `iri_psd` | IRI з PSD методу (м/км) |
| `iri_multi` | IRI з multivariable методу (м/км) |
| `grms` | RMS vertical acceleration (g) |
| `speed_median` | Медіанна швидкість (м/с) |

### 2. segments_map.html

Інтерактивна карта з кольоровим кодуванням за IRI:
- 🟢 Зелений: IRI < 2.5 (Відмінно)
- 🟡 Жовтий: 2.5 ≤ IRI < 4.0 (Добре)
- 🟠 Помаранчевий: 4.0 ≤ IRI < 6.0 (Задовільно)
- 🔴 Червоний: IRI ≥ 6.0 (Погано)

### 3. Графіки (plots/)

- **speed_vs_distance.png** - профіль швидкості
- **accel_vs_distance.png** - вертикальне прискорення
- **metrics_vs_distance.png** - Grms + IRI_multi по дистанції
- **iri_psd_vs_distance.png** - IRI_psd по дистанції

## Troubleshooting

### Проблема: ModuleNotFoundError

**Причина:** Не встановлені залежності або не активовано virtual environment

**Рішення:**
```bash
# Активувати venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/macOS

# Перевстановити залежності
pip install -r requirements.txt
```

### Проблема: Негативні значення IRI_psd

**Причина:** PSD-based метод може давати негативні значення на чистих даних (формула використовує емпіричні коефіцієнти)

**Рішення:** Використовуйте IRI_multi замість IRI_psd - він завжди позитивний і краще відповідає стандартам

### Проблема: Мало GPS даних

**Причина:** GPS сигнал був недоступний (indoor, тунель, urban canyon)

**Результат:** Сегменти без GPS будуть мати `valid_gps_ratio < 0.5` і можуть бути виключені з аналізу

**Рішення:** Повторити збір даних на відкритій місцевості

## Технічні деталі

- **Sampling rate:** ~50 Hz (рекомендовано 80-120 Hz для dx≤0.3м)
- **GPS frequency:** 1-5 Hz (залежить від пристрою)
- **Gravity correction:** Lowpass filter 0.3 Hz
- **Anomaly detection:** Threshold 10 m/s² (baseline)
- **Segmentation:** 100m distance-based bins

## Залежності

- Python 3.8+
- numpy >= 2.3
- pandas >= 2.3
- scipy >= 1.16 (Welch PSD, Butterworth filter)
- matplotlib >= 3.10 (plots)
- folium >= 0.20 (interactive maps)

## Документація

Детальна документація у папці `docs/`:
- [User Guide](docs/08_user_guide_and_cli_reference.md) - повний посібник користувача
- [Technical Parameters](docs/TECHNICAL_PARAMETERS.md) - параметри та формули
- [Research Results](docs/RESEARCH_RESULTS.md) - результати досліджень

## Ліцензія

Проект розроблено для наукових цілей та досліджень якості дорожнього покриття.

**Версія:** 2.0  
**Дата оновлення:** Січень 2026

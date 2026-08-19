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

# Встановити залежності (встановлює пакет analyzer у editable-режимі)
pip install -r requirements.txt

# Еквівалент напряму (без pytest):
pip install -e ./analyzer
```

Пакет `road_quality_analyzer` живе в `analyzer/src/` (src-layout), тому
editable-встановлення обов'язкове — саме воно робить імпорти й CLI доступними
з будь-якої робочої директорії.

### 2. Запуск аналізу

```bash
# Основна команда
python -m road_quality_analyzer analyze --input storage/data/sensor_data_20250729_163334.csv --out storage/results/my_analysis

# Або через main.py wrapper
python main.py --input storage/data/sensor_data_20250729_163334.csv --out storage/results/my_analysis
```

**Опція `--low-speed-policy`** — що робити із сегментами, пройденими повільніше
за 20 км/год (дорога настільки погана, що швидше фізично не проїхати):

| Значення | Поведінка |
|----------|-----------|
| `very-poor` | мітка `low_speed_class = very_poor` |
| `poor` | мітка `low_speed_class = poor` |
| `invalid` | мітка `low_speed_class = invalid` (за замовчуванням) |
| `ignore` | рядки сегментів виключено з CSV, GeoJSON і карти; у `report.md` вони враховані |

За будь-якої політики `iri_multi` для таких сегментів лишається `NaN` — ставимо
мітку, а не вигадуємо число (Eq.4/5/6 не визначені поза 20–100 км/год).

```bash
python -m road_quality_analyzer analyze --input storage/data/drive.csv --out storage/results/run --low-speed-policy poor
```

### 3. Результати

Після завершення аналізу у вказаній директорії будуть створені:

```
storage/results/my_analysis/
├── road_segments.csv          # Метрики по 100м сегментах
├── roughness.geojson          # Сегменти з геометрією (GeoJSON)
├── events.geojson             # Виявлені аномалії (точки)
├── segments_map.html          # Інтерактивна карта (відкрити у браузері)
├── report.md                  # Технічний звіт
└── plots/                     # Діагностичні графіки (PNG + PDF)
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
# schema=2
# units: accel=m/s^2 (includes gravity), gyro=rad/s, latlon=deg WGS84, time=ms epoch anchored monotonic
Time,Type,X,Y,Z,Latitude,Longitude
1722272000123,Accelerometer,0.12,-0.45,9.78,,
1722272000456,Location,,,,50.4501,30.5234
1722272000789,Gyroscope,0.01,0.02,-0.01,,
```

Рядки, що починаються з `#`, — необов'язкова metadata-преамбула (контракт v2),
вона пропускається під час читання. Заголовок має точно збігатися з наведеним,
інакше завантаження падає з помилкою.

**Типи записів:**
- `Accelerometer` - прискорення (м/с²), колонки X,Y,Z
- `Location` - GPS координати, колонки Latitude,Longitude
- `Gyroscope` - кутова швидкість (рад/с), не обов'язково

## Outputs

### 1. road_segments.csv

Таблиця метрик для кожного 100м сегмента (24 колонки). Нижче — основні;
шість діагностичних колонок PSD (`psd_band_power`, `psd_sqrt_scalar`,
`psd_scalar_mode`, `psd_n_samples_used`, `psd_df_hz`, `fs_used_hz`) описані
у [User Guide](docs/08_user_guide_and_cli_reference.md):

| Column | Description |
|--------|-------------|
| `seg_id` | ID сегмента (0, 1, 2, ...) |
| `s_start`, `s_end` | Початок/кінець сегмента (м) |
| `length_m` | Фактична довжина сегмента (м) |
| `partial` | `True` для сегмента < 90 м — виключений із середніх звіту |
| `n_samples` | Кількість семплів у сегменті |
| `mean_speed_mps`, `mean_speed_kmh` | Середня швидкість |
| `speed_valid` | Швидкість у діапазоні зйомки 20–100 км/год |
| `low_speed_class` | Мітка сегмента < 20 км/год за політикою `--low-speed-policy` (`normal` для решти) |
| `needs_class12_survey` | `True` для сегментів < 20 км/год — потрібне обстеження профілометром (клас 1/2) |
| `dx_le_03_share` | Частка семплів із просторовим кроком dx ≤ 0.3 м |
| `grms` | RMS vertical acceleration (g) |
| `iri_psd_raw`, `iri_psd` | IRI з PSD методу: сире та clipped (м/км) |
| `iri_multi` | IRI з multivariable методу (м/км) |
| `anomaly_count` | Кількість перевищень порогу 10 м/с² |
| `events_per_km` | Кількість подій на кілометр (`anomaly_count` / довжина сегмента) |

`iri_multi` дорівнює `NaN`, якщо `speed_valid = False` (Eq.4/5/6 мають speed-член
і не калібровані поза 20–100 км/год). `iri_psd` (Eq.3) speed-члена не має, тому
не залежить від `speed_valid`; він `NaN` лише коли PSD неможливо обчислити
(< 2 с даних) — вигаданих значень не записуємо.

Для сегментів із `needs_class12_survey = True` показником стану служить
`events_per_km` (пороговий детектор працює й на низькій швидкості), а не IRI.

### 2. segments_map.html

Інтерактивна карта з кольоровим кодуванням за IRI (покращена візуалізація з v2):
- 🟢 Зелений: найкращий стан (низький IRI)
- 🔵 Синій: середня якість
- 🟠 Помаранчевий: погана якість
- 🔴 Червоний: найгірший стан (високий IRI)
- 🟣 Пурпуровий (#FF00FF), товстіша лінія: сегмент < 20 км/год — IRI не рахуємо,
  у легенді «Потребує обстеження профілометром (клас 1/2)». Легенда з'являється
  лише тоді, коли такі сегменти є на карті

**Покращення візуалізації:**
- Товсті лінії з чорною обводкою (halo effect) — видно на будь-якому фоні
- Насичені контрастні кольори замість блідої палітри

### 3. Графіки (plots/)

Кожен графік зберігається у двох форматах: `.png` (перегляд) та `.pdf`
(вектор, стиль SciencePlots — для тексту дисертації).

- **speed_vs_distance** - профіль швидкості
- **accel_vs_distance** - вертикальне прискорення
- **metrics_vs_distance** - Grms + IRI_multi по дистанції
- **iri_psd_vs_distance** - IRI_psd по дистанції

## Troubleshooting

### Проблема: ModuleNotFoundError

**Причина:** Не встановлені залежності або не активовано virtual environment

**Рішення:**
```bash
# Активувати venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/macOS

# Перевстановити залежності (разом з editable-пакетом analyzer)
pip install -r requirements.txt
```

### Проблема: Негативні значення IRI_psd

**Причина:** PSD-based метод може давати негативні значення на чистих даних (формула використовує емпіричні коефіцієнти)

**Рішення:** Використовуйте IRI_multi замість IRI_psd - він завжди позитивний і краще відповідає стандартам

### Проблема: Мало GPS даних

**Причина:** GPS сигнал був недоступний (indoor, тунель, urban canyon)

**Результат:** Аналіз падає з помилкою `No Location rows ...` — без GPS
відстань і швидкість невідомі, а вигадувати їх не можна. Семпли поза часовим
діапазоном GPS відкидаються, а неповні сегменти позначаються `partial=True`.

**Рішення:** Повторити збір даних на відкритій місцевості

## Технічні деталі

- **Sampling rate:** рекордер запитує 100 Hz (`SAMPLING_PERIOD_US = 10000`); фактична
  частота плаває, тому пайплайн виводить `fs` з `median(diff(t))`. Датасет
  `storage/data/sensor_data_20250729_163334.csv` записаний старішою версією застосунку і дає
  fs ≈ 52.6 Hz. Рекомендація для dx ≤ 0.3 м — 80–120 Hz
- **GPS frequency:** 1 Hz (`LocationRequest` interval 1000 мс, min 500 мс)
- **Gravity correction:** Lowpass Butterworth 4-го порядку, cutoff 0.3 Hz
- **Band-pass перед метриками:** 0.5–6.0 Hz (zero-phase `filtfilt`)
- **Anomaly detection:** Threshold 10 m/s² на gravity-removed вертикалі (baseline)
- **Segmentation:** 100m distance-based bins

## Тести

```bash
.venv\Scripts\python.exe -m pytest analyzer/tests -q
# 163 passed (11 файлів у analyzer/tests/, ~23 с)
```

Синтетичні CSV для тестів генерує `analyzer/tests/conftest.py::write_drive_csv`; реальний
11-мегабайтний запис у тестах не використовується. Seed зафіксовано
(`np.random.default_rng(20260101)` у фікстурі `rng`).

## Залежності

- Python 3.11+ (вимога numpy >= 2.3)
- numpy >= 2.3
- pandas >= 2.3
- scipy >= 1.16 (Welch PSD, Butterworth filter)
- matplotlib >= 3.10 (plots)
- scienceplots >= 2.1 (стиль публікаційних графіків)
- folium >= 0.20 (interactive maps)

## Документація

Детальна документація у папці `docs/`:
- [Індекс](docs/00_index.md) - навігація по розділах 00-09
- [User Guide](docs/08_user_guide_and_cli_reference.md) - повний посібник користувача
- [Methods (new pipeline)](docs/02_methods_new_pipeline.md) - параметри, формули, псевдокод
- [Results](docs/05_results_legacy_vs_new.md) - числові результати

**Історичні документи** (описують видалений пайплайн `modules/` версії 2.0 і не
відповідають поточному коду — тримати лише як довідку):
- [Technical Parameters](docs/TECHNICAL_PARAMETERS.md) - параметри пайплайну 2.0
- [Research Results](docs/RESEARCH_RESULTS.md) - результати пайплайну 2.0

## Ліцензія

Проект розроблено для наукових цілей та досліджень якості дорожнього покриття.

**Версія:** 2.0  
**Дата оновлення:** Січень 2026

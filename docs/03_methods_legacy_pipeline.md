# 03 — Методи legacy пайплайну

## Зміст
1. [Загальна архітектура legacy](#загальна-архітектура-legacy)
2. [Крок 1: Завантаження та злиття потоків](#крок-1-завантаження-та-злиття-потоків)
3. [Крок 2: Калібрування акселерометра (rolling mean)](#крок-2-калібрування-акселерометра)
4. [Крок 3: RMSA метрика (body-frame)](#крок-3-rmsa-метрика)
5. [Крок 4: Peak detection](#крок-4-peak-detection)
6. [Крок 5: Time-based сегментація](#крок-5-time-based-сегментація)
7. [Крок 6: Класифікація та візуалізація](#крок-6-класифікація-та-візуалізація)
8. [Чому RMSA "вищий": gravity contamination](#чому-rmsa-вищий)
9. [Еволюція підходу (без дискредитації)](#еволюція-підходу)

---

## Загальна архітектура legacy

**Місцезнаходження:** `modules/` (4 файли)

```
modules/
├── io_utils.py         — Завантаження CSV
├── preprocessing.py    — Калібрування, фільтри
├── analysis.py         — RMSA, peaks, класифікація
└── visualization.py    — Folium maps, plots
```

**Точка входу:** `main.py` (без `--use-new-pipeline` flag)

```
                ┌─────────────────┐
                │  sensor CSV     │
                └────────┬────────┘
                         ↓
                ┌────────────────────┐
            (1) │  io_utils.py       │  read_csv + ffill/bfill
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
            (2) │ preprocessing.py   │  calibrate_accelerometer (rolling mean)
                │                    │  apply_highpass_filter (0.5 Hz)
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
            (3) │ analysis.py        │  compute_rmsa (body-frame)
                │                    │  detect_peaks (threshold)
                │                    │  classify_road_quality
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
            (4) │ segmentation       │  Time-based groups (кожні 10 секунд)
                │ (в analysis.py)    │  Aggregate RMSA per segment
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
            (5) │ visualization.py   │  Folium map, plots (RMSA, peaks)
                └────────────────────┘
```

**Ключова особливість:** body-frame обробка (без orientation correction)

---

## Крок 1: Завантаження та злиття потоків

**Файл:** `modules/io_utils.py` (у legacy версії цей функціонал в preprocessing.py)

### Код (спрощено)

```python
def preprocess_data(df):
    # 1. Перетворення Time
    if pd.api.types.is_numeric_dtype(df['Time']):
        df['Time'] = pd.to_datetime(df['Time'], unit='ms', utc=True)
    
    # 2. Створення окремих колонок для потоків акселерометра і локації
    df_filtered = df.copy()
    df_filtered['accel_x'] = np.where(df_filtered['Type'] == 'Accelerometer', 
                                       df_filtered['X'], np.nan)
    df_filtered['accel_y'] = np.where(df_filtered['Type'] == 'Accelerometer', 
                                       df_filtered['Y'], np.nan)
    df_filtered['accel_z'] = np.where(df_filtered['Type'] == 'Accelerometer', 
                                       df_filtered['Z'], np.nan)
    
    # 3. ❌ ПРОБЛЕМА: ffill/bfill для заповнення NaN
    df_filtered = df_filtered.ffill().bfill()
    
    return df_filtered
```

### Проблема: ffill/bfill

> У схемах нижче `ACCEL` / `GPS` — скорочення для читабельності. У самому CSV
> значення `Type` завжди були `Accelerometer` / `Gyroscope` / `Location`
> (див. [08](08_user_guide_and_cli_reference.md)).

**Forward fill (ffill):**
```
Before:
Time    Type    accel_x  gps_lat
100     ACCEL   0.5      NaN
101     GPS     NaN      50.45
102     ACCEL   0.6      NaN

After ffill:
Time    Type    accel_x  gps_lat
100     ACCEL   0.5      NaN       (no previous GPS)
101     GPS     NaN      50.45
102     ACCEL   0.6      50.45     ← propagated from t=101
```

**Backward fill (bfill):**
```
After ffill+bfill:
Time    Type    accel_x  gps_lat
100     ACCEL   0.5      50.45     ← propagated from FUTURE (t=101)
101     GPS     NaN      50.45
102     ACCEL   0.6      50.45
```

**Наслідки:**
- **Non-causal:** використання майбутніх GPS координат для минулих ACCEL samples
- **Неточна прив'язка:** GPS "розмазується" на всі ACCEL rows, навіть якщо насправді phone змінив позицію
- **Spatial aliasing:** 1 GPS точка (1 Hz) прив'язується до 50-100 ACCEL точок (50 Hz) → втрата роздільної здатності

**Порівняння з новим пайплайном:**
- New: linear interpolation GPS на uniform grid → фізично коректна інтерполяція
- Legacy: ffill/bfill → простіша реалізація, але lower accuracy

---

## Крок 2: Калібрування акселерометра

**Файл:** `modules/preprocessing.py`

**Функція:** `calibrate_accelerometer(accel_x, accel_y, accel_z)`

### Код

```python
def calibrate_accelerometer(accel_x, accel_y, accel_z):
    """
    Калібрування акселерометра з компенсацією гравітації.
    Віднімає гравітаційний вектор для отримання чистих вібрацій.
    """
    # Обчислюємо середній вектор гравітації (припускаємо горизонтальний пристрій)
    gravity_x = accel_x.rolling(window=50, center=True, min_periods=1).mean()
    gravity_y = accel_y.rolling(window=50, center=True, min_periods=1).mean()
    gravity_z = accel_z.rolling(window=50, center=True, min_periods=1).mean()
    
    # Віднімаємо гравітацію
    linear_accel_x = accel_x - gravity_x
    linear_accel_y = accel_y - gravity_y
    linear_accel_z = accel_z - gravity_z
    
    return linear_accel_x, linear_accel_y, linear_accel_z
```

### Аналіз підходу

**Ідея:** rolling mean (50 samples ≈ 1 секунда при fs=50 Hz) оцінює gravity

**Проблема 1: Body-frame залишається**
```
a_raw = [ax, ay, az]  (phone body frame)

Rolling mean видаляє AC component, але НЕ обертає вісі до world frame:
- Якщо phone під кутом 10°, gravity_z ≈ 9.8*cos(10°) = 9.66 m/s²
- linear_accel_z = az - gravity_z ≈ road vibrations + residual gravity noise
```

**Проблема 2: Window size trade-off**
```
window=50 samples @ fs=50 Hz → 1 second

Якщо phone обертається швидше (наприклад, поворот за 0.5 сек):
→ rolling mean "розмиває" gravity через кілька орієнтацій
→ linear_accel містить gravity artifacts
```

**Порівняння з новим пайплайном:**
- **Legacy:** rolling mean (body-frame) → залишається gravity contamination
- **New:** low-pass filter (0.25 Hz) + quaternion rotation до world frame → повне видалення gravity

**Чому legacy все одно "працює":**
- Для **відносних порівнянь** (segment A vs segment B на тому ж проїзді) contamination однакова
- RMSA **корелює** з roughness, навіть якщо absolute value завищений
- **Validation:** Spearman ρ = 0.942 (Grms vs legacy RMSA) → сильна кореляція

---

## Крок 3: RMSA метрика

**Файл:** `modules/analysis.py`

**Функція:** `compute_rmsa(df, accel_x_series, accel_y_series, accel_z_series, window_size=10)`

### Формула

**3D RMSA (Root Mean Square Acceleration):**
```
RMSA = sqrt(RMS_x² + RMS_y² + RMS_z²)

де:
RMS_x = sqrt(mean(a_x²))
RMS_y = sqrt(mean(a_y²))
RMS_z = sqrt(mean(a_z²))
```

### Код

```python
def compute_rmsa(df, accel_x_series, accel_y_series, accel_z_series, window_size=10):
    # 1. Заповнення пропусків
    x_filled = accel_x_series.ffill().bfill().fillna(0)
    y_filled = accel_y_series.ffill().bfill().fillna(0)
    z_filled = accel_z_series.ffill().bfill().fillna(0)
    
    # 2. Згладжування Савіцького-Голея
    x_filtered = savgol_filter(x_filled, window_length=11, polyorder=2)
    y_filtered = savgol_filter(y_filled, window_length=11, polyorder=2)
    z_filtered = savgol_filter(z_filled, window_length=11, polyorder=2)
    
    # 3. Центрування (видалення DC component)
    x = x_filtered - np.mean(x_filtered)
    y = y_filtered - np.mean(y_filtered)
    z = z_filtered - np.mean(z_filtered)
    
    # 4. Rolling RMS для кожної осі
    rms_x = pd.Series(x).rolling(window=window_size, center=True).apply(
        lambda vals: np.sqrt(np.mean(vals**2))
    )
    rms_y = pd.Series(y).rolling(window=window_size, center=True).apply(
        lambda vals: np.sqrt(np.mean(vals**2))
    )
    rms_z = pd.Series(z).rolling(window=window_size, center=True).apply(
        lambda vals: np.sqrt(np.mean(vals**2))
    )
    
    # 5. 3D RMSA
    rmsa = np.sqrt(rms_x**2 + rms_y**2 + rms_z**2)
    
    return rmsa
```

### Одиниці виміру

**Проблема одиниць у legacy:**
```python
# У коді немає явної конвертації м/с² → g
# a_x, a_y, a_z — в м/с² (з CSV)
# RMSA — також в м/с²

# Але в класифікації використовуються пороги як для g:
def classify_road_quality(rmsa_value):
    if rmsa_value < 0.5:  # ← це м/с² чи g?
        return ('Відмінно', 'green')
    elif rmsa_value < 1.0:
        return ('Добре', 'lightgreen')
    ...
```

**Наш датасет:**
- Legacy RMSA mean = 0.3335 (м/с², але інтерпретується як proxy для g)
- New Grms mean = 0.0590 g (явно в g, після g0 = 9.80665 m/s² division)

**Співвідношення:**
```
0.3335 м/с² / 9.8 ≈ 0.034 g  (якщо інтерпретувати як pure linear accel)

Але фактично 0.3335 ~ 5.6x більше за 0.0590 g:
0.3335 / 0.0590 ≈ 5.65

→ RMSA містить gravity contamination
```

---

## Крок 4: Peak detection

**Файл:** `modules/analysis.py`

**Функція:** `detect_peaks(accel_z_series, threshold)`

### Код

```python
from scipy.signal import find_peaks

def detect_peaks(accel_z_series, threshold):
    """
    Виявляє піки прискорення (potholes, bumps).
    
    Використовує scipy.signal.find_peaks з:
    - height: мінімальна висота піку
    - distance: мінімальна відстань між піками
    """
    # Заповнення NaN
    data = accel_z_series.fillna(0).values
    
    # Find peaks
    peaks, properties = find_peaks(
        np.abs(data),  # Абсолютне значення (+ і - піки)
        height=threshold,
        distance=10  # Мінімум 10 samples (~0.2 сек) між піками
    )
    
    return peaks, properties
```

### Параметри

**Threshold:** динамічний (обчислюється як `mean + 2*std`)

```python
threshold = accel_z_cal.mean() + 2 * accel_z_cal.std()
```

**Приклад:**
```
accel_z_cal:
mean = 0.15 м/с²
std = 0.42 м/с²

threshold = 0.15 + 2*0.42 = 0.99 м/с²
```

**Результат на нашому датасеті:**
- **7177 peaks detected** (legacy)
- **0 anomalies** (new, threshold = 10 m/s²)

**Різниця підходів:**
- **Legacy peaks:** statistical outliers (> mean+2σ) → багато false positives (engine vibrations, phone движения)
- **New anomalies:** absolute threshold (10 m/s²) → тільки справжні distresses (potholes, speed bumps)

---

## Крок 5: Time-based сегментація

**Файл:** `modules/analysis.py` (в функції `analyze_route_segments`)

### Алгоритм

```python
def analyze_route_segments(df, rmsa, segment_duration_sec=10):
    """
    Розбиває маршрут на сегменти за часом.
    
    Параметри:
    - segment_duration_sec: тривалість сегмента (секунди)
    
    Повертає:
    - DataFrame з сегментами (avg_latitude, avg_longitude, avg_rmsa, quality)
    """
    # 1. Створити groups за часом
    df['segment'] = (df.index / (segment_duration_sec * fs)).astype(int)
    
    # 2. Aggregate по сегментах
    segments = []
    
    for seg_id, group in df.groupby('segment'):
        # GPS coordinates (mean)
        avg_lat = group['gps_lat'].mean()
        avg_lon = group['gps_lon'].mean()
        
        # RMSA (mean)
        avg_rmsa = rmsa[group.index].mean()
        
        # Classify
        quality, color = classify_road_quality(avg_rmsa)
        
        segments.append({
            'segment': seg_id,
            'avg_latitude': avg_lat,
            'avg_longitude': avg_lon,
            'avg_rmsa': avg_rmsa,
            'quality': quality,
            'color': color
        })
    
    return pd.DataFrame(segments)
```

### Проблема time-based segments

**Сценарій 1: Highway (швидка дорога, 80 km/h = 22.2 m/s)**
```
10 сек → 222 м відстані
→ Сегмент дуже довгий, low spatial resolution
```

**Сценарій 2: City traffic (повільна дорога, 20 km/h = 5.6 m/s)**
```
10 сек → 56 м відстані
→ Сегмент короткий, high spatial resolution
```

**Наслідки:**
- Неможливо порівнювати сегменти (різна довжина)
- Bias до швидких ділянок (більша вага в overall statistics)
- Порушення spatial consistency

**Наш датасет:**
- **1799 time-based segments** (variable length 10-300 м)
- Середня швидкість 41.7 km/h → 10 сек ≈ 116 м
- Але variance дуже велика (stop-and-go)

**Порівняння з новим пайплайном:**
- **Legacy:** 1799 segments (time-based, variable length)
- **New:** 152 segments (distance-based, 100 м; 2 позначені `partial`)
- **100m-aligned:** 152 overlap segments для validation

---

## Крок 6: Класифікація та візуалізація

**Файл:** `modules/analysis.py`, `modules/visualization.py`

### Класифікація

```python
def classify_road_quality(rmsa_value):
    """
    Шкала відповідає приблизно IRI (International Roughness Index):
    - Відмінно: RMSA < 0.5 м/с² (IRI < 2 м/км)
    - Добре: 0.5 ≤ RMSA < 1.0 м/с² (IRI 2-4 м/км)
    - Задовільно: 1.0 ≤ RMSA < 2.0 м/с² (IRI 4-8 м/км)
    - Погано: RMSA ≥ 2.0 м/с² (IRI > 8 м/км)
    """
    if pd.isna(rmsa_value):
        return ('Невідомо', 'gray')
    elif rmsa_value < 0.5:
        return ('Відмінно', 'green')
    elif rmsa_value < 1.0:
        return ('Добре', 'lightgreen')
    elif rmsa_value < 2.0:
        return ('Задовільно', 'orange')
    else:
        return ('Погано', 'red')
```

**Наш датасет:**
```
RMSA mean = 0.3335 → класифікація "Відмінно"
IRI_multi = 3.78 m/km → класифікація "GOOD" (World Bank)

→ Узгодження якісної оцінки!
```

### Візуалізація (Folium map)

```python
import folium

def create_route_map(segments_df):
    # Створити карту
    center_lat = segments_df['avg_latitude'].mean()
    center_lon = segments_df['avg_longitude'].mean()
    m = folium.Map(location=[center_lat, center_lon], zoom_start=13)
    
    # Додати markers для кожного сегмента
    for _, row in segments_df.iterrows():
        folium.CircleMarker(
            location=[row['avg_latitude'], row['avg_longitude']],
            radius=5,
            color=row['color'],
            fill=True,
            fillColor=row['color'],
            fillOpacity=0.7,
            popup=f"RMSA: {row['avg_rmsa']:.2f} m/s²<br>Quality: {row['quality']}"
        ).add_to(m)
    
    m.save('road_quality_map.html')
```

**Outputs:**
- `road_quality_map.html` — interactive Folium map
- `grms_plot.png` — RMSA vs time
- `peaks_plot.png` — detected peaks overlay
- `road_segments.csv` — CSV з сегментами

---

## Чому RMSA "вищий"

### Gravity Contamination

**Legacy RMSA = 0.3335 (м/с²)**  
**New Grms = 0.0590 g ≈ 0.0590 * 9.8 = 0.578 (м/с²)**

Але фактично:
```
0.3335 / 0.0590 ≈ 5.65x (якщо порівнювати як g)
```

**Причини:**

#### 1. Body-frame processing
```
Legacy:
a_raw = [ax, ay, az]  (phone frame)
Rolling mean видаляє низькі частоти, але НЕ обертає вісі

Якщо phone під кутом θ:
az_body = a_linear_z * cos(θ) + g * sin(θ)
      ≈ 0.5 * cos(10°) + 9.8 * sin(10°)
      ≈ 0.49 + 1.70 = 2.19 m/s²  (навіть після calibration)
```

#### 2. 3D summation amplifies noise
```
RMSA = sqrt(RMS_x² + RMS_y² + RMS_z²)

Якщо кожна вісь містить gravity residual:
RMS_x ≈ 0.1 (gravity noise X)
RMS_y ≈ 0.1 (gravity noise Y)
RMS_z ≈ 0.3 (gravity noise Z + road signal)

RMSA = sqrt(0.01 + 0.01 + 0.09) = sqrt(0.11) ≈ 0.33 m/s²

Тоді як чистий road signal:
Grms_vertical ≈ 0.06 g ≈ 0.59 m/s² (world frame, gravity removed)
```

#### 3. Different frequency content
```
Legacy:
- High-pass 0.5 Hz (видаляє DC, але не gravity oscillations)
- Савіцький-Голей smoothing (поліном 2 порядку)

New:
- Low-pass 0.25 Hz для gravity estimation (steep rolloff)
- Band-pass 0.5-6 Hz після orientation correction
- Zero-phase filtfilt (no lag)
```

**Висновок:** RMSA вищий через **gravity contamination**, а не тому що legacy "краще детектує". Validation показала ρ = 0.942 (Grms vs RMSA) → **обидва метрики корелюють**, але new має lower noise floor.

---

## Еволюція підходу

### Legacy strengths (що було добре)

1. **Простота реалізації:**
   - Мінімум dependencies (pandas, numpy, scipy)
   - Швидка обробка (~10 секунд для 15 км)
   - Зрозумілий код для початківців

2. **Візуалізація:**
   - Folium map — інтуїтивно зрозумілий
   - Color-coded segments (green/orange/red)
   - Інтерактивні popups з метриками

3. **Peak detection:**
   - Statistical approach (mean + 2σ) — adaptive threshold
   - Працює без калібрування

4. **Практична застосовність:**
   - Виявляє roughness patterns (підтверджено ρ = 0.942)
   - Підходить для relative comparisons (segment A vs B)

### Limitations (що потрібно було покращити)

1. **Orientation:**
   - Body-frame → gravity contamination
   - RMSA завищений у 5-6 разів

2. **Segmentation:**
   - Time-based → variable spatial length
   - Неможливо порівнювати різні проїзди

3. **Calibration:**
   - Немає reference IRI для validation
   - Пороги класифікації empricial (не калібровані)

4. **GPS integration:**
   - ffill/bfill → non-causal
   - Low spatial resolution

5. **Testing:**
   - Немає unit tests
   - Non-deterministic (випадкові ініціалізації)

### Що змінилося в новому пайплайні

| Аспект | Legacy | New | Improvement |
|--------|--------|-----|-------------|
| Orientation | Body-frame, rolling mean | World-frame, quaternion rotation | ✅ Gravity видалений повністю |
| Segmentation | Time-based (variable length) | Distance-based (100 м) | ✅ Spatial consistency |
| Metrics | RMSA (м/с², змішаний) | Grms (g), IRI (m/km) | ✅ ISO compliance |
| GPS | ffill/bfill | Linear interpolation | ✅ Causal, фізично коректно |
| Anomalies | Statistical (mean+2σ) | Absolute (10 m/s²) | ✅ Fewer false positives |
| Testing | 0 tests | 163 unit tests | ✅ Deterministic, reproducible |
| Validation | None | Spearman ρ = 0.783 | ✅ Quantitative evidence |

### Чому legacy залишається цінним

**Для швидких польових замірів:**
- Простіша обробка (no complex rotations)
- Швидший результат (немає PSD обчислень)
- Immediate visualization (Folium map)

**Для навчання:**
- Зрозумілий код (good starting point)
- Демонструє базові концепції (RMS, rolling mean, peaks)

**Для порівняння:**
- Baseline для нових методів
- Validation reference (ρ = 0.942 показує, що обидва підходи capture roughness)

---

## Висновки

**Legacy пайплайн був важливим кроком:**
- Демонстрував feasibility smartphone-based approach
- Виявляв roughness patterns (підтверджено кореляцією)
- Служив baseline для validation нового пайплайну

**Еволюція була необхідною для:**
- Scientific validity (orientation correction, ISO compliance)
- Reproducibility (deterministic pipeline, unit tests)
- Comparability (distance-based segments, calibration)

**Результат:** новий пайплайн **зберігає** roughness detection (ρ = 0.783), але **додає** methodological rigor для наукових публікацій.

**Наступні розділи:**
- [04_experimental_design_and_reproducibility.md](04_experimental_design_and_reproducibility.md) — protocol
- [05_results_legacy_vs_new.md](05_results_legacy_vs_new.md) — числові результати
- [06_threats_to_validity_and_limitations.md](06_threats_to_validity_and_limitations.md) — обмеження

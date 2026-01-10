# 02 — Методи нового пайплайну

## Зміст
1. [Загальна архітектура](#загальна-архітектура)
2. [Крок 1: Ingestion](#крок-1-ingestion)
3. [Крок 2: Uniform Time Grid](#крок-2-uniform-time-grid)
4. [Крок 3: GPS Distance and Speed](#крок-3-gps-distance-and-speed)
5. [Крок 4: Orientation Correction (критичний!)](#крок-4-orientation-correction)
6. [Крок 5: Filtering](#крок-5-filtering)
7. [Крок 6: Metrics Computation](#крок-6-metrics-computation)
8. [Крок 7: Anomaly Detection](#крок-7-anomaly-detection)
9. [Крок 8: 100m Segmentation](#крок-8-100m-segmentation)
10. [Крок 9: Artifacts Export](#крок-9-artifacts-export)
11. [Determinism & Testing](#determinism--testing)

---

## Загальна архітектура

**Новий пайплайн:** `road_quality_analyzer/` (8 модулів)

```
                ┌─────────────────┐
                │  sensor CSV     │
                └────────┬────────┘
                         ↓
                ┌────────────────────┐
            (1) │  ingestion.py      │  Завантаження, розділення ACCEL/GPS
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
            (2) │ preprocessing.py   │  Uniform time grid (акселерометр)
                │                    │  GPS distance (Haversine)
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
            (3) │ orientation.py     │  Gravity alignment + GPS heading
                │                    │  a_vertical, a_perp
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
            (4) │ filtering.py       │  Band-pass 0.5-6 Hz
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
            (5) │ analysis.py        │  Grms, PSD, IRI_psd, IRI_multi
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
            (6) │ segmentation.py    │  100m bins, aggregate metrics
                └────────┬───────────┘
                         ↓
                ┌────────────────────┐
            (7) │ artifacts.py       │  CSV, GeoJSON, plots, HTML, report.md
                └────────────────────┘
```

**Всі формули:** `agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md`

---

## Крок 1: Ingestion

**Файл:** `road_quality_analyzer/ingestion.py`

**Функція:** `load_sensor_csv(filepath)`

### Псевдокод

```python
def load_sensor_csv(filepath):
    # 1. Завантажити CSV
    df_raw = pd.read_csv(filepath)
    
    # 2. Розділити за Type
    accel_mask = (df_raw['Type'] == 'ACCEL')
    gps_mask = (df_raw['Type'] == 'GPS')
    
    df_accel = df_raw[accel_mask][['Time', 'X', 'Y', 'Z']].copy()
    df_gps = df_raw[gps_mask][['Time', 'Latitude', 'Longitude']].copy()
    
    # 3. Перетворити Time: ms → seconds
    df_accel['t_sec'] = df_accel['Time'] / 1000.0
    df_gps['t_sec'] = df_gps['Time'] / 1000.0
    
    # 4. Видалити NaN (якщо є)
    df_accel = df_accel.dropna(subset=['X', 'Y', 'Z'])
    df_gps = df_gps.dropna(subset=['Latitude', 'Longitude'])
    
    # 5. НЕ використовувати ffill/bfill (на відміну від legacy)
    # → GPS інтерполюється пізніше на uniform grid
    
    return df_accel, df_gps
```

### Ключові відмінності від legacy

**Legacy (modules/io_utils.py):**
```python
# ❌ Змішує streams до розділення
df = pd.read_csv(filepath)
df = df.ffill().bfill()  # Forward/backward fill NaN
```

**Проблема legacy:**
- `ffill()` propagates GPS coordinates на ACCEL rows → неточна прив'язка
- `bfill()` використовує майбутні значення → non-causal

**New:**
- Розділяємо streams **спочатку**
- GPS інтерполюється лінійно на uniform grid (causal, фізично коректно)

---

## Крок 2: Uniform Time Grid

**Файл:** `road_quality_analyzer/preprocessing.py`

**Функція:** `build_uniform_time_grid(df_accel, df_gps)`

### Навіщо?

**Проблема:** акселерометр має **нерівномірний sampling**
```
Original timestamps:
[100.023, 100.043, 100.062, 100.081, 100.105, ...]  (Δt варіюється!)

Median Δt = 0.019 s → fs ≈ 52.6 Hz
```

**PSD (Welch) потребує рівномірної сітки** для FFT.

### Алгоритм

```python
def build_uniform_time_grid(df_accel, df_gps):
    # 1. Визначити fs з median delta
    dt_median = np.median(np.diff(df_accel['t_sec']))
    fs_hz = 1.0 / dt_median
    
    # 2. Створити uniform grid
    t_start = df_accel['t_sec'].min()
    t_end = df_accel['t_sec'].max()
    t_uniform = np.arange(t_start, t_end, dt_median)
    
    # 3. Resample акселерометр (linear interpolation)
    ax_uniform = np.interp(t_uniform, df_accel['t_sec'], df_accel['X'])
    ay_uniform = np.interp(t_uniform, df_accel['t_sec'], df_accel['Y'])
    az_uniform = np.interp(t_uniform, df_accel['t_sec'], df_accel['Z'])
    
    # 4. Resample GPS (linear interpolation)
    lat_uniform = np.interp(t_uniform, df_gps['t_sec'], df_gps['Latitude'])
    lon_uniform = np.interp(t_uniform, df_gps['t_sec'], df_gps['Longitude'])
    
    # 5. Створити DataFrame
    df_uniform = pd.DataFrame({
        't': t_uniform,
        'ax': ax_uniform,
        'ay': ay_uniform,
        'az': az_uniform,
        'lat': lat_uniform,
        'lon': lon_uniform
    })
    
    return df_uniform, fs_hz
```

**Результат:**
- `df_uniform` має рівномірну сітку (fs ≈ 52.6 Hz для нашого датасету)
- GPS interpolated на кожен акселерометр timestamp
- Ready для PSD та orientation correction

---

## Крок 3: GPS Distance and Speed

**Файл:** `road_quality_analyzer/preprocessing.py`

**Функції:**
- `compute_gps_distance(lat, lon)` — cumulative distance
- `build_distance_grid(df_uniform, fs_hz)` — відстань + швидкість

### Haversine Formula (Eq.B1 з `02_FORMULAS`)

Для двох точок `(lat1, lon1)` та `(lat2, lon2)`:

```python
def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000  # Earth radius (meters)
    
    # Перетворити градуси → радіани
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    
    # Haversine formula
    a = np.sin(dphi/2)**2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda/2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
    
    distance = R * c  # meters
    return distance
```

### Cumulative Distance

```python
def compute_gps_distance(lat, lon):
    distances = np.zeros(len(lat))
    
    for i in range(1, len(lat)):
        d = haversine_distance(lat[i-1], lon[i-1], lat[i], lon[i])
        distances[i] = distances[i-1] + d
    
    return distances
```

**Приклад:**
```
t (s):       [0.0,  0.019, 0.038, 0.057, ...]
s (m):       [0.0,  0.27,  0.55,  0.82,  ...]  (cumulative)
```

### Speed Estimation

```python
def build_distance_grid(df_uniform, fs_hz):
    # 1. Cumulative distance
    df_uniform['s'] = compute_gps_distance(df_uniform['lat'], df_uniform['lon'])
    
    # 2. Speed (smooth derivative)
    # v = ds/dt, але з kernel smoothing для GPS noise reduction
    kernel_size = int(fs_hz * 2.0)  # 2-second window
    df_uniform['v_ms'] = savgol_filter(
        np.gradient(df_uniform['s'], df_uniform['t']),
        window_length=kernel_size,
        polyorder=2
    )
    
    # 3. Convert to km/h
    df_uniform['v_kmh'] = df_uniform['v_ms'] * 3.6
    
    return df_uniform
```

**Навіщо smoothing:**
- GPS має noise ±3-10 м → `ds` має jumps
- `np.gradient()` amplifies noise
- Savitzky-Golay filter (polyorder=2) зглажує, зберігаючи trends

**Результат:**
```csv
t,s,v_ms,v_kmh
0.0,0.0,12.5,45.0
0.019,0.27,12.6,45.4
...
```

---

## Крок 4: Orientation Correction

**Файл:** `road_quality_analyzer/orientation.py`

**Функції:**
- `align_gravity(ax, ay, az, fs_hz)` → rotation matrix R(t)
- `compute_gps_heading(lat, lon)` → heading unit vector h_hat(t)
- `compute_perpendicular_accel(a_world, heading)` → a_perp(t)

### 4.1 Gravity Alignment (Eq.B3.1-B3.3 з `02_FORMULAS`)

**Мета:** знайти обертання R(t), яке вирівнює phone Z-axis з world vertical

#### Крок 1: Оцінити гравітацію (low-pass filter)

```python
def estimate_gravity(ax, ay, az, fs_hz, f_cutoff=0.25):
    # Butterworth low-pass filter (4th order)
    from scipy.signal import butter, filtfilt
    
    nyquist = fs_hz / 2.0
    b, a = butter(4, f_cutoff / nyquist, btype='low')
    
    # Zero-phase filtering (filtfilt)
    gx = filtfilt(b, a, ax)
    gy = filtfilt(b, a, ay)
    gz = filtfilt(b, a, az)
    
    return gx, gy, gz
```

**Параметри:**
- **f_cutoff = 0.25 Hz:** gravity змінюється повільно (phone rotation < 1 Hz)
- **4th order Butterworth:** steep rolloff, flat passband
- **filtfilt:** zero-phase (no lag)

**Результат:**
```
a_raw = [ax, ay, az] = a_linear + g
g_hat = low_pass(a_raw) ≈ gravity component
```

#### Крок 2: Обчислити вертикальний напрямок

```python
def compute_z_up(gx, gy, gz):
    # Gravity вказує "вниз", тому z_up = -normalize(g_hat)
    magnitude = np.sqrt(gx**2 + gy**2 + gz**2)
    
    z_up_x = -gx / magnitude
    z_up_y = -gy / magnitude
    z_up_z = -gz / magnitude
    
    return z_up_x, z_up_y, z_up_z
```

**Перевірка:** `|z_up| ≈ 1.0`, `z_up ≈ [0, 0, 1]` якщо phone horizontal

#### Крок 3: Quaternion "from-to" rotation

**Задача:** знайти quaternion q, що обертає `z_phone → z_world = [0,0,1]`

```python
def quaternion_from_to(u, v):
    """
    u: current direction (z_phone)
    v: target direction [0,0,1]
    Returns: quaternion [w, x, y, z]
    """
    # Cross product: axis of rotation
    w_vec = np.cross(u, v)
    
    # Dot product: angle
    c = np.dot(u, v)
    
    # Special case: u ≈ -v (180° rotation)
    if c < -0.9999:
        # Choose arbitrary perpendicular axis
        axis = np.array([1, 0, 0]) if abs(u[0]) < 0.9 else np.array([0, 1, 0])
        return np.array([0.0, axis[0], axis[1], axis[2]])
    
    # General case: q = [1+c, w_x, w_y, w_z]
    q = np.array([1.0 + c, w_vec[0], w_vec[1], w_vec[2]])
    
    # Normalize
    q = q / np.linalg.norm(q)
    
    return q
```

#### Крок 4: Quaternion → Rotation Matrix

```python
def quaternion_to_rotation_matrix(q):
    w, x, y, z = q
    
    R = np.array([
        [1 - 2*(y**2 + z**2),     2*(x*y - w*z),     2*(x*z + w*y)],
        [    2*(x*y + w*z), 1 - 2*(x**2 + z**2),     2*(y*z - w*x)],
        [    2*(x*z - w*y),     2*(y*z + w*x), 1 - 2*(x**2 + y**2)]
    ])
    
    return R
```

#### Крок 5: Apply Rotation

```python
def align_gravity(ax, ay, az, fs_hz):
    # 1. Estimate gravity
    gx, gy, gz = estimate_gravity(ax, ay, az, fs_hz)
    
    # 2. Compute z_up for each timestep
    z_up_x, z_up_y, z_up_z = compute_z_up(gx, gy, gz)
    
    # 3. Linear acceleration (subtract gravity)
    ax_lin = ax - gx
    ay_lin = ay - gy
    az_lin = az - gz
    
    # 4. Rotate to world frame
    a_vertical = np.zeros(len(ax))
    a_horizontal_x = np.zeros(len(ax))
    a_horizontal_y = np.zeros(len(ax))
    
    for i in range(len(ax)):
        # z_phone at time i
        z_phone = np.array([z_up_x[i], z_up_y[i], z_up_z[i]])
        
        # Quaternion rotation
        q = quaternion_from_to(z_phone, np.array([0, 0, 1]))
        R = quaternion_to_rotation_matrix(q)
        
        # Apply rotation
        a_phone = np.array([ax_lin[i], ay_lin[i], az_lin[i]])
        a_world = R @ a_phone
        
        a_vertical[i] = a_world[2]  # Z-component (vertical)
        a_horizontal_x[i] = a_world[0]  # X-component
        a_horizontal_y[i] = a_world[1]  # Y-component
    
    return a_vertical, a_horizontal_x, a_horizontal_y
```

**Результат:**
- `a_vertical` — чисто вертикальне прискорення (м/с²), gravity removed
- `a_horizontal_x, a_horizontal_y` — горизонтальні компоненти

### 4.2 GPS Heading (Eq.B2 з `02_FORMULAS`)

**Мета:** визначити напрямок руху у горизонтальній площині

```python
def compute_gps_heading(lat, lon):
    # ENU approximation (equirectangular)
    R = 6371000  # meters
    lat0 = np.radians(np.mean(lat))
    
    # Convert to local meters
    x = R * np.cos(lat0) * np.radians(lon)
    y = R * np.radians(lat)
    
    # Heading = normalize(Δx, Δy)
    dx = np.gradient(x)
    dy = np.gradient(y)
    
    magnitude = np.sqrt(dx**2 + dy**2)
    
    # Avoid division by zero (stop-and-go)
    magnitude = np.maximum(magnitude, 1e-6)
    
    heading_x = dx / magnitude
    heading_y = dy / magnitude
    
    return heading_x, heading_y
```

**Stop-and-go masking:**
```python
# Mask heading where speed < 1 m/s
valid_heading = (v_ms >= 1.0)
heading_x[~valid_heading] = np.nan
heading_y[~valid_heading] = np.nan
```

### 4.3 Perpendicular Acceleration (Eq.B3.4 з `02_FORMULAS`)

**Мета:** horizontal accel perpendicular to travel direction

```python
def compute_perpendicular_accel(a_horiz_x, a_horiz_y, heading_x, heading_y):
    # Perpendicular vector: p_hat = z_world × h_hat
    # z_world = [0, 0, 1], h_hat = [heading_x, heading_y, 0]
    # → p_hat = [-heading_y, heading_x, 0]
    
    perp_x = -heading_y
    perp_y = heading_x
    
    # Projection: a_perp = a_horiz · p_hat
    a_perp = a_horiz_x * perp_x + a_horiz_y * perp_y
    
    return a_perp
```

**Застосування:**
- ML features: `[a_vertical, a_perp, speed]` → anomaly classifier
- Lateral distress detection (potholes викликають lateral jolt)

---

## Крок 5: Filtering

**Файл:** `road_quality_analyzer/filtering.py`

**Функція:** `apply_bandpass(a_vertical_g, fs_hz, f_low=0.5, f_high=6.0)`

### Band-pass 0.5–6 Hz (Eq.B6 з `02_FORMULAS`)

**Навіщо:**
- **f < 0.5 Hz:** DC drift, ultra-low frequency noise
- **f > 6 Hz:** engine vibrations, electrical noise (не road roughness)
- **0.5–6 Hz:** типовий діапазон для road-induced vibrations

```python
from scipy.signal import butter, filtfilt

def apply_bandpass(signal, fs_hz, f_low=0.5, f_high=6.0):
    nyquist = fs_hz / 2.0
    
    # Normalized frequencies
    low = f_low / nyquist
    high = f_high / nyquist
    
    # Butterworth band-pass (4th order)
    b, a = butter(4, [low, high], btype='band')
    
    # Zero-phase filtering
    signal_filtered = filtfilt(b, a, signal)
    
    return signal_filtered
```

**Параметри за замовчуванням:**
- `f_low = 0.5 Hz`
- `f_high = 6.0 Hz`
- `order = 4`

**Конфігуровані через CLI:** `--filter-low 0.5 --filter-high 6.0`

---

## Крок 6: Metrics Computation

**Файл:** `road_quality_analyzer/analysis.py`

**Метрики:**
1. **Grms** — RMS вертикального прискорення (g)
2. **PSD scalar** — band power (g²)
3. **IRI_psd** — IRI з PSD (Eq.3)
4. **IRI_multi** — IRI з vehicle regression (Eq.4-6)

### 6.1 Grms (Eq.B4 з `02_FORMULAS`)

```python
def compute_grms(a_vertical_g):
    """
    a_vertical_g: vertical acceleration in g (after orientation correction)
    Returns: RMS in g
    """
    grms = np.sqrt(np.mean(a_vertical_g**2))
    return grms
```

**Приклад:**
```
a_vertical_g = [0.05, -0.03, 0.07, -0.04, 0.06, ...]  (100 samples)
grms = sqrt(mean([0.0025, 0.0009, 0.0049, 0.0016, 0.0036, ...])) ≈ 0.053 g
```

### 6.2 PSD (Welch Method, Eq.B5 з `02_FORMULAS`)

```python
from scipy.signal import welch

def compute_psd_scalar(a_vertical_g, fs_hz, f_low=0.5, f_high=6.0):
    # Welch PSD
    freqs, psd = welch(
        a_vertical_g,
        fs=fs_hz,
        window='hann',
        nperseg=min(256, len(a_vertical_g) // 4),
        noverlap=None,  # Default: nperseg // 2
        scaling='density'  # g² / Hz
    )
    
    # Band power
    mask = (freqs >= f_low) & (freqs <= f_high)
    df = freqs[1] - freqs[0]  # Frequency resolution
    
    band_power = np.sum(psd[mask]) * df  # g²
    sqrt_psd = np.sqrt(band_power)  # g
    
    return sqrt_psd
```

**Параметри:**
- **window='hann':** Hanning window (гладке згладжування)
- **nperseg=256:** segment length для FFT (trade-off: frequency resolution vs variance)
- **scaling='density':** PSD у g²/Hz (power per Hz)

### 6.3 IRI_psd (Eq.3 з `02_FORMULAS`)

**Формула з книги:**
```
IRI = 0.774 * sqrt(PSD) - 0.825  (m/km)
```

```python
def compute_iri_psd(sqrt_psd, A=0.774, B=0.825):
    """
    sqrt_psd: in g (from PSD band power)
    A, B: calibration coefficients from book (Eq.3)
    Returns: IRI in m/km
    """
    iri_psd = A * sqrt_psd - B
    return iri_psd
```

**Проблема:** IRI_psd може бути **< 0** якщо `sqrt_psd` малий або `A, B` не калібровані для конкретного phone/vehicle

**Приклад:**
```
sqrt_psd = 0.5 g
IRI_psd = 0.774 * 0.5 - 0.825 = -0.438 m/km  (негативний!)
```

**Рішення:**
- IRI_psd зберігаємо "as is" (може бути < 0)
- **Основний IRI** = IRI_multi (Eq.4-6), який завжди >= 0

### 6.4 IRI_multi (Eq.4-6 з `02_FORMULAS`)

**Формула (Eq.6, generic vehicle):**
```
IRI = 50.32 * Grms - 0.06 * Speed + 0.17 * Npeop - 1.86 * Stif - 0.90 * DampF - 0.78 * TyreS + 6.68
```

**Дефолтні параметри (без user input):**
```python
def compute_iri_multi(grms, speed_kmh, 
                      npeop=1, stif=1.0, damp_f=1.0, tyre_s=1.0):
    """
    Eq.6: Generic vehicle model
    
    grms: in g
    speed_kmh: in km/h
    npeop: number of people (1-4)
    stif: stiffness factor (0.8-1.2)
    damp_f: damping factor (0.8-1.2)
    tyre_s: tyre size factor (0.7-1.0)
    """
    iri = (50.32 * grms 
           - 0.06 * speed_kmh 
           + 0.17 * npeop 
           - 1.86 * stif 
           - 0.90 * damp_f 
           - 0.78 * tyre_s 
           + 6.68)
    
    return max(0.0, iri)  # Clamp to >= 0
```

**Приклад:**
```
grms = 0.059 g
speed_kmh = 41.7
npeop = 1
stif = 1.0, damp_f = 1.0, tyre_s = 1.0

IRI_multi = 50.32*0.059 - 0.06*41.7 + 0.17*1 - 1.86*1 - 0.90*1 - 0.78*1 + 6.68
          = 2.969 - 2.502 + 0.17 - 1.86 - 0.90 - 0.78 + 6.68
          = 3.78 m/km  ✓
```

**Validation:** наш результат 3.78 m/km → класифікація **GOOD** (2-4 m/km)

---

## Крок 7: Anomaly Detection

**Файл:** `road_quality_analyzer/analysis.py`

**Функція:** `detect_threshold_anomalies(a_vertical, threshold_ms2=10.0)`

### Threshold 10 m/s² (Eq.A5 з `02_FORMULAS`)

**Формула:**
```
anomaly(t) = 1  if |a_vertical(t)| > 10 m/s²
             0  otherwise
```

```python
def detect_threshold_anomalies(a_vertical, threshold_ms2=10.0):
    """
    a_vertical: in m/s² (world-frame, gravity removed)
    threshold_ms2: threshold in m/s²
    
    Returns: boolean array
    """
    anomalies = np.abs(a_vertical) > threshold_ms2
    return anomalies
```

**Приклад:**
```
a_vertical = [0.5, -0.3, 12.5, -0.4, 0.6, ...]  (m/s²)
threshold = 10.0 m/s²

anomalies = [False, False, True, False, False, ...]
→ count = 1 anomaly
```

**Наш датасет:** 0 anomalies (жодного |a_vertical| > 10 m/s²) → good road

### Distress Removal для PSD (Eq.B8 з `02_FORMULAS`)

**Навіщо:** Eq.3 калібровано "after removing the effect of distress"

```python
def remove_distress_windows(a_vertical_g, anomalies, fs_hz, window_sec=1.0):
    """
    Exclude ±window_sec навколо кожної anomaly
    """
    window_samples = int(window_sec * fs_hz)
    
    mask_exclude = np.zeros(len(a_vertical_g), dtype=bool)
    
    # Find anomaly indices
    anomaly_idx = np.where(anomalies)[0]
    
    for idx in anomaly_idx:
        # Exclude window
        start = max(0, idx - window_samples)
        end = min(len(a_vertical_g), idx + window_samples + 1)
        mask_exclude[start:end] = True
    
    # Clean signal
    a_clean = a_vertical_g[~mask_exclude]
    
    return a_clean
```

**Параметр window_sec:** конфігурований (default 1.0 s)

---

## Крок 8: 100m Segmentation

**Файл:** `road_quality_analyzer/segmentation.py`

**Функція:** `segment_by_distance(df_uniform, segment_length_m=100.0)`

### Алгоритм (Eq.B7 з `02_FORMULAS`)

```python
def segment_by_distance(df_uniform, segment_length_m=100.0):
    # 1. Compute seg_id
    df_uniform['seg_id'] = np.floor(df_uniform['s'] / segment_length_m).astype(int)
    
    # 2. Group by seg_id
    segments = []
    
    for seg_id, group in df_uniform.groupby('seg_id'):
        # Aggregate metrics
        s_start = group['s'].min()
        s_end = group['s'].max()
        
        # Grms
        grms = np.sqrt(np.mean(group['a_vertical_g']**2))
        
        # PSD (if enough samples)
        if len(group) >= 128:
            sqrt_psd = compute_psd_scalar(group['a_vertical_g'], fs_hz)
            iri_psd = compute_iri_psd(sqrt_psd)
        else:
            sqrt_psd = np.nan
            iri_psd = np.nan
        
        # IRI_multi
        mean_speed_kmh = group['v_kmh'].mean()
        iri_multi = compute_iri_multi(grms, mean_speed_kmh)
        
        # Anomalies
        anomaly_count = group['anomaly'].sum()
        
        # Valid ratio (GPS available, heading defined)
        valid_ratio = group['valid_heading'].sum() / len(group)
        
        segments.append({
            'seg_id': seg_id,
            's_start': s_start,
            's_end': s_end,
            'iri_multi': iri_multi,
            'iri_psd': iri_psd,
            'grms': grms,
            'mean_speed_kmh': mean_speed_kmh,
            'valid_ratio': valid_ratio,
            'anomaly_count': anomaly_count
        })
    
    df_segments = pd.DataFrame(segments)
    return df_segments
```

**Результат:**
```csv
seg_id,s_start,s_end,iri_multi,iri_psd,grms,mean_speed_kmh,valid_ratio,anomaly_count
0,0.0,99.88,7.67,3.45,0.128,34.8,0.98,0
1,100.0,199.86,3.60,2.12,0.054,41.2,1.00,0
...
```

---

## Крок 9: Artifacts Export

**Файл:** `road_quality_analyzer/artifacts.py`

**Функції:**
- `export_csv(df_segments, output_dir)` → road_segments.csv
- `export_geojson(df_segments, df_uniform, output_dir)` → roughness.geojson
- `export_plots(df_segments, output_dir)` → PNG plots
- `export_html_map(df_segments, df_uniform, output_dir)` → Folium map
- `generate_report(df_segments, metrics_overall, output_dir)` → report.md

### GeoJSON Structure

```python
def export_geojson(df_segments, df_uniform, output_dir):
    features = []
    
    for _, seg in df_segments.iterrows():
        # Get GPS points for this segment
        mask = (df_uniform['s'] >= seg['s_start']) & (df_uniform['s'] < seg['s_end'])
        seg_points = df_uniform[mask]
        
        # LineString coordinates
        coords = [[lon, lat] for lat, lon in zip(seg_points['lat'], seg_points['lon'])]
        
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coords
            },
            "properties": {
                "seg_id": int(seg['seg_id']),
                "s_start": float(seg['s_start']),
                "s_end": float(seg['s_end']),
                "iri_multi": float(seg['iri_multi']),
                "grms": float(seg['grms']),
                "mean_speed_kmh": float(seg['mean_speed_kmh']),
                "valid_ratio": float(seg['valid_ratio']),
                "anomaly_count": int(seg['anomaly_count'])
            }
        }
        features.append(feature)
    
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    with open(f"{output_dir}/roughness.geojson", 'w') as f:
        json.dump(geojson, f, indent=2)
```

---

## Determinism & Testing

**Файл:** `tests/` (22 unit tests)

### Фіксований seed

```python
np.random.seed(42)  # Для будь-яких stochastic операцій
```

### Test coverage

1. **test_ingestion.py** (3 tests)
   - `test_load_sensor_csv_separates_streams` — розділення ACCEL/GPS
   - `test_load_sensor_csv_no_ffill` — немає ffill/bfill
   - `test_time_conversion_to_seconds` — ms → seconds

2. **test_preprocessing.py** (5 tests)
   - `test_build_uniform_time_grid` — рівномірна сітка
   - `test_compute_gps_distance_haversine` — Haversine формула
   - `test_compute_gps_distance_cumulative` — monotonic increase
   - `test_build_distance_grid` — відстань + швидкість
   - `test_distance_grid_velocity_smoothing` — savgol filter

3. **test_orientation.py** (5 tests)
   - `test_gravity_alignment_synthetic_roll_pitch` — rotation matrix correctness
   - `test_gravity_alignment_synthetic_pitch` — single-axis tilt
   - `test_gps_heading` — heading unit vector
   - `test_perpendicular_accel` — a_perp calculation
   - `test_perpendicular_accel_masked_low_speed` — masking v < 1 m/s

4. **test_units.py** (4 tests)
   - `test_units_grms` — g units consistency
   - `test_units_threshold_anomaly` — m/s² threshold
   - `test_units_iri_psd_input` — PSD scalar в g
   - `test_psd_scalar_modes_consistency` — Welch parameters

5. **test_compare_runs.py** (5 tests, STAGE 2)
   - `test_haversine_distance` — geospatial distance
   - `test_compute_gps_distance` — cumulative distance
   - `test_binning_to_100m` — legacy re-binning
   - `test_rank_correlation_calculation` — Spearman
   - `test_outputs_created` — artifacts existence

**Всі тести:** 22/22 PASS (runtime ~3 секунди)

### Determinism checklist

- [x] Fixed random seed
- [x] Reproducible filters (filtfilt, zero-phase)
- [x] No external API calls (offline обробка)
- [x] Fixed parameters (f_low, f_high, threshold)
- [x] Unit tests для кожної функції

---

## Висновки

**Новий пайплайн реалізує:**
1. ✅ Orientation correction (gravity alignment + GPS heading)
2. ✅ Distance-based 100m segmentation
3. ✅ ISO 2631-1 compliant metrics (Grms, PSD)
4. ✅ Multi-method IRI (Eq.3 PSD, Eq.4-6 vehicle)
5. ✅ Threshold anomaly detection (10 m/s²)
6. ✅ Sampling compliance monitoring (dx ≤ 0.3 m)
7. ✅ Deterministic pipeline (22 tests)

**Ключові відмінності від legacy:**
- Gravity removal → Grms lower by 5.6x
- Distance segmentation → apples-to-apples comparison
- Uniform grid → PSD possible
- GPS heading → a_perp features

**Validation:** Spearman ρ = 0.783 → новий пайплайн зберігає roughness patterns legacy

**Наступні розділи:**
- [03_methods_legacy_pipeline.md](03_methods_legacy_pipeline.md) — legacy підхід
- [05_results_legacy_vs_new.md](05_results_legacy_vs_new.md) — числові результати

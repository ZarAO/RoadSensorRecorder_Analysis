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

**Новий пайплайн:** `road_quality_analyzer/` — оркеструє `cli.py::analyze()`

```
                ┌─────────────────┐
                │  sensor CSV     │
                └────────┬────────┘
                         ↓
                ┌──────────────────────────┐
            (1) │ io/ingestion.py          │  Завантаження, розділення потоків
                │                          │  Accelerometer/Gyroscope/Location
                └────────┬─────────────────┘
                         ↓
                ┌──────────────────────────┐
            (2) │ preprocessing/time_grid  │  Uniform time grid (акселерометр)
                │                          │  GPS distance (Haversine) + speed
                └────────┬─────────────────┘
                         ↓
                ┌──────────────────────────┐
            (3) │ orientation/             │  gravity_alignment.py: g_hat, R,
                │                          │  a_vertical; heading.py: GPS heading
                └────────┬─────────────────┘
                         ↓
                ┌──────────────────────────┐
            (4) │ filtering.py             │  Band-pass 0.5-6 Hz (filtfilt)
                └────────┬─────────────────┘
                         ↓
                ┌──────────────────────────┐
            (5) │ anomaly/threshold.py     │  |a_vertical| > 10 m/s²,
                │                          │  distress removal для PSD
                └────────┬─────────────────┘
                         ↓
                ┌──────────────────────────┐
            (6) │ metrics/grms.py, iri.py  │  Grms, PSD, IRI_psd, IRI_multi
                └────────┬─────────────────┘
                         ↓
                ┌──────────────────────────┐
            (7) │ segmentation/            │  100m bins, aggregate metrics
                │ segment_100m.py          │
                └────────┬─────────────────┘
                         ↓
                ┌──────────────────────────┐
            (8) │ artifacts.py             │  GeoJSON, plots, HTML
                │ cli.py                   │  road_segments.csv, report.md
                └──────────────────────────┘
```

**Всі формули:** `agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md`

---

## Крок 1: Ingestion

**Файл:** `road_quality_analyzer/io/ingestion.py`

**Функція:** `load_sensor_csv(filepath) -> SensorData`

### Псевдокод

```python
EXPECTED_COLUMNS = ['Time', 'Type', 'X', 'Y', 'Z', 'Latitude', 'Longitude']

def load_sensor_csv(filepath):
    # 1. Завантажити CSV; comment='#' пропускає metadata-преамбулу контракту v2,
    #    index_col=False — рядок із зайвим полем падає, а не зсуває колонки
    df = pd.read_csv(filepath, comment='#', index_col=False)
    if list(df.columns) != EXPECTED_COLUMNS:
        raise ValueError(...)          # заголовок фіксований контрактом

    # 2. Перевести Time у секунди від початку запису.
    #    Одиниця визначається за величиною (_detect_time_unit): epoch-ms ~1.7e12,
    #    epoch-s ~1.7e9; підтримується також ISO-рядок
    df['time_sec'] = (df['Time'] - df['Time'].min()) / divisor

    # 3. Розділити за Type (порівняння без урахування регістру)
    accel = _prepare_stream(df[type_lower == 'accelerometer'], ['x', 'y', 'z'])
    gyro  = _prepare_stream(df[type_lower == 'gyroscope'],     ['x', 'y', 'z'])
    loc   = _prepare_stream(df[type_lower == 'location'], ['latitude', 'longitude'])

    # _prepare_stream: dropna → стабільне сортування (mergesort) за часом →
    # згортання дублікатів timestamp у середнє (interp1d вимагає строго зростаючий x)

    # 4. НЕ використовувати ffill/bfill (на відміну від legacy)
    #    → GPS інтерполюється пізніше на uniform grid

    if len(accel) == 0:
        raise ValueError(...)          # перелічує знайдені значення Type

    return SensorData(accel_time=..., accel_x=..., ..., time_unit=time_unit)
```

`SensorData` містить окремі потоки акселерометра, гіроскопа та локації;
`gyro_*` і `gps_*` дорівнюють `None`, якщо відповідних рядків у файлі немає.

### Ключові відмінності від legacy

**Legacy (modules/io_utils.py):**
```python
# ❌ Змішує streams до розділення
df = pd.read_csv(filepath)
df = df.ffill().bfill()  # Forward/backward fill NaN
```

**Проблема legacy:**
- `ffill()` propagates GPS coordinates на рядки акселерометра → неточна прив'язка
- `bfill()` використовує майбутні значення → non-causal

**New:**
- Розділяємо streams **спочатку**
- GPS інтерполюється лінійно на uniform grid (causal, фізично коректно)

---

## Крок 2: Uniform Time Grid

**Файл:** `road_quality_analyzer/preprocessing/time_grid.py`

**Функція:** `build_uniform_time_grid(accel_time, accel_x, accel_y, accel_z)`

### Навіщо?

**Проблема:** акселерометр має **нерівномірний sampling**
```
Original timestamps:
[100.023, 100.043, 100.062, 100.081, 100.105, ...]  (Δt варіюється!)

Median Δt = 0.019 s → fs ≈ 52.6 Hz (для датасету 2025-07-29;
рекордер зараз запитує 100 Hz, але фактична частота теж плаває)
```

**PSD (Welch) потребує рівномірної сітки** для FFT.

### Алгоритм

```python
def build_uniform_time_grid(accel_time, accel_x, accel_y, accel_z):
    # 1. Визначити крок з median delta (медіана, не середнє: стійка до пропусків)
    dt_median = np.median(np.diff(accel_time))

    # 2. Створити uniform grid
    t_grid = np.arange(accel_time[0], accel_time[-1], dt_median)

    # 3. Resample акселерометр (linear interpolation, scipy interp1d)
    ax_grid = interp1d(accel_time, accel_x, kind='linear')(t_grid)
    ay_grid = interp1d(accel_time, accel_y, kind='linear')(t_grid)
    az_grid = interp1d(accel_time, accel_z, kind='linear')(t_grid)

    return t_grid, ax_grid, ay_grid, az_grid
```

`fs = 1 / median(diff(t_grid))` обчислюється в `cli.py::analyze()`; якщо результат
поза смугою 5–1000 Hz, аналіз падає з `ValueError` (ознака неправильної одиниці
колонки `Time`).

**Результат:**
- рівномірна сітка часу для акселерометра
- GPS **не** інтерполюється тут — відстань і швидкість будує окрема
  `build_distance_grid(gps_time, gps_lat, gps_lon, t_grid)` (крок 3)
- Ready для PSD та orientation correction

---

## Крок 3: GPS Distance and Speed

**Файл:** `road_quality_analyzer/preprocessing/time_grid.py`

**Функції:**
- `compute_gps_distance(lat, lon)` — cumulative distance
- `build_distance_grid(gps_time, gps_lat, gps_lon, t_grid)` — відстань + швидкість

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
def build_distance_grid(gps_time, gps_lat, gps_lon, t_grid):
    # 1. Cumulative distance у точках GPS
    s_gps = compute_gps_distance(gps_lat, gps_lon)

    # 2. Інтерполяція на t_grid БЕЗ екстраполяції:
    #    поза часовим діапазоном GPS відстань невідома → NaN
    s_grid = interp1d(gps_time, s_gps, kind='linear',
                      bounds_error=False, fill_value=np.nan)(t_grid)

    # 3. Швидкість: згладжування ДО диференціювання (~1 с ковзне середнє)
    dt = np.median(np.diff(t_grid))
    window_size = max(1, int(round(1.0 / dt)))

    v_grid = np.full_like(s_grid, np.nan)
    covered = np.isfinite(s_grid)
    if np.sum(covered) > 1:
        s_covered = s_grid[covered]
        if window_size > 1:
            s_covered = uniform_filter1d(s_covered, size=window_size,
                                         mode='nearest')
        v_grid[covered] = np.gradient(s_covered, dt)

    return s_grid, v_grid
```

**Навіщо smoothing:**
- GPS має noise ±3-10 м → `ds` має jumps
- `np.gradient()` amplifies noise, тому рівномірне ковзне середнє (`uniform_filter1d`,
  вікно ≈ 1 с) застосовується **до відстані й до диференціювання**, а не до готової
  похідної
- `mode='nearest'` не «притягує» краї до нуля, як згортка з нульовим доповненням
- `s` — кумулятивна сума модулів haversine, тобто монотонна, тому похідна
  невід'ємна без додаткового clipping

**Результат:** `(s_grid, v_grid)` на `t_grid` — відстань у метрах і швидкість у м/с.
Поза покриттям GPS обидва масиви дорівнюють `NaN`; ці семпли `cli.py::analyze()`
відкидає перед сегментацією. Переведення в км/год відбувається пізніше, у
`segmentation/segment_100m.py` (`mean_speed_kmh = mean_speed_mps * 3.6`).

---

## Крок 4: Orientation Correction

**Файли:**
- `road_quality_analyzer/orientation/gravity_alignment.py`
- `road_quality_analyzer/orientation/heading.py`

**Функції:**
- `estimate_gravity(accel_x, accel_y, accel_z, fs, cutoff_hz=0.3)` → g_hat(t)
- `compute_rotation_matrix(g_hat_x, g_hat_y, g_hat_z)` → R(t), масив (N, 3, 3)
- `transform_to_world(accel_x, accel_y, accel_z, g_hat_x, g_hat_y, g_hat_z, R_matrices)`
  → `(a_world_x, a_world_y, a_world_z, a_vertical)`; далі використовується лише
  `a_vertical`
- `compute_gps_heading(gps_time, gps_lat, gps_lon, t_grid, heading_min_speed_mps=1.0)`
  → `(heading_x, heading_y, heading_valid)`

### 4.1 Gravity Alignment (Eq.B3.1-B3.3 з `02_FORMULAS`)

**Мета:** знайти обертання R(t), яке вирівнює phone Z-axis з world vertical

#### Крок 1: Оцінити гравітацію (low-pass filter)

```python
def estimate_gravity(ax, ay, az, fs_hz, cutoff_hz=0.3):
    # Butterworth low-pass filter (4th order)
    from scipy.signal import butter, filtfilt
    
    nyquist = fs_hz / 2.0
    b, a = butter(4, cutoff_hz / nyquist, btype='low')
    
    # Zero-phase filtering (filtfilt)
    gx = filtfilt(b, a, ax)
    gy = filtfilt(b, a, ay)
    gz = filtfilt(b, a, az)
    
    return gx, gy, gz
```

**Параметри:**
- **cutoff_hz = 0.3 Hz** (значення, яке передає `cli.py`; сам аргумент має
  замовчування 0.3): gravity змінюється повільно (phone rotation < 1 Hz)
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
def compute_gps_heading(gps_time, gps_lat, gps_lon, t_grid,
                        heading_min_speed_mps=1.0):
    # 1. ENU approximation (equirectangular) навколо першої точки
    x_gps, y_gps = latlon_to_enu(gps_lat, gps_lon)

    # 2. Інтерполяція на uniform time grid
    x_grid = interp1d(gps_time, x_gps, kind='linear',
                      bounds_error=False, fill_value='extrapolate')(t_grid)
    y_grid = interp1d(gps_time, y_gps, kind='linear',
                      bounds_error=False, fill_value='extrapolate')(t_grid)

    # 3. Згладжування позиції ДО диференціювання (~1 с ковзне середнє):
    #    np.gradient підсилює GPS-шум
    dt = np.median(np.diff(t_grid))
    window_size = max(1, int(round(1.0 / dt)))
    if window_size > 1:
        x_grid = uniform_filter1d(x_grid, size=window_size, mode='nearest')
        y_grid = uniform_filter1d(y_grid, size=window_size, mode='nearest')

    # 4. Heading = normalize(Δx, Δy)
    dx = np.gradient(x_grid, dt)
    dy = np.gradient(y_grid, dt)
    speed = np.hypot(dx, dy)

    # 5. Stop-and-go masking: heading невизначений при v < 1 м/с
    heading_x = np.zeros_like(dx)
    heading_y = np.zeros_like(dy)
    heading_valid = speed >= heading_min_speed_mps

    normalizable = heading_valid & (speed > 1e-6)
    heading_x[normalizable] = dx[normalizable] / speed[normalizable]
    heading_y[normalizable] = dy[normalizable] / speed[normalizable]

    return heading_x, heading_y, heading_valid
```

`heading_valid` використовується лише як показник якості GPS (кількість валідних
семплів друкується у `report.md`). Горизонтальні компоненти світового прискорення
та перпендикулярна складова `a_perp` у поточному пайплайні не обчислюються і не
експортуються — метрики рахуються тільки з `a_vertical`.

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

**Задані константами в `cli.py`** (`BAND_LOW_HZ`, `BAND_HIGH_HZ`); CLI-прапорців
для їх зміни немає — фактичні значення друкуються у `report.md`.

**Edge trim:** `cli.py::analyze()` відкидає по 3 с (`EDGE_TRIM_SEC = 3.0`, тобто
158 семплів при fs ≈ 52.6 Hz) з кожного кінця **після** того, як усі фільтри
відпрацювали на повному вікні покриття GPS. Розмір задає найповільніший фільтр
ланцюга — gravity low-pass 0.3 Hz; обрізання входу замість виходу лише залишило б
filtfilt-транзієнти всередині аналітичного вікна.

---

## Крок 6: Metrics Computation

**Файли:**
- `road_quality_analyzer/metrics/grms.py` — `compute_grms(a_vertical_g)`
- `road_quality_analyzer/metrics/iri.py` — `compute_psd_band_power(...)`,
  `compute_iri_psd(...)`, `compute_iri_multi(...)`

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

def compute_psd_band_power(signal_g, fs, f_low=0.5, f_high=6.0,
                           nperseg=None, scalar_mode='mean_psd_sqrt'):
    # Welch потребує щонайменше 2 с сигналу; інакше NaN, а не вигадане число
    if len(signal_g) < fs * 2:
        return np.nan, _nan_psd_debug(scalar_mode, len(signal_g), 0, 0)

    if nperseg is None:
        nperseg = min(len(signal_g), int(fs * 4))

    freqs, psd = welch(signal_g, fs=fs, window='hann',
                       nperseg=nperseg, noverlap=nperseg // 2)

    # Band power
    idx_band = (freqs >= f_low) & (freqs <= f_high)
    df = freqs[1] - freqs[0]          # frequency resolution
    psd_band = psd[idx_band]
    band_power = np.sum(psd_band) * df  # g²

    # Eq.3 бере корінь із густини PSD (g/√Hz), а не з інтегральної потужності,
    # тому режим за замовчуванням — 'mean_psd_sqrt'
    sqrtPSD = np.sqrt(np.mean(psd_band))

    return sqrtPSD, debug_info
```

**Параметри:**
- **window='hann':** Hanning window (гладке згладжування)
- **nperseg = fs*4** (≈ 210 семплів при fs ≈ 52.6 Hz), `noverlap = nperseg // 2`
- **scaling:** `welch` за замовчуванням повертає густину, тобто g²/Hz
- **Guard `n >= fs*2`:** сегмент коротший за 2 с не дає PSD → `NaN`
- **scalar_mode:** `mean_psd_sqrt` (default), `band_power_sqrt`, `median_psd_sqrt`,
  `peak_psd_sqrt` — усі чотири прораховуються у `cli.py` як діагностика і
  порівнюються в `report.md`

### 6.3 IRI_psd (Eq.3 з `02_FORMULAS`)

**Формула з книги:**
```
IRI = 0.774 * sqrt(PSD) - 0.825  (m/km)
```

```python
def compute_iri_psd(a_vertical_g, fs, f_low=0.5, f_high=6.0,
                    scalar_mode='mean_psd_sqrt', return_debug=False):
    """
    Returns: (iri_psd_raw, iri_psd, debug_info), обидва IRI у m/km
    """
    sqrtPSD, debug_info = compute_psd_band_power(
        a_vertical_g, fs, f_low, f_high, scalar_mode=scalar_mode
    )

    # Eq.3 з книги, коефіцієнти НЕ перекалібровуються під датасет
    iri_psd_raw = 0.774 * sqrtPSD - 0.825

    # Clipped-версія; NaN НЕ перетворюється на 0 — max() сховав би пропуск
    iri_psd = max(0.0, iri_psd_raw) if np.isfinite(iri_psd_raw) else np.nan

    return iri_psd_raw, iri_psd, debug_info
```

**Проблема:** `iri_psd_raw` може бути **< 0**, якщо виміряна густина PSD нижча за
поріг калібрування Eq.3 (некалібрований телефон/кріплення), а не тому, що дорога
ідеальна.

**Приклад (сегмент 1 поточного датасету):**
```
psd_sqrt_scalar = 0.013478 g/√Hz
iri_psd_raw     = 0.774 * 0.013478 - 0.825 = -0.8146 m/km  (негативний)
iri_psd         = max(0, -0.8146)           =  0.00 m/km
```

**Контракт:**
- `iri_psd_raw` — сире значення Eq.3, зберігається як діагностика калібрування
- `iri_psd = max(0, iri_psd_raw)` — те, що використовується далі
- обидві колонки експортуються в `road_segments.csv`
- обидві дорівнюють `NaN`, якщо PSD неможливо обчислити (`n < fs*2` або порожня
  смуга); Eq.3 не має speed-члена, тому `iri_psd` **не** залежить від `speed_valid`
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

**Приклад (сегмент 1 поточного датасету):**
```
grms = 0.066388 g
speed_kmh = 37.761
npeop = 1
stif = 1.0, damp_f = 1.0, tyre_s = 1.0

IRI_multi = 50.32*0.066388 - 0.06*37.761 + 0.17*1 - 1.86*1 - 0.90*1 - 0.78*1 + 6.68
          = 3.3406 - 2.2657 + 0.17 - 1.86 - 0.90 - 0.78 + 6.68
          = 4.385 m/km
```

Eq.4/5/6 містять speed-член і калібровані лише для 20–100 км/год, тому поза цим
діапазоном (`speed_valid = False`) записується `NaN`, а не 0.

**Validation:** середнє по повних сегментах поточного датасету — **2.99 m/km**
(150 повних сегментів зі 152; числа й умови прогону — у
[05_results_legacy_vs_new.md](05_results_legacy_vs_new.md)), тобто класифікація
**GOOD** (2-4 m/km)

---

## Крок 7: Anomaly Detection

**Файл:** `road_quality_analyzer/anomaly/threshold.py`

**Функції:**
- `detect_threshold_anomalies(a_vertical, threshold_ms2=10.0)`
- `remove_distress_windows(signal, anomaly_mask, fs, window_sec=0.5)`

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

**Наш датасет:** 0 anomalies (жодного |a_vertical| > 10 m/s²). Це **не** доказ
ідеальної дороги: поріг 10 m/s² узятий із книги для сирого показу акселерометра, а
пайплайн застосовує його до gravity-removed вертикалі у світовій системі й не
калібрує під конкретний телефон і кріплення. Тому кількість подій може бути
заниженою — див. [06_threats_to_validity_and_limitations.md](06_threats_to_validity_and_limitations.md).

### Distress Removal для PSD (Eq.B8 з `02_FORMULAS`)

**Навіщо:** Eq.3 калібровано "after removing the effect of distress"

```python
def remove_distress_windows(signal, anomaly_mask, fs, window_sec=0.5):
    """
    Замаскувати ±window_sec навколо кожної anomaly
    """
    cleaned_signal = signal.copy()

    anomaly_indices = np.where(anomaly_mask)[0]
    window_samples = int(window_sec * fs)

    for idx in anomaly_indices:
        start = max(0, idx - window_samples)
        end = min(len(signal), idx + window_samples + 1)
        cleaned_signal[start:end] = np.nan   # NaN, а не видалення семплів

    return cleaned_signal
```

**Параметр window_sec:** фіксований ±0.5 с (`DISTRESS_WINDOW_SEC = 0.5` у `cli.py`);
CLI-прапорця для його зміни немає.

**Чому NaN, а не компактний масив:** функція повертає масив тієї самої довжини, у
якому вікна аномалій замінені на `NaN`. Стикувати вцілілі шматки впритул не можна —
у місці склейки з'явився б стрибок, який Welch побачив би як широкосмугову енергію
рівно в смузі Eq.3. Тому `segmentation/segment_100m.py::longest_finite_run()` бере
**найдовший неперервний скінченний відрізок** сегмента і подає у Welch лише його;
якщо цей відрізок коротший за `fs*2`, сегмент просто не має `IRI_psd` (`NaN`).

---

## Крок 8: 100m Segmentation

**Файл:** `road_quality_analyzer/segmentation/segment_100m.py`

**Функції:**
- `create_segments(s_grid, segment_length_m=100.0)` → `{seg_id: indices}`
- `longest_finite_run(signal)` → найдовший неперервний скінченний відрізок
- `aggregate_segment_metrics(...)` → метрики одного сегмента
- `create_segments_dataframe(...)` → `pandas.DataFrame` усіх сегментів

### Алгоритм (Eq.B7 з `02_FORMULAS`)

```python
MIN_FULL_SEGMENT_M = 90.0
SPEED_VALID_MIN_KMH, SPEED_VALID_MAX_KMH = 20.0, 100.0
DX_COMPLIANT_M = 0.3
LOW_SPEED_MAX_KMH = SPEED_VALID_MIN_KMH          # 20 км/год
LOW_SPEED_CLASS_BY_POLICY = {'very-poor': 'very_poor', 'poor': 'poor',
                             'invalid': 'invalid', 'ignore': 'ignore'}
NORMAL_SPEED_CLASS = 'normal'


def create_segments(s_grid, segment_length_m=100.0):
    # s_grid має бути вже очищений від NaN: поза покриттям GPS відстань невідома,
    # а np.floor(NaN).astype(int) створив би фантомний сегмент
    if not np.all(np.isfinite(s_grid)):
        raise ValueError(...)

    seg_ids = np.floor(s_grid / segment_length_m).astype(int)
    return {sid: np.where(seg_ids == sid)[0] for sid in np.unique(seg_ids)}


def aggregate_segment_metrics(seg_id, indices, a_vertical_g, a_vertical_g_psd,
                              v_grid, s_grid, fs, anomaly_mask=None,
                              low_speed_policy='invalid', ...):
    seg_s = s_grid[indices]
    seg_v = v_grid[indices]
    length_m = seg_s[-1] - seg_s[0]
    mean_speed_kmh = np.mean(seg_v) * 3.6

    # Дорога, якою неможливо їхати швидше за 20 км/год: збудження підвіски падає
    # під смугу 0.5-6 Hz, тому сегмент дістає мітку, а не число
    low_speed = mean_speed_kmh < LOW_SPEED_MAX_KMH

    metrics = {
        'seg_id': seg_id,
        's_start': seg_s[0],
        's_end': seg_s[-1],
        'length_m': length_m,
        'partial': length_m < MIN_FULL_SEGMENT_M,   # хвіст запису
        'n_samples': len(indices),
        'mean_speed_mps': np.mean(seg_v),
        'mean_speed_kmh': mean_speed_kmh,
        'speed_valid': SPEED_VALID_MIN_KMH <= mean_speed_kmh <= SPEED_VALID_MAX_KMH,
        'low_speed_class': (LOW_SPEED_CLASS_BY_POLICY[low_speed_policy]
                            if low_speed else NORMAL_SPEED_CLASS),
        'needs_class12_survey': low_speed,          # прилад класу 1/2 (профілометр)
        'dx_le_03_share': np.mean((seg_v / fs) <= DX_COMPLIANT_M),
    }

    metrics['grms'] = compute_grms(a_vertical_g[indices])

    # Welch — лише на найдовшому неперервному чистому відрізку сигналу без
    # distress-вікон; guard n >= fs*2 сидить усередині compute_psd_band_power
    seg_psd_input = longest_finite_run(a_vertical_g_psd[indices])
    iri_psd_raw, iri_psd, debug = compute_iri_psd(seg_psd_input, fs, ...)
    metrics['iri_psd_raw'] = iri_psd_raw
    metrics['iri_psd'] = iri_psd
    # + діагностика PSD: psd_band_power, psd_sqrt_scalar, psd_scalar_mode,
    #   psd_n_samples_used, psd_df_hz, fs_used_hz

    # Eq.4/5/6 мають speed-член і калібровані для 20-100 км/год → поза діапазоном NaN
    metrics['iri_multi'] = (
        compute_iri_multi(metrics['grms'], mean_speed_kmh,
                          vehicle_type=VehicleType.GENERIC)
        if metrics['speed_valid'] else np.nan
    )

    metrics['anomaly_count'] = int(np.sum(anomaly_mask[indices]))

    # Пороговий детектор працює й нижче 20 км/год, тому для low-speed сегментів
    # саме events_per_km замінює IRI; нульова довжина → NaN, не ділення на нуль
    metrics['events_per_km'] = (metrics['anomaly_count'] / (length_m / 1000.0)
                                if length_m > 0 else np.nan)
    return metrics
```

**Політика low-speed сегментів (`--low-speed-policy`).** Мітка залежить від
політики, число — ніколи: `iri_multi` лишається `NaN` за будь-якої з чотирьох
політик, бо Eq.4/5/6 калібровані лише на 20–100 км/год (опорні швидкості
30/50/80 км/год), а частота збудження `v / λ` нижче 20 км/год виходить за смугу
0.5–6 Hz, у якій визначені Eq.3 і Grms. Політика `ignore` додатково прибирає
рядки з `road_segments.csv`, `roughness.geojson` і карти — але не зі звіту:
`report.md` рахує та перелічує їх у секції «Сегменти з низькою швидкістю».

**Результат:** `road_segments.csv` має 24 колонки (значення нижче округлені для
читабельності; повний опис колонок — у
[08_user_guide_and_cli_reference.md](08_user_guide_and_cli_reference.md)):

```csv
seg_id,s_start,s_end,length_m,partial,n_samples,mean_speed_mps,mean_speed_kmh,speed_valid,low_speed_class,needs_class12_survey,dx_le_03_share,grms,iri_psd_raw,iri_psd,psd_band_power,psd_sqrt_scalar,psd_scalar_mode,psd_n_samples_used,psd_df_hz,fs_used_hz,iri_multi,anomaly_count,events_per_km
0,28.608,99.878,71.270,True,385,9.767,35.162,True,normal,False,1.0,0.045616,-0.811575,0.0,0.001659,0.017346,mean_psd_sqrt,385,0.250627,52.632,3.495702,0,0.0
1,100.077,199.974,99.897,False,502,10.489,37.761,True,normal,False,1.0,0.066388,-0.814568,0.0,0.001002,0.013478,mean_psd_sqrt,502,0.250627,52.632,4.384994,0,0.0
5,500.093,599.926,99.833,False,3026,1.738,6.257,False,invalid,True,1.0,0.011871,-0.822574,0.0,0.000054,0.003135,mean_psd_sqrt,3026,0.250627,52.632,,0,0.0
...
```

Сегмент 0 позначений `partial=True`: після обрізання країв (3 с) запис починається
на 28.6 м, тому в перший 100-метровий бін потрапляє лише 71.3 м.

Сегмент 5 пройдено на 6.3 км/год: `needs_class12_survey=True`, `iri_multi` порожній
(NaN), а стан ділянки описує `events_per_km`. У записі 2025-07-29 таких сегментів
19 зі 152.

---

## Крок 9: Artifacts Export

**Файл:** `road_quality_analyzer/artifacts.py`

**Функції:**
- `export_segments_geojson(...)` → roughness.geojson (LineString на сегмент)
- `export_events_geojson(...)` → events.geojson (Point на кожну аномалію)
- `create_segments_map_html(...)` → segments_map.html (Folium)
- `create_plots(...)` → plots/*.png + plots/*.pdf (стиль SciencePlots)

`road_segments.csv` (`segments_df.to_csv`) і `report.md` пише сам
`cli.py::analyze()`. Метрики серіалізуються через `_json_num`: не-скінченне
значення стає `null`, а не `NaN` (валідний JSON), `json.dump(..., allow_nan=False)`.

### GeoJSON Structure

```python
# спрощено; реальна реалізація — export_segments_geojson()
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
                "s_start": _json_num(seg['s_start']),
                "s_end": _json_num(seg['s_end']),
                "length_m": _json_num(seg['length_m']),
                "partial": bool(seg['partial']),
                "iri_multi": _json_num(seg['iri_multi']),
                "iri_psd_raw": _json_num(seg['iri_psd_raw']),
                "iri_psd": _json_num(seg['iri_psd']),
                "grms": _json_num(seg['grms']),
                "mean_speed_kmh": _json_num(seg['mean_speed_kmh']),
                "speed_valid": bool(seg['speed_valid']),
                "low_speed_class": str(seg['low_speed_class']),
                "needs_class12_survey": bool(seg['needs_class12_survey']),
                "dx_le_03_share": _json_num(seg['dx_le_03_share']),
                "anomaly_count": int(seg['anomaly_count']),
                "events_per_km": _json_num(seg['events_per_km'])
                # + psd_sqrt_scalar / psd_scalar_mode / psd_band_power, якщо є
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

### Позначення low-speed сегментів на карті

`create_segments_map_html()` фарбує сегменти за `iri_multi`, нормованим на
[min, max] цього запису (зелений `#1A9641` → синій `#2C7BB6` → помаранчевий
`#FF7F00` → червоний `#D7191C`). Сегмент із `needs_class12_survey = True`
знімається з цієї шкали повністю:

```python
LOW_SPEED_COLOR = '#FF00FF'
LOW_SPEED_LEGEND_LABEL = 'Потребує обстеження профілометром (клас 1/2)'
LOW_SPEED_WEIGHT_BONUS = 2      # товща за звичайні LINE_WEIGHT = 8

if bool(row['needs_class12_survey']):
    color = LOW_SPEED_COLOR
    line_weight = LINE_WEIGHT + LOW_SPEED_WEIGHT_BONUS
```

Пурпуровий не трапляється ніде у шкалі IRI, тому кандидата на обстеження
профілометром неможливо сплутати з оціненим сегментом. Легенда додається на
карту лише тоді, коли такий сегмент справді намальовано (`has_low_speed`),
а tooltip для нього додатково показує `low_speed_class` і той самий текст
легенди. `events_per_km` є у tooltip кожного сегмента.

---

## Determinism & Testing

**Файл:** `tests/` (163 unit tests у 11 файлах)

### Фіксований seed

Єдине джерело випадковості в тестах — фікстура `rng` у `tests/conftest.py`:
явно засіяний `default_rng`, незалежний від глобального стану NumPy (глобальний
`np.random` не використовує ні пакет, ні тести):

```python
SEED = 20260101

@pytest.fixture
def rng():
    return np.random.default_rng(SEED)
```

Сам пайплайн (`analyze()`) стохастичних операцій не має — детермінізм перевіряє
`test_cli.py::test_pipeline_is_deterministic_across_two_runs`, який запускає
аналіз двічі на тому самому CSV і порівнює `road_segments.csv` побайтово.

### Test coverage

Тестові дані синтезуються в `tmp_path` (`tests/conftest.py::write_drive_csv`);
11-мегабайтний реальний запис у тестах не використовується.

1. **test_ingestion.py** (13 tests) — контракт CSV v2: розділення потоків,
   заборона ffill/bfill, `#`-преамбула, згортання дублікатів timestamp,
   детекція одиниці Time (ms / s / epoch-s / ISO), вироджені входи
   (порожній файл, немає Accelerometer, немає Location, зайве поле в рядку),
   стабільне сортування.

2. **test_preprocessing.py** (12 tests) — uniform grid з **median** dt (не mean),
   haversine із масштабуванням `cos(lat)` для довготи та контроль на
   транспозицію lat/lon, NaN поза покриттям GPS, згладжування ДО диференціювання.

3. **test_orientation.py** (11 tests) — відновлення відомого вертикального
   поштовху на нахиленому телефоні (30° roll / 20° pitch), відсутність витоку
   бічного прискорення у вертикаль, ортонормальність `R` та `det(R) = 1`,
   ENU з `cos(lat0)`, маскування heading при v < 1 м/с.

4. **test_filtering.py** (12 tests) — підсилення 1.0 у смузі та 0.5 на її межах
   (filtfilt застосовує фільтр двічі), придушення 0.1 Гц і 15 Гц, нульова
   групова затримка проти каузального `lfilter`, guard недопустимої смуги та
   входу, коротшого за `padlen`.

5. **test_grms.py** (6 tests) — Grms проти аналітичних еталонів
   (синус → 1/√2), NaN-вхід, порожній вхід.

6. **test_iri.py** (17 tests) — коефіцієнти Eq.3 та Eq.4/5/6 закріплені
   літералами, raw-vs-clipped контракт, NaN замість вигаданого значення
   при `n < fs*2` та порожній смузі, контракт одиниць (g, не м/с²),
   зв'язок `band_power_sqrt = mean_psd_sqrt * sqrt(ширина смуги)`.

7. **test_anomaly.py** (9 tests) — поріг по модулю, distress-вікна ±0.5 с,
   обрізання на краях масиву, поширення NaN у Grms/Welch.

8. **test_segmentation.py** (14 tests) — `seg_id = floor(s/100)` на межі 100.0,
   guard `n >= fs*2`, Welch на найдовшому чистому run (без склеювання чанків),
   NaN поза діапазоном швидкості зйомки.

9. **test_artifacts.py** (11 tests) — GeoJSON: порядок `[lon, lat]`, `null`
   замість `NaN`, валідність FeatureCollection; карта: пурпурний `#FF00FF` і
   товща лінія для low-speed сегментів, легенда лише за їх наявності,
   сегменти малюються навіть коли жоден `iri_multi` не визначений.

10. **test_cli.py** (16 tests) — наскрізний `analyze()`: відсутність GPS падає
    з `ValueError` і не пише жодного артефакту, обрізання країв ПІСЛЯ фільтрів
    (перший корисний рядок не несе filtfilt-транзієнта), distress removal лише
    для PSD, застосування band-pass до метрик, детермінізм, звіт документує
    реально виконані коефіцієнти.

11. **test_low_speed_policy.py** (42 tests) — політика `--low-speed-policy`:
    поріг рівно 20 км/год (строга нерівність), матриця з 4 політик, інваріант
    «`iri_multi` лишається NaN за будь-якої політики», `events_per_km` (зокрема
    guard на сегменті нульової довжини), `ignore` виключає рядки з CSV/GeoJSON/
    карти, але звіт їх рахує, і повністю low-speed запис усе одно дає повний
    набір артефактів.

**Всі тести:** 163/163 PASS (runtime ~23 секунди)

### Determinism checklist

- [x] Fixed random seed (`tests/conftest.py`, фікстура `rng`)
- [x] Reproducible filters (filtfilt, zero-phase)
- [x] No external API calls (offline обробка)
- [x] Fixed parameters (f_low, f_high, threshold)
- [x] Unit tests для кожної функції
- [x] Наскрізний тест побайтової відтворюваності двох запусків

---

## Висновки

**Новий пайплайн реалізує:**
1. ✅ Orientation correction (gravity alignment + GPS heading)
2. ✅ Distance-based 100m segmentation
3. ✅ ISO 2631-1 compliant metrics (Grms, PSD)
4. ✅ Multi-method IRI (Eq.3 PSD, Eq.4-6 vehicle)
5. ✅ Threshold anomaly detection (10 m/s²)
6. ✅ Sampling compliance monitoring (dx ≤ 0.3 m)
7. ✅ Deterministic pipeline (163 tests)

**Ключові відмінності від legacy:**
- Gravity removal → Grms lower by 5.6x
- Distance segmentation → apples-to-apples comparison
- Uniform grid → PSD possible
- GPS heading → контроль якості GPS (маска `heading_valid`)

**Validation:** Spearman ρ = 0.783 → новий пайплайн зберігає roughness patterns legacy
(результат прогону STAGE 2; скрипт `tools/compare_runs_v2.py` та каталог
`out/comparison/` видалені разом із legacy-кодом, тому з поточного дерева це число
не переобчислюється)

**Наступні розділи:**
- [03_methods_legacy_pipeline.md](03_methods_legacy_pipeline.md) — legacy підхід
- [05_results_legacy_vs_new.md](05_results_legacy_vs_new.md) — числові результати

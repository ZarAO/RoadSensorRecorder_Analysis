# 01 — PLAN STRUCTURE (UNIFIED)

Це покрокова інструкція для GitHub Copilot (VS Code), щоб він:
- зробив аудит репозиторію,
- реалізував орієнтаційну корекцію,
- реалізував IRI (m/km) як у книзі,
- додав vehicle classification (LEV/DSD/GENERIC),
- зробив 100 м сегментацію,
- згенерував артефакти і тести.

---

## 0) Жорсткі обмеження
1) **No browsing**: не використовувати інтернет/документацію зовні.
2) “Book Canon” брати ТІЛЬКИ з `02_FORMULAS_TEST_MAP_UNIFIED.md`.
3) Усе інше — або:
   - витягнути з наявного коду/даних в репозиторії,
   - або додати як **Engineering Addition** (з тестами).

---

## 1) Аудит поточного стану (1-й крок, без змін логіки)
### 1.1 Запуск і фіксація baseline
- Запусти `python main.py` на наявному CSV в `data/`.
- Збережи baseline артефакти в `out/baseline_<date>/`.
- Зафіксуй:
  - fs акселя/gyro,
  - наявність GPS,
  - поточні метрики.

### 1.2 Виявити головні технічні проблеми (обовʼязково описати в report.md)
- чи змішуються ряди різних сенсорів в один time-series (ffill/bfill),
- чи є рівномірний `dt` для PSD,
- чи є сегментація саме по 100 м,
- чи є IRI в m/km (а не proxy),
- чи є orientation-корекція.

---

## 2) Нова архітектура (additive refactor)
### 2.1 Структура пакета
Додай пакет:
- `road_quality_analyzer/`
  - `io/` (читання CSV, розділення по сенсорах)
  - `preprocessing/` (ресемплінг, GPS distance, speed)
  - `orientation/` (gravity alignment, heading, a_perp)
  - `metrics/` (Grms, PSD, IRI)
  - `segmentation/` (100 м сегменти)
  - `anomaly/` (threshold_10ms2, rf(optional), mad(optional))
  - `reporting/` (CSV/GeoJSON/HTML map/plots/report)
  - `cli.py` (entry point)

Legacy:
- `main.py` має або викликати новий CLI (за замовчуванням), або мати прапорець `--legacy`.

---

## 3) Інгест даних (строго)
### 3.1 Розділення потоків
CSV має містити записи різних сенсорів. Розділити на таблиці:
- Accelerometer: (t, ax, ay, az)
- Gyroscope: (t, gx, gy, gz)
- Location/GPS: (t, lat, lon)

Заборонено:
- ffill/bfill аксель значень “через” GPS рядки.

### 3.2 Уніфікація часу
- з ms → s
- відсортувати по t
- перевірити монотонність

---

## 4) Препроцесинг та distance-domain (ключове)
### 4.1 Uniform time grid для акселя
- `dt = median(diff(t_accel))`
- побудувати `t_grid`
- інтерполювати `ax,ay,az` на `t_grid` (linear)
- зберегти маску валідності

### 4.2 GPS distance + speed
- cumulative distance `s(t_gps)` через haversine або ENU-апроксимацію
- інтерполювати `s(t)` на `t_grid`
- speed `v(t) = ds/dt` (smoothed)

### 4.3 Resample у домені відстані
- побудувати рівномірну сітку `s_grid` з кроком `distance_grid_step_m`
- інтерполювати `a_vertical(t)` та `speed(t)` на `s_grid`
- це основа для 100 м сегментації “як у книзі”.

---

## 5) Orientation-корекція (обовʼязково, детально)
Реалізувати за математикою `02_FORMULAS...` (Engineering Additions B3):
1) оцінити `g_hat(t)` low-pass фільтром,
2) побудувати quaternion/матрицю `R(t)` для вирівнювання gravity,
3) отримати `a_lin_world(t)` та `a_vertical(t)`,
4) з GPS heading отримати `a_perp(t)` (перпендикуляр до руху),
5) обробити stop-and-go: якщо `speed < heading_min_speed`, `a_perp` = NaN + маска.

Тести:
- синтетичний сигнал: беремо “істинне” вертикальне прискорення, обертаємо довільним roll/pitch, перевіряємо що після корекції `a_vertical` відновлюється з малим RMSE.
- перевірка норми gravity-вектора.

---

## 6) Метрики roughness та IRI (m/km)
### 6.1 Grms
- реалізувати `Grms` по `a_vertical_g` (RMS) згідно `02`.

### 6.2 PSD → IRI (Eq.2–3)
- band-pass (0.5–6 Hz) підтримати
- Welch PSD
- `sqrtPSD = sqrt(band_power)`
- IRI через Eq.3: `IRI = 0.774*sqrtPSD - 0.825`

Важливо:
- перед PSD застосувати “distress removal” (виключення вікон біля аномалій), бо Eq.3 в книзі наведено “after removing the effect of distress”.

### 6.3 Multi-linear IRI (Eq.4–6) + vehicle classification
- `vehicle_type`:
  - LEV → Eq.4
  - DSD → Eq.5
  - GENERIC → Eq.6
- `Speed` використовувати в **км/год** (segment mean)
- `Npeop, Stif, DampF, TyreS` брати з конфігу
- wheel size зберігати як метадані, не використовувати в формулах.

---

## 7) Сегментація 100 м (як у книзі)
- у домені `s_grid`: сегменти [0..100), [100..200), ...
- для кожного сегмента:
  - lat/lon репрезентативні (середина/медіана GPS)
  - mean speed
  - valid_ratio
  - Grms
  - sqrtPSD
  - IRI_psd
  - IRI_multi
  - anomaly_count

---

## 8) Sampling compliance report (книга)
- оцінити `fs_accel`
- для кожного семпла: `dx = v/fs`
- порахувати частку `dx≤0.3 m`
- відобразити в `report.md` разом з рекомендаціями 80–120 Hz

---

## 9) Anomaly / defects
Мінімум два режими:
1) `threshold_10ms2` (Book Canon): `a_vertical > 10 m/s²`
2) `rf` (книга): фічі `a_vertical, a_perp, speed` + moving average (реалізувати, але дозволити вимикати якщо немає даних/міток)

Додатково можна залишити `mad_peaks` як опцію.

---

## 10) Артефакти (детерміновані)
- `segments.csv` (всі сегменти)
- `roughness.geojson` (лінія/полігони сегментів)
- `events.geojson` (точки аномалій)
- `segments_map.html` (folium)
- `plots/` (графіки по відстані)
- `report.md` (пояснення, параметри, sampling compliance, топ-10 найгірших сегментів)

---

## 11) Покриття тестами та якість
- unit tests: haversine/ENU, orientation, PSD scalar, segmentation
- lint/typing бажано, але не блокер
- не ламати `python main.py`

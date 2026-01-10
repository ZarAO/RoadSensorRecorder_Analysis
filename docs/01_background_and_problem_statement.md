# 01 — Проблематика та постановка задачі

## Зміст
1. [Вступ: Road roughness як критичний показник](#вступ)
2. [IRI — International Roughness Index](#iri---international-roughness-index)
3. [Smartphone-based системи: Class III response-type](#smartphone-based-системи)
4. [Обмеження сенсорів та GPS](#обмеження-сенсорів-та-gps)
5. [Чому необхідні orientation correction та distance-domain](#чому-необхідні-corrections)
6. [Структура сенсорних даних у проєкті](#структура-даних)

---

## Вступ

**Road roughness (шорсткість дорожнього покриття)** — це ключова характеристика якості доріг, що впливає на:
- **Безпеку руху:** нерівності призводять до втрати керованості, збільшення гальмівного шляху
- **Комфорт пасажирів:** вібрації та удари погіршують комфорт, знижують продуктивність водіїв
- **Витрати на експлуатацію:** передчасний знос підвіски, шин, паливні витрати через збільшення опору руху
- **Планування ремонтів:** об'єктивні метрики дозволяють пріоритизувати ділянки, що потребують ремонту

### Традиційні методи вимірювання

**Профілометри (profilometers):** спеціалізовані дорожні лабораторії з лазерними датчиками, що вимірюють профіль дороги з точністю до міліметрів. **Недоліки:**
- Висока вартість обладнання (десятки-сотні тисяч доларів)
- Низька частота замірів (1-2 рази на рік для основних магістралей)
- Неможливість масового покриття другорядних доріг

**Response-type системи (акселерометри на авто):** встановлені на транспортні засоби акселерометри, що вимірюють відгук підвіски на нерівності. Класифікуються за точністю:
- **Class I:** професійні системи, каліброваніна reference segments (похибка < 5%)
- **Class II:** комерційні fleet systems (похибка 5-15%)
- **Class III:** consumer-grade sensors, включно з смартфонами (похибка 15-30%)

### Проблема

Більшість міських та сільських доріг **не мають регулярного моніторингу** через високу вартість традиційних методів. Smartphone-based підхід дозволяє:
- **Масштабованість:** кожен власник смартфону — потенційний сенсор
- **Висока частота:** daily/weekly coverage замість annual
- **Низька вартість:** використання існуючих пристроїв

Але Class III системи мають **серйозні методологічні виклики**, які адресує цей проєкт.

---

## IRI — International Roughness Index

### Визначення

**IRI (m/km)** — стандартизований показник шорсткості дороги, що представляє **кумулятивне вертикальне переміщення підвіски** на кілометр шляху при русі зі сталою швидкістю (зазвичай 80 km/h).

### Референтне визначення (Quarter-car model)

Згідно з `agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md` **Eq.1**:

```
IRI = (1/L) * ∫[0, L/V] |V₁(t) - V₂(t)| dt
```

де:
- **V₁** — вертикальна швидкість sprung mass (кузов автомобіля)
- **V₂** — вертикальна швидкість unsprung mass (колесо/вісь)
- **L** — довжина вимірюваної ділянки (м)
- **V** — середня швидкість руху (м/с)

**Вхідні дані для quarter-car моделі:**
- **Wheel track elevation profile h(s)** — висота дорожнього профілю як функція відстані
- Параметри підвіски: жорсткість пружин, коефіцієнти демпфування

**Проблема для смартфонів:** Quarter-car модель **вимагає знати профіль дороги h(s)**, якого у смартфонному акселерометрі немає. Тому quarter-car підхід:
- Реалізовано як **опціональний** (якщо користувач надає зовнішній road profile)
- **Основний метод IRI** у цьому проєкті — через **PSD-based regression** (Eq.2-3) та **vehicle-specific regression** (Eq.4-6)

### Класифікація доріг за IRI

| IRI (m/km) | Класифікація | Характеристика |
|------------|--------------|----------------|
| 0 - 2 | EXCELLENT | Ідеальні автобани, новий асфальт |
| 2 - 4 | GOOD | Якісні міські дороги, незначний знос |
| 4 - 6 | FAIR | Помірний знос, потрібен моніторинг |
| 6 - 8 | POOR | Значний знос, плановий ремонт |
| 8+ | VERY POOR | Критичний стан, термінові заходи |

**Приклад з проєкту:** новий пайплайн дав **IRI_multi = 3.78 m/km** → класифікація **GOOD** (за World Bank standards).

---

## Smartphone-based системи

### Class III response-type characteristics

**Наш підхід належить до Class III response-type систем**, що означає:

#### 1. Response-type (на відміну від profilometer)
- Вимірюємо **відгук (response)** транспортного засобу на нерівності, а не сам профіль дороги
- Акселерометр фіксує прискорення кузова, а не абсолютну висоту профілю
- Потребує **calibration** для перетворення acceleration → IRI

#### 2. Class III precision tier
**Характеристики:**
- **Sensor quality:** MEMS акселерометри у смартфонах (bias drift ~0.01 m/s², noise ~0.001 m/s²)
- **Mounting:** нефіксоване кріплення (тримач, кишеня, сидіння) → змінна орієнтація
- **Sampling:** fs = 50-100 Hz (залежить від моделі смартфону та OS)
- **GPS quality:** civilian GPS (похибка 3-10 м у міській забудові)
- **Expected error:** 15-30% порівняно з reference IRI

**Порівняння з Class I/II:**
- **Class I:** професійні інерціальні системи з RTK-GPS, fixed mounting → похибка < 5%
- **Class II:** комерційні fleet sensors з calibration → похибка 5-15%
- **Class III (наш):** consumer smartphones → похибка 15-30%, але **масштабованість**

### Переваги smartphone підходу

1. **Масштабованість (scalability):**
   - Billions of smartphones worldwide
   - Crowdsourcing potential (кожен водій = sensor node)
   - Можливість покриття 100% доріг міста за місяць

2. **Економічність:**
   - Нульові витрати на обладнання (використання існуючих пристроїв)
   - Мінімальні витрати на обробку (cloud computing)

3. **Висока частота оновлення:**
   - Daily/weekly updates замість annual surveys
   - Real-time моніторинг погіршення стану

4. **Гнучкість:**
   - Різні типи транспорту (легкові, вантажні, автобуси)
   - Різні швидкості та умови (міські, заміські)

### Недоліки та виклики

1. **Variability (мінливість):**
   - Phone mounting position (dashboard vs pocket vs seat)
   - Phone orientation (portrait vs landscape, tilt angles)
   - Vehicle suspension characteristics (sedan vs SUV vs van)

2. **Sensor limitations:**
   - Акселерометр вимірює у **phone body frame**, а не world frame
   - Gravity contamination (9.8 m/s² >> road-induced 0.1-1.0 m/s²)
   - Bias drift та temperature sensitivity

3. **GPS limitations:**
   - Multipath errors у міських каньйонах (buildings)
   - Low sampling rate (1-10 Hz)
   - Speed estimation errors → dx compliance issues

---

## Обмеження сенсорів та GPS

### Акселерометр (MEMS)

**Що вимірює:** `a_raw(t) = a_linear(t) + g(t)` (м/с²)

де:
- **a_linear** — лінійне прискорення транспортного засобу
- **g** — гравітаційне прискорення у phone body frame (~9.8 m/s²)

**Проблема 1: Gravity contamination**
```
Смартфон під кутом 10° → g_z ≈ 9.8*cos(10°) = 9.66 m/s²
Road-induced a_vertical ≈ 0.5 m/s² (typical для GOOD roads)

Signal-to-noise ratio: 0.5 / 9.66 ≈ 5%
```

Якщо просто взяти `a_z` без correction → отримаємо **переважно gravity**, а не road roughness.

**Проблема 2: Phone orientation невідома**
- User кладе телефон як зручно (portrait/landscape, face up/down)
- Orientation змінюється при поворотах, гальмуванні
- Неможливо знати "вертикальну" вісь без обчислень

**Проблема 3: Sensor noise and bias**
- **Noise:** ~0.001 m/s² RMS (білий шум)
- **Bias drift:** повільна зміна нуля (~0.01 m/s²/годину при зміні температури)
- **Quantization:** 12-16 bit ADC → обмежена роздільна здатність

### GPS

**Що надає:** `(lat, lon, altitude, speed, heading)` на частоті 1-10 Hz

**Проблема 1: Low sampling rate**
```
GPS: 1 Hz (оновлення кожну секунду)
Accel: 50-100 Hz (50-100 оновлень на секунду)

При швидкості 50 km/h = 13.9 m/s:
Distance between GPS points: 13.9 m

Акселерометр "бачить" event на відстані 0.3 м,
але GPS прив'язує його до 13.9 м bin → spatial aliasing
```

**Проблема 2: Position errors**
- **Civilian GPS:** 3-10 м absolute error (без DGPS/RTK)
- **Urban canyon effect:** multipath від будівель → errors до 30 м
- **Тунелі/мости:** signal loss → gaps у траєкторії

**Проблема 3: Speed/heading inaccuracies**
- GPS speed розрахований з delta positions → похибка ~0.5 m/s
- Heading невизначений при малих швидкостях (< 1 m/s)
- Filtering delays: smoothing фільтри вносять lag

### Синхронізація

**Проблема:** акселерометр та GPS працюють **асинхронно**

```
Timestamp alignment:
Accel: [100.023, 100.043, 100.062, 100.081, ...]  (50 Hz)
GPS:   [100.0,   101.0,   102.0, ...]              (1 Hz)

Інтерполяція GPS → accel потребує filtering
```

У проєкті використовуємо:
- **Uniform time grid:** resample accel на рівномірну сітку
- **Linear interpolation:** GPS lat/lon на accel timestamps
- **Distance grid:** cumulative distance з Haversine formula

---

## Чому необхідні corrections

### 1. Orientation Correction (критично!)

**Без correction:**
```python
# Legacy підхід (modules/preprocessing.py)
rmsa = np.sqrt(np.mean(accel_z**2))  # body-frame Z-axis
```

**Проблема:**
- `accel_z` = gravity component + road-induced vertical
- Якщо телефон під кутом → gravity "розмазується" на всі осі
- RMSA включає gravity noise → завищений у 5-10 разів

**Приклад з проєкту:**
- Legacy RMSA = 0.3335 (body-frame, змішаний з gravity)
- New Grms = 0.0590 g (world-frame, gravity видалений)
- **Різниця: 5.6x**

**З correction (новий пайплайн):**
1. Estimate gravity vector з low-pass filter (0.25 Hz cutoff)
2. Обертання до world frame (quaternion rotation)
3. Subtract gravity → `a_linear_world`
4. Взяти `a_vertical = a_linear_world.z` (чисто вертикальна компонента)

**Результат:** метрика **Grms** відображає реальні вібрації від дороги, а не phone tilt.

### 2. Distance-Domain Segmentation

**Проблема time-based segments:**

```
Legacy: сегменти за часом (наприклад, кожні 10 секунд)

Сценарій 1 (швидка дорога, 80 km/h):
10 сек → 222 м відстані

Сценарій 2 (міський traffic, 20 km/h):
10 сек → 55 м відстані

→ Неможливо порівнювати сегменти (різна spatial resolution)
```

**Distance-based segments (новий пайплайн):**
- Кожен сегмент = **рівно 100 м** (незалежно від швидкості)
- Дозволяє порівнювати різні проїзди, різні умови
- Згідно з `02_FORMULAS` **Eq.B7**: `seg_id = floor(s / 100)`

**Приклад:**
- Legacy: 1799 time-based segments (variable length 10-300 м)
- New: 153 distance-based segments (exactly 100 м кожен)
- **100m-aligned comparison:** 152 overlap segments для validation

### 3. Sampling Compliance (dx ≤ 0.3 m)

**Вимога з `02_FORMULAS` Eq.A4:**
> sampling interval уздовж відстані не більше 300 мм

**Розрахунок:**
```
dx(t) = v(t) / fs_accel

Приклад:
v = 50 km/h = 13.9 m/s
fs = 50 Hz
→ dx = 13.9 / 50 = 0.278 м < 0.3 м ✓

Проблема:
v = 80 km/h = 22.2 m/s
fs = 50 Hz
→ dx = 22.2 / 50 = 0.444 м > 0.3 м ✗ (non-compliant)
```

**Чому критично:**
- Nyquist spatial frequency: потрібно ≥2 samples на найменшу wavelength
- Для urban roads (wavelength ~0.5-1.0 м) → dx < 0.3 м забезпечує adequate sampling
- **Non-compliance → aliasing:** пропускаємо короткі нерівності (potholes)

**Рішення у проєкті:**
1. Compute dx для кожного sample
2. Report share of distance with `dx ≤ 0.3 m` у `table_metrics_overall.csv`
3. Mask non-compliant segments у ML features (опціонально)

### 4. GPS Heading для a_perp

**Навіщо:** horizontal acceleration perpendicular to travel direction

**Застосування:**
- **Anomaly detection:** potholes/bumps мають a_perp spike (lateral jolt)
- **Turn detection:** різкі зміни heading → exclude від roughness metrics
- **ML features:** a_perp + a_vertical → краще розпізнавання distress types

**Обчислення (Eq.B2 з `02_FORMULAS`):**
```python
# GPS coordinates → ENU (local East-North-Up)
Δx = R * cos(lat0) * (lon[i] - lon[i-1])
Δy = R * (lat[i] - lat[i-1])

# Heading unit vector
h_hat = normalize([Δx, Δy, 0])

# Perpendicular у горизонтальній площині
p_hat = normalize(cross([0,0,1], h_hat))

# Projection
a_perp = dot(a_linear_world, p_hat)
```

**Проблема stop-and-go:** при v < 1 m/s heading невизначений → mask a_perp

---

## Структура даних

### Вхідний CSV (sensor log)

**Приклад:** `data/sensor_data_20250729_163334.csv`

**Формат:**
```
Time,Type,X,Y,Z,Latitude,Longitude
1722261414023,ACCEL,0.2345,-0.1234,9.8765,,
1722261414043,ACCEL,0.2401,-0.1198,9.8812,,
...
1722261414000,GPS,,,,,50.450123,30.523456
1722261415000,GPS,,,,,50.450234,30.523567
```

**Колонки:**
- **Time:** Unix timestamp у мілісекундах
- **Type:** `ACCEL` (3-axis accelerometer) або `GPS` (location)
- **X, Y, Z:** акселерометр у м/с² (phone body frame) або пусті для GPS
- **Latitude, Longitude:** GPS coordinates у градусах або пусті для ACCEL

**Характеристики нашого датасету:**
- **Distance:** 15.14 km
- **Duration:** ~30 хвилин
- **Accel samples:** 94702 (fs ≈ 52.6 Hz після uniform grid)
- **GPS samples:** 1799 (~1 Hz)

### Вихідні артефакти

**1. road_segments.csv**
```csv
seg_id,s_start,s_end,iri_multi,iri_psd,grms,mean_speed_kmh,valid_ratio,anomaly_count
0,0.0,99.9,7.67,3.45,0.128,34.8,0.98,0
1,100.0,199.9,3.60,2.12,0.054,41.2,1.00,0
...
```

**Metrics:**
- **iri_multi:** IRI з Eq.4-6 (vehicle-specific regression), м/км
- **iri_psd:** IRI з Eq.3 (PSD-based), м/км (може бути < 0 якщо не калібрований)
- **grms:** RMS вертикального прискорення, g
- **mean_speed_kmh:** середня швидкість на сегменті
- **valid_ratio:** частка valid samples (GPS available, heading defined)
- **anomaly_count:** кількість samples з |a_vertical| > 10 m/s²

**2. roughness.geojson**
- LineString features для кожного сегмента
- Properties: всі метрики + geometry
- Можна відкрити у QGIS/Kepler.gl/Folium

**3. report.md**
- Текстовий звіт з summary statistics
- Acceptance criteria check (21/21)
- Plots references

**4. Plots (PNG, 150 DPI)**
- `plot_grms_profile.png` — Grms vs distance
- `plot_iri_profile.png` — IRI_multi vs distance
- `plot_speed_profile.png` — Speed vs distance
- `plot_psd_heatmap.png` — PSD spectrogram (frequency vs distance)

---

## Висновки

### Ключові проблеми, що адресує проєкт:

1. **Gravity contamination** → **Orientation correction** (Eq.B3)
2. **Phone mounting variability** → **Quaternion rotation** до world frame
3. **Time-domain bias** → **Distance-based 100m segments**
4. **Sampling non-compliance** → **dx ≤ 0.3 m monitoring** + reporting
5. **GPS inaccuracies** → **Haversine distance** + **heading smoothing**
6. **IRI estimation without road profile** → **PSD regression (Eq.3)** + **vehicle regression (Eq.4-6)**
7. **Anomaly detection** → **Threshold 10 m/s²** (Eq.A5) + **a_perp features**

### Validation результат:

**Spearman ρ = 0.783** (IRI_multi vs legacy RMSA, p < 0.0001)
- Новий пайплайн **зберігає** roughness detection patterns legacy
- Але **додає** orientation correction, ISO compliance, distance-based segmentation
- **Trade-off:** складніша обробка ↔ вища валідність

**Наступні розділи:**
- [02_methods_new_pipeline.md](02_methods_new_pipeline.md) — детальний алгоритм
- [03_methods_legacy_pipeline.md](03_methods_legacy_pipeline.md) — legacy підхід
- [05_results_legacy_vs_new.md](05_results_legacy_vs_new.md) — числові результати

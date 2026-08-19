# 06 — Загрози валідності та обмеження

## Зміст
1. [Phone Mount Variability](#phone-mount-variability)
2. [Sampling Compliance](#sampling-compliance)
3. [Speed Variability](#speed-variability)
4. [GPS Errors](#gps-errors)
5. [Orientation Estimation](#orientation-estimation)
6. [Calibration Mismatch](#calibration-mismatch)
7. [Vehicle Parameters](#vehicle-parameters)
8. [Mitigations Implemented](#mitigations-implemented)
9. [Remaining Risks](#remaining-risks)

---

## Phone Mount Variability

### Проблема

**Mounting position affects measurements:**
- **Dashboard holder:** rigid, minimal vibration dampening
- **Cup holder:** semi-rigid, phone може обертатися
- **Pocket/seat:** soft, high dampening, непередбачувана орієнтація

**Impact на metrics:**
```
Rigid mount (dashboard):
→ Phone vibrations ≈ vehicle vibrations
→ Grms accurately reflects road roughness

Soft mount (pocket):
→ Fabric dampening reduces high-frequency vibrations
→ Grms systematically lower (underestimation)
→ Phone може обертатися → gravity alignment errors
```

**Quantification (estimated):**
- Dashboard vs pocket: **20-40% difference** у Grms
- Tilt variability: **±5-15°** → gravity residuals ~0.1-0.3 m/s²

### Threat Level: **HIGH**

**Why critical:**
- Smartphone users зазвичай НЕ документують mounting method
- Cross-device/cross-user comparisons biased
- Absolute IRI values unreliable (only relative comparisons valid)

---

## Sampling Compliance

### Проблема (dx ≤ 0.3 m requirement)

**From Eq.A4 (`02_FORMULAS`):**
> sampling interval уздовж відстані не більше 300 мм

**Calculation:**
```
dx(t) = v(t) / fs_accel

Our dataset:
fs = 52.6 Hz
v_max = 67 km/h = 18.6 m/s

dx_max = 18.6 / 52.6 = 0.35 m > 0.3 m  ✗ (non-compliant)
```

**Impact:**
- **Spatial aliasing:** пропускаємо короткі wavelengths (< 0.7 м)
- **Potholes underdetection:** typical pothole width 0.3-0.5 м → marginal
- **PSD bias:** high-frequency content underestimated

**Quantification** (поточний прогін: середня `dx_le_03_share` по повних сегментах
= 0.795; у 41 зі 150 сегментів частка < 1):
```
Частка dx ≤ 0.3 m рахується пайплайном:
- по сегментах — колонка dx_le_03_share у road_segments.csv
  (експортується і в properties roughness.geojson)
- по всьому запису — секція "Sampling Compliance" у report.md
  (median dt, mean dx, P95 dx, share dx≤0.3m, прапорець fs у смузі 80-120 Hz)
```

### Threat Level: **MODERATE**

**Mitigations possible:**
- Mask segments with high speed (> 57 km/h @ 52.6 Hz)
- Require fs >= 80 Hz для highway measurements
- Use interpolation (але artificial, not recommended)

---

## Speed Variability

### Проблема (stop-and-go)

**IRI definition assumes constant speed:**
- Quarter-car model (Eq.1) розрахований для V = const (зазвичай 80 km/h)
- Vehicle regression (Eq.6) має speed term, але assumes smooth speed

**Our dataset** (поточний прогін, 150 повних сегментів):
- Середня з посегментних `mean_speed_kmh`: 41.9 km/h
- Range: 4.4–74.7 km/h
- **Stop-and-go segments:** v < 1 m/s → GPS heading undefined (маскується)

**Impact:**
- **IRI_multi underestimation** на високих швидкостях (Eq.6 має `-0.06*Speed` term)
- **Distance grid errors** при зупинках (GPS noise amplified)
- **Heading undefined** → a_perp features invalid

**Quantification:**
```
Speed variability: σ = 16.7 km/h між сегментами
IRI_multi (повні сегменти): mean 2.99, σ 1.45, max 6.72 m/km
Поза діапазоном зйомки 20-100 km/h: 19 зі 150 сегментів → IRI = NaN
```

### Threat Level: **MODERATE**

**Best practices:**
- Filter segments with `dx_le_03_share < 0.8` (просторова дискретизація не відповідає вимозі)
- Сегменти поза діапазоном швидкості зйомки вже позначені `speed_valid = False`,
  і для них `iri_multi` = NaN (Eq.3 speed-члена не має, тому `iri_psd` зберігається)
- **Median speed per segment — НЕ реалізовано:** `segment_100m.py` рахує лише
  `mean_speed_mps` / `mean_speed_kmh`, і саме середня швидкість іде у speed-член
  Eq.6. Зупинка всередині сегмента зміщує середнє сильніше за медіану — це
  відкритий пункт (див. [07](07_future_work_roadmap.md))
- Acknowledge in paper: "urban mixed-traffic conditions"

### Парадокс низької швидкості (low-speed paradox)

**Найгірші ділянки дають найменш валідний вимір.** Дорога, розбита настільки, що
швидше за ~5–20 км/год нею фізично не проїхати, — це саме та ділянка, заради якої
робиться зйомка. І саме там акселерометричний IRI не працює:

- частота збудження підвіски `f = v / λ` (λ — довжина хвилі нерівності), тому
  фіксована смуга 0.5–6 Hz, у якій визначені Eq.3 і Grms, «бачить» різні
  довжини хвиль залежно від швидкості:

  | Швидкість | Смуга 0.5–6 Hz відповідає λ |
  |-----------|------------------------------|
  | 80 км/год (22.2 м/с) | 3.7–44 м — саме діапазон, у якому визначений IRI |
  | 20 км/год (5.6 м/с) | 0.9–11 м — нижня межа зйомки |
  | 6.3 км/год (1.7 м/с) | 0.3–3.5 м — це вже текстура, а не рівність |

  На 6 км/год довгохвильова складова, яка й формує IRI, зміщується **під**
  смугу вимірювання, а в самій смузі лишається короткохвильовий вміст;
- Eq.4/5/6 містять speed-член і калібровані на 30/50/80 км/год, робочий діапазон —
  20–100 км/год. Нижче нього формула просто не визначена;
- guidebook класифікує запис зі швидкістю < 20 км/год як **incomplete dataset**.

Тобто чим гірша дорога, тим менше в неї шансів отримати число — це не помилка
реалізації, а межа методу. У записі 2025-07-29 це 19 зі 152 сегментів.

**Що зроблено (не приховано, а марковано):**
- `needs_class12_survey = True` для кожного такого сегмента: потрібен прилад
  **класу 1/2** (лазерний профілометр), а не смартфон;
- `low_speed_class` — мітка за політикою `--low-speed-policy`
  (`very-poor` / `poor` / `invalid` / `ignore`), причому **числовий `iri_multi`
  лишається `NaN` за будь-якої політики**: мітка ніколи не підміняє вимір;
- `events_per_km` — пороговий детектор подій працює й на низькій швидкості, тому
  для цих ділянок саме він служить індикатором стану;
- на карті такі сегменти пурпурові (`#FF00FF`, товща лінія) з окремою легендою;
- сама стійко низька швидкість — теж індикатор стану (guidebook Eq.10/11:
  FFS/V50 vs IRI, значущо для IRI > 7 м/км), але як **окреме** свідчення, а не
  як підставлене замість IRI число.

### Threat Level: **HIGH** (для найгірших ділянок — метод там не вимірює)

---

## GPS Errors

### Проблема 1: Position Accuracy

**Civilian GPS:** ±3-10 м absolute error  
**Urban canyon:** до ±30 м (multipath)

**Impact на distance:**
```
Haversine between noisy points:
True distance: 100.0 m
GPS distance: 95.2 m або 104.8 m (±5% error)

Cumulative over 15 km:
→ Total distance error: ±750 m (5% of 15000 m)
```

**Our dataset:**
- Reported distance: 15140.7 m
- True distance (Google Maps): [unknown, потрібна manual verification]
- Estimated error: ±2-3%

### Проблема 2: Sampling Rate

**GPS: 1 Hz** (оновлення кожну секунду)  
**Accel: 52.6 Hz**

**At v = 50 km/h = 13.9 m/s:**
```
GPS updates every 13.9 m
Accel samples every 0.26 m

→ 53x більше accel samples, але прив'язані до coarse GPS grid
→ Linear interpolation smooths GPS noise, але втрачає sharp turns
```

### Threat Level: **MODERATE**

**Mitigations:**
- Згладжування cumulative distance ковзним середнім ~1 с (`uniform_filter1d`)
  ДО чисельного диференціювання швидкості (already implemented)
- Report distance uncertainty в metadata
- Use heading only when v > 1 m/s (already masked)

---

## Orientation Estimation

### Проблема (Gravity Alignment Assumptions)

**Assumption 1: Low-pass cutoff = 0.3 Hz sufficient**
```
Gravity LPF at 0.3 Hz → assumes phone rotates slower than 0.3 Hz

But:
- Sharp turn: phone може tilted > 15° за 0.5 sec → 2 Hz rotation
- Pothole hit: phone може bounce → transient gravity spikes

→ LPF "розмиває" gravity estimation during rapid movements
```

**Assumption 2: Linear acceleration << gravity**
```
Typical road: a_linear ~ 0.5 m/s²
Gravity: g ~ 9.8 m/s²

Ratio: 0.5 / 9.8 ≈ 5%

Quaternion rotation працює if rotation slow,
але fails if a_linear >> g (наприклад, harsh braking 8 m/s²)
```

**Quantification (residual gravity):**
```
After alignment:
|a_vertical| should be ~ 0-1 m/s² (pure road vibrations)

Observed:
max |a_vertical| = 3.5 m/s² (у top segments)

Possible causes:
- Residual gravity (phone tilted during sharp turn)
- True road distress
- Sensor noise

→ Cannot distinguish without gyroscope fusion
```

### Threat Level: **MODERATE-HIGH**

**Impacts:**
- **Grms overestimation** у segments з sharp turns (residual gravity)
- **a_perp errors** якщо heading змінюється швидше за GPS updates
- **IRI bias** (Eq.6 uses Grms → propagated error)

**Mitigations implemented:**
- Low-pass at 0.3 Hz (steep Butterworth 4th order, zero-phase filtfilt)
- Quaternion rotation (numerically stable)
- Heading masking at low speed (v < 1 m/s)

**Remaining risks:**
- No gyroscope fusion (gyro дав би true rotation rate)
- No explicit turn detection (sharp curves not excluded)

---

## Calibration Mismatch

### Проблема (Eq.3: IRI_psd)

**From `02_FORMULAS` Eq.3:**
```
IRI = 0.774 * sqrt(PSD) - 0.825  (m/km)
```

**Coefficients A = 0.774, B = 0.825 from book:**
- Калібровані на **specific phone model** (не вказано який)
- **After removing distresses** (filtering applied)
- **Specific vehicle/suspension** (не вказано який)

**Our implementation:**
- Uses book defaults (A, B not recalibrated)
- Applies distress removal (±0.5 s вікно навколо кожної аномалії)
- But: phone/vehicle різні → mismatch

**Impact:**
```
Our dataset:
IRI_psd can be < 0 (negative!)

Example segment:
sqrt(PSD) = 0.5 g
IRI_psd = 0.774 * 0.5 - 0.825 = -0.438 m/km  (invalid)

→ Negative IRI physically meaningless
```

**Quantification** (поточний прогін на `data/sensor_data_20250729_163334.csv`):
- **% повних сегментів з `iri_psd_raw` < 0:** 100% (mean `iri_psd_raw` = -0.81 m/km)
- `iri_psd` кліпається до 0, сире значення зберігається окремою колонкою;
  частка негативних також друкується у `report.md`
- Тобто на цих даних Eq.3 з книжковими коефіцієнтами непридатна як абсолютна
  метрика — це сигнал про калібрування, а не про ідеальну дорогу

### Threat Level: **HIGH** (for IRI_psd absolute values)

**Why IRI_multi used as primary:**
- IRI_multi (Eq.6) has vehicle params → more robust
- IRI_multi always >= 0 (clamped)
- IRI_psd useful for relative comparisons, але NOT absolute

**Future work (P0 priority):**
- Collect ground truth IRI (reference profilometer)
- Calibrate A, B per phone model
- Cross-validate on multiple routes

---

## Vehicle Parameters

### Проблема (Eq.4-6: Simulated Coefficients)

**From `02_FORMULAS` Eq.6 (generic vehicle):**
```
IRI = 50.32*Grms - 0.06*Speed + 0.17*Npeop - 1.86*Stif - 0.90*DampF - 0.78*TyreS + 6.68
```

**Coefficients derived from simulation:**
- **Speed range:** 30, 50, 80 km/h (discrete values)
- **Npeop:** 1-4 (70 kg/person)
- **Stif, DampF, TyreS:** ±20% variations around nominal

**Our defaults:**
```python
npeop = 1      # Single driver
stif = 1.0     # Nominal stiffness
damp_f = 1.0   # Nominal damping
tyre_s = 1.0   # Nominal tyre
```

**Mismatch sources:**
1. **Real vehicle ≠ simulated vehicle:**
   - Sedan vs SUV vs van → різна підвіска
   - Tire pressure, wear → різний tyre_s
   - Load (luggage) → різний effective npeop

2. **Continuous speed vs discrete calibration:**
   - Model trained at [30, 50, 80] km/h
   - Our data: continuous 15-67 km/h → extrapolation

**Impact:**
```
Sensitivity analysis (example):
If stif = 0.8 (softer suspension):
IRI_delta = -1.86 * (0.8 - 1.0) = +0.37 m/km

If npeop = 2 (passenger):
IRI_delta = 0.17 * (2 - 1) = +0.17 m/km

Total uncertainty: ±0.5 m/km (for mean IRI = 3.78 → ±13% error)
```

### Threat Level: **MODERATE** (systematic bias, but consistent)

**Why acceptable for validation:**
- Defaults applied **uniformly** to all segments
- Bias cancels у relative comparisons (segment A vs B)
- Correlation preserved (ρ = 0.783 unaffected by constant bias)

**Future work:**
- Collect vehicle metadata (make/model, tire specs)
- Calibrate per vehicle type
- User input via CLI (--stif, --npeop)

---

## Mitigations Implemented

### ✅ What We Already Did

1. **Orientation correction:**
   - Low-pass 0.3 Hz (gravity estimation)
   - Quaternion rotation (world-frame alignment)
   - **Impact:** Grms 5.6x lower than legacy RMSA → reduced gravity contamination

2. **Distance-based segmentation:**
   - 100 м bins → spatial consistency
   - **Impact:** 99.3% overlap (152/153 segments) → robust comparison

3. **Heading masking:**
   - v < 1 m/s → heading = NaN, a_perp masked
   - **Impact:** Fewer invalid features у ML

4. **Anomaly threshold:**
   - Absolute 10 m/s² (not statistical)
   - **Impact:** на датасеті 2025-07-29 — 0 подій (поріг застосовано до
     gravity-removed вертикалі й не калібрований під цей пристрій, тому
     кількість подій може бути заниженою)

5. **Deterministic pipeline:**
   - Fixed parameters, unit tests (163/163 PASS, 11 файлів)
   - Seed зафіксовано в `tests/conftest.py` (фікстура `rng`); наскрізний тест порівнює
     `road_segments.csv` двох прогонів побайтово
   - **Impact:** Reproducible results

6. **Validation against legacy:**
   - Spearman ρ = 0.783 → preserved ranking
   - **Impact:** Confidence у new metrics

---

## Remaining Risks

### 🔴 High Priority (cannot fully mitigate without external data)

1. **Absolute IRI accuracy:**
   - No ground truth reference
   - **Risk:** IRI_multi may be biased ±1-2 m/km
   - **Mitigation:** Acknowledge in paper, use relative comparisons only

2. **Phone mount variability:**
   - Users don't document mounting
   - **Risk:** 20-40% variance cross-user
   - **Mitigation:** Standardize mounting protocol (future campaigns)

3. **Calibration (Eq.3):**
   - Book defaults A, B may not fit our phone/vehicle
   - **Risk:** на цьому датасеті `iri_psd_raw` < 0 у 100% повних сегментів
   - **Mitigation:** Use IRI_multi as primary (P0: recalibrate A, B)

### 🟡 Moderate Priority (can partially mitigate)

4. **Sampling compliance (dx):**
   - 20-30% segments non-compliant
   - **Risk:** Spatial aliasing, high-freq underestimation
   - **Mitigation:** Report share_dx_le_0_3m, mask high-speed segments

5. **GPS errors:**
   - Distance ±2-3% uncertainty
   - **Risk:** Cumulative error over 15 km
   - **Mitigation:** Use RTK-GPS (future), report uncertainty

6. **Speed variability:**
   - Stop-and-go → IRI assumptions violated
   - **Risk:** IRI underestimation ±0.5 m/km
   - **Mitigation:** Filter segments with `speed_valid = False`

### 🟢 Low Priority (acceptable for current scope)

7. **Vehicle parameters:**
   - Defaults не калібровані per vehicle
   - **Risk:** ±13% systematic bias
   - **Mitigation:** Uniform defaults → bias consistent (OK for relative)

8. **Gyroscope missing:**
   - No sensor fusion → orientation errors у turns
   - **Risk:** Grms overestimation у sharp curves
   - **Mitigation:** Future work (P1: gyro fusion)

---

## Висновки

### Validity Statement

**Internal validity (reproducibility):** ✅ HIGH
- Deterministic pipeline, fixed params, 163 tests

**External validity (generalizability):** ⚠ MODERATE
- Single phone model, single vehicle, single route
- Cannot generalize to all smartphones/vehicles without multi-device validation

**Construct validity (do we measure what we claim):** ⚠ MODERATE-HIGH
- Grms measures vibrations ✅ (ρ = 0.942 vs legacy)
- IRI_multi correlates with roughness ✅ (ρ = 0.783)
- Absolute IRI accuracy unknown ❌ (no ground truth)

### For Scientific Publication

**Must acknowledge:**
1. No ground truth IRI (validation only against legacy proxy)
2. Single-device, single-route dataset (limited generalizability)
3. Eq.3 calibration mismatch (negative IRI_psd possible)
4. Phone mount not controlled (variability source)

**Strengths to emphasize:**
1. Methodological improvements (orientation, distance-domain)
2. Strong correlation preserved (ρ = 0.783, p < 0.0001)
3. Deterministic, reproducible pipeline
4. 100m-aligned comparison (99.3% overlap)

**Наступні розділи:**
- [07_future_work_roadmap.md](07_future_work_roadmap.md) — roadmap для усунення limitations
- [08_user_guide_and_cli_reference.md](08_user_guide_and_cli_reference.md) — practical guide

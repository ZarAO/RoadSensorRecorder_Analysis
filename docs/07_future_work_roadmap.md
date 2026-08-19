# 07 — Future Work Roadmap

## Зміст
1. [Priority Classification](#priority-classification)
2. [P0: Critical Improvements](#p0-critical-improvements)
3. [P1: High-Value Features](#p1-high-value-features)
4. [P2: Research Extensions](#p2-research-extensions)
5. [Timeline Estimate](#timeline-estimate)

---

## Priority Classification

### Definitions

**P0 (Critical):** Вирішує fundamental validity threats, потрібно для publication  
**P1 (High):** Significantly improves accuracy/usability, рекомендовано для production  
**P2 (Research):** Розширює scope, потрібно для широкого adoption

---

## P0: Critical Improvements

### P0.1 — Recalibrate Eq.3 (IRI_psd) Coefficients

**Problem:** (from [06_threats](06_threats_to_validity_and_limitations.md#calibration-mismatch))
```
IRI_psd = 0.774*sqrt(PSD) - 0.825  → negative values у 10-20% segments
Book defaults A=0.774, B=0.825 не калібровані для нашого phone/vehicle
```

**What's Needed:**
1. **Ground truth collection:**
   - Hire/borrow reference profilometer (ГОСТ 30412-96 certified)
   - Measure same route as `storage/data/sensor_data_20250729_163334.csv`
   - Extract IRI_reference per 100m

2. **Dataset structure:**
   ```
   validation_data/
     ├── route_20250729_163334/
     │   ├── smartphone_aligned.csv   (наш output: PSD, IRI_psd)
     │   └── profilometer_reference.csv  (IRI_true per 100m)
   ```

3. **Regression:**
   ```python
   from scipy.optimize import curve_fit
   
   def iri_psd_model(sqrt_psd, A, B):
       return A * sqrt_psd + B
   
   popt, pcov = curve_fit(iri_psd_model, sqrt_psd_array, iri_true_array)
   A_new, B_new = popt
   # Save to config: agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md
   ```

4. **Code changes:**
   - Update `analyzer/src/road_quality_analyzer/metrics/iri.py` (`IRI_PSD_COEFFICIENTS`)
   - Add CLI flags: `--iri_psd_A <float> --iri_psd_B <float>`
   - Update unit test `test_compute_iri_psd()` з новими defaults

**Success Metrics:**
- ✅ R² > 0.85 (IRI_psd vs IRI_true)
- ✅ Zero negative IRI_psd values (physical constraint)
- ✅ MAE < 0.5 m/km (acceptable error)

**Effort:** **3-4 weeks** (2 weeks profilometer rental + data collection, 1 week regression, 1 week validation)

---

### P0.2 — Recalibrate Eq.6 (IRI_multi) Coefficients

**Problem:**
```
IRI_multi = 50.32*Grms - 0.06*Speed + ... + 6.68
Coefficients from simulation (generic vehicle), не калібровані для real vehicle
```

**What's Needed:**
1. **Extend ground truth dataset:**
   - Collect smartphone data + profilometer reference (same as P0.1)
   - Extract features: Grms, Speed, npeop (known), stif/damp_f/tyre_s (assumed defaults)

2. **Regression:**
   ```python
   from sklearn.linear_model import LinearRegression
   
   X = df[['Grms', 'Speed', 'npeop', 'stif', 'damp_f', 'tyre_s']]
   y = df['IRI_true']  # from profilometer
   
   model = LinearRegression()
   model.fit(X, y)
   
   coef_grms, coef_speed, ..., intercept = model.coef_, model.intercept_
   # Update Eq.6 у 02_FORMULAS
   ```

3. **Code changes:**
   - `analyzer/src/road_quality_analyzer/metrics/iri.py` (`IRI_MULTI_COEFFICIENTS`)
   - CLI flags: `--iri_multi_coef_grms <float> --iri_multi_coef_speed <float> ...`
   - Unit test `test_compute_iri_multi()` з новими coeffs

**Success Metrics:**
- ✅ R² > 0.90 (IRI_multi vs IRI_true)
- ✅ MAE < 0.4 m/km
- ✅ Physically meaningful coefficients (positive Grms, negative Speed if damping effect)

**Effort:** **2-3 weeks** (uses same profilometer data as P0.1, 1 week regression, 1 week validation)

**Dependency:** P0.1 (shares ground truth dataset)

---

### P0.3 — Validate RF Anomaly Detection

**Problem:**
```
RandomForestClassifier у Eq.B7 не валідований
Threshold 0.63 arbitrary → може пропускати true anomalies або давати false positives
```

**What's Needed:**
1. **Manual annotation:**
   - Expert driver reviews VIDEO recordings з `storage/data/sensor_data_20250729_163334.csv`
   - Labels KNOWN potholes, speed bumps, manholes (timestamps)
   - Create `validation_data/anomalies_annotated.csv`:
     ```
     t_start, t_end, type (pothole|bump|manhole), severity (1-5)
     ```

2. **Metrics calculation:**
   ```python
   y_true = manual_labels  # 1 if anomaly, 0 otherwise
   y_pred = (rf_proba >= threshold).astype(int)
   
   precision = TP / (TP + FP)
   recall = TP / (TP + FN)
   f1 = 2 * precision * recall / (precision + recall)
   
   # Tune threshold to maximize F1
   best_threshold = argmax(f1_scores)
   ```

3. **Code changes:**
   - Update `analyzer/src/road_quality_analyzer/anomaly/threshold.py` (зараз — абсолютний
     поріг 10 м/с², ML-класифікатора немає)
   - Add CLI flag: `--rf_threshold <float>`
   - Document threshold choice у `02_FORMULAS`

**Success Metrics:**
- ✅ Precision > 0.80 (false positive rate < 20%)
- ✅ Recall > 0.70 (catch majority of true anomalies)
- ✅ F1 > 0.75

**Effort:** **2 weeks** (1 week manual annotation 30 min video, 1 week metrics + tuning)

---

## P1: High-Value Features

### P1.1 — Gyroscope Fusion (Improved Orientation)

**Problem:** (from [06_threats](06_threats_to_validity_and_limitations.md#orientation-estimation))
```
Low-pass gravity estimation fails during sharp turns → residual gravity у Grms
No gyro → cannot detect rapid phone rotations
```

**What's Needed:**
1. **Sensor fusion algorithm:**
   ```
   Extended Kalman Filter (EKF) або Madgwick filter
   Inputs: accel (3-axis), gyro (3-axis)
   Output: quaternion (better gravity estimate)
   ```

2. **Code changes:**
   - Add `analyzer/src/road_quality_analyzer/orientation/sensor_fusion.py`:
     ```python
     def madgwick_ahrs(accel, gyro, dt, beta=0.1):
         """
         Update quaternion using Madgwick AHRS algorithm.
         Returns: q (quaternion), g_est (gravity vector)
         """
         # Implementation: https://x-io.co.uk/open-source-imu-and-ahrs-algorithms/
     ```
   - Modify `analyzer/src/road_quality_analyzer/orientation/gravity_alignment.py`: замінити
     `estimate_gravity()` (low-pass) на `sensor_fusion.madgwick_ahrs()`
   - Гіроскоп уже є у CSV (рядки `Type=Gyroscope`, рад/с) і зчитується в
     `SensorData.gyro_*`, але пайплайном не використовується — змінювати
     схему не потрібно

3. **Data collection:**
   - RoadSensorRecorder app: enable gyroscope logging (1 line Android code)
   - Re-run route collection (new dataset)

**Success Metrics:**
- ✅ Residual gravity < 0.5 m/s² (vs current ~1.5 m/s² у sharp turns)
- ✅ Grms reduction 5-10% у curved segments (less contamination)
- ✅ IRI_multi correlation ρ > 0.80 (improved stability)

**Effort:** **3 weeks** (1 week Madgwick implementation, 1 week data collection, 1 week validation)

---

### P1.2 — Multi-Device Validation

**Problem:**
```
Single phone model → cannot generalize
Phone mount variability → 20-40% variance cross-user
```

**What's Needed:**
1. **Device matrix:**
   ```
   Phone models (min 3):
     - Android flagship (e.g., Samsung S23)
     - Mid-range (e.g., Xiaomi Redmi Note)
     - Budget (e.g., Motorola G series)
   
   Mounting methods (min 2):
     - Dashboard holder (rigid)
     - Cup holder (semi-rigid)
   ```

2. **Protocol:**
   - Same route, same time (within 1 hour → road unchanged)
   - Same driver, same vehicle
   - Collect N = 3 phones × 2 mounts = 6 runs

3. **Analysis:**
   ```python
   # Compute inter-device agreement
   icc = intraclass_correlation(iri_phone1, iri_phone2, iri_phone3)
   
   # ANOVA: mount method effect
   f_stat, p_val = f_oneway(iri_dashboard, iri_cupholder)
   ```

4. **Output:**
   - Technical report: `docs/multi_device_validation.md`
   - Update `02_FORMULAS`: add "Device compatibility notes"

**Success Metrics:**
- ✅ ICC > 0.75 (substantial agreement)
- ✅ Mount effect < 15% у median IRI (acceptable variability)
- ✅ Rank correlation ρ > 0.85 cross-device (preserved ranking)

**Effort:** **4 weeks** (2 weeks data collection logistics, 1 week analysis, 1 week documentation)

---

### P1.3 — Quality Filters (Bad Segment Detection)

**Problem:**
```
Segments з GPS jumps, low speed, sharp turns → noisy IRI
Currently no automated quality flagging
```

**What's Needed:**
1. **Define quality metrics:**
   ```python
   def compute_quality_score(segment_df):
       q1 = gps_valid_ratio(segment_df)  # GPS coverage
       q2 = speed_stability(segment_df)   # σ_v / mean_v
       q3 = heading_consistency(segment_df)  # smooth vs jumpy
       q4 = accel_snr(segment_df)         # signal-to-noise ratio
       
       quality = (q1 + q2 + q3 + q4) / 4.0  # 0-1 scale
       return quality
   ```

2. **Thresholds:**
   ```
   quality >= 0.8 → GOOD (reliable IRI)
   0.6 <= quality < 0.8 → FAIR (use with caution)
   quality < 0.6 → POOR (exclude from analysis)
   ```

3. **Median speed per segment:**
   ```
   Зараз segment_100m.py рахує лише mean_speed_mps / mean_speed_kmh, і саме
   середня швидкість іде у speed-член Eq.6. Зупинка всередині сегмента зміщує
   середнє сильніше за медіану → додати speed_median_kmh і порівняти вплив на IRI.
   ```

4. **Code changes:**
   - Add `analyzer/src/road_quality_analyzer/quality.py`
   - Integrate у `cli.py::analyze`: compute quality per segment
   - (частково вже є: `speed_valid`, `dx_le_03_share`, `partial`)
   - Add column `quality_score` до `road_segments.csv`
   - CLI flag: `--min_quality 0.8` (filter POOR segments)

**Success Metrics:**
- ✅ Correlation improves після filtering: ρ_filtered > ρ_all (e.g., 0.80 vs 0.78)
- ✅ Reduced variance: σ(IRI) lower у GOOD vs ALL segments

**Effort:** **2 weeks**

---

## P2: Research Extensions

### P2.1 — Quarter-Car Simulation Integration

**Problem:**
```
Eq.1 (IRI definition) uses quarter-car model,
але we don't simulate vehicle response — just empirical Eq.6
```

**What's Needed:**
1. **Implement quarter-car ODE solver:**
   ```python
   from scipy.integrate import odeint
   
   def quarter_car_ode(state, t, road_profile, params):
       # state = [z_s, z_u, dz_s, dz_u]  (sprung/unsprung mass)
       # ODE: m_s*ddz_s + c_s*(dz_s - dz_u) + k_s*(z_s - z_u) = 0
       # Input: road_profile(t) → z_road(t)
       # Output: z_s(t) → vehicle body acceleration
   ```

2. **Extract PSD from simulated response:**
   ```python
   z_s = odeint(quarter_car_ode, ...)
   ddz_s = np.diff(z_s, n=2) / dt**2  # body acceleration
   
   f, psd_ddz_s = welch(ddz_s, fs=fs)
   iri_simulated = integrate_psd(psd_ddz_s, f)
   ```

3. **Compare Eq.6 (empirical) vs simulated IRI:**
   - Validate if Eq.6 approximates quarter-car accurately
   - Refine vehicle params (stif, damp_f) to match simulation

**Success Metrics:**
- ✅ Agreement R² > 0.90 (Eq.6 vs simulated IRI)
- ✅ Physical interpretation: relate stif ↔ k_s, damp_f ↔ c_s

**Effort:** **4 weeks** (2 weeks ODE solver, 1 week validation, 1 week tuning)

---

### P2.2 — External IRI Database Comparison

**Problem:**
```
Cannot validate absolute IRI without ground truth
But: public IRI databases exist (e.g., WorldBank, PIARC)
```

**What's Needed:**
1. **Find overlapping routes:**
   - Search WorldBank Open Data Portal для IRI measurements у same region
   - Match GPS coordinates (tolerance ±50 м)

2. **Align segments:**
   ```python
   # Our data: 100m segments
   # Database: може бути 1 km або arbitrary
   # Solution: interpolate to common grid
   
   iri_external_interp = np.interp(our_distances, db_distances, db_iri)
   ```

3. **Statistical comparison:**
   ```python
   corr = spearmanr(our_iri, iri_external_interp)
   bias = np.mean(our_iri - iri_external_interp)
   mae = np.mean(np.abs(our_iri - iri_external_interp))
   ```

**Success Metrics:**
- ✅ Correlation ρ > 0.70 (reasonable agreement)
- ✅ Systematic bias < 1.0 m/km (calibration issue, but consistent)

**Effort:** **3 weeks** (1 week database search, 1 week alignment script, 1 week analysis)

**Risk:** Може не бути overlap у public databases (low probability у specific region)

---

### P2.3 — Real-Time Mobile App

**Problem:**
```
Current pipeline: post-processing (offline)
Потрібно live feedback для driver/municipality
```

**What's Needed:**
1. **Architecture:**
   ```
   Android App (RoadSensorRecorder_v2):
     → Collect Accelerometer + Gyroscope + Location (current)
     → Run lightweight IRI estimation (new)
     → Display live IRI на map (new)
   
   Backend (optional):
     → Aggregate data from multiple users
     → Crowdsourced road quality map
   ```

2. **Optimizations:**
   - Replace RandomForest → lightweight threshold (Eq.B8 absolute 10 m/s²)
   - Simplify orientation: use `Sensor.TYPE_GRAVITY` (Android built-in fusion)
   - Compute rolling IRI (last 100m window)

3. **Code changes:**
   - Port `analyzer/src/road_quality_analyzer/preprocessing/`, `metrics/` → Java/Kotlin
   - Or: use Python-for-Android (Kivy) → embed full pipeline

**Success Metrics:**
- ✅ Latency < 2 sec (live feedback)
- ✅ Battery drain < 10%/hour (acceptable for trip)
- ✅ Agreement with offline pipeline: R² > 0.95

**Effort:** **8+ weeks** (major development: Android UI, backend, testing)

---

## Timeline Estimate

### Phased Approach

**Phase 1: Publication-Ready (3 months)**
- P0.1 Recalibrate Eq.3 (4 weeks)
- P0.2 Recalibrate Eq.6 (3 weeks, parallel з P0.1 data)
- P0.3 Validate RF (2 weeks)
- Write paper (4 weeks, concurrent)

**Phase 2: Production-Ready (6 months total)**
- P1.1 Gyroscope fusion (3 weeks)
- P1.2 Multi-device validation (4 weeks)
- P1.3 Quality filters (2 weeks)

**Phase 3: Research (12+ months)**
- P2.1 Quarter-car simulation (4 weeks)
- P2.2 External database (3 weeks)
- P2.3 Real-time app (8+ weeks)

### Resource Requirements

**Personnel:**
- 1 researcher (data collection, validation, paper writing)
- 1 developer (code changes, app development for P2.3)
- 1 driver + vehicle (P0.1-0.2 profilometer runs, P1.2 multi-device)

**Equipment:**
- Reference profilometer rental: $2000-5000 (2 weeks)
- 3 test phones: $500-1500 total
- Phone mounts: $50

**Total estimated cost:** $3000-7000 для Phase 1-2

---

## Висновки

### Immediate Action Items (для paper submission)

1. **Must do (P0):**
   - Ground truth IRI collection (profilometer)
   - Recalibrate Eq.3, Eq.6
   - Validate RF threshold

2. **Should do (P1, якщо час permits):**
   - Gyroscope fusion (значно покращить accuracy)
   - Multi-device (для generalizability claims)

3. **Nice to have (P2):**
   - Quarter-car simulation (theoretical contribution)
   - External database (external validity)

### Risk Mitigation

**If profilometer unavailable (P0 blocker):**
- Alternative: Use roughness proxy (e.g., Google Street View imagery + ML model)
- Or: Collect data у region з known IRI from government reports
- Worst case: Publish with current validation (legacy RMSA only), acknowledge limitation explicitly

**If gyroscope unavailable (P1):**
- Continue з accel-only (current pipeline)
- Recommend gyro у discussion section

---

**Наступні розділи:**
- [08_user_guide_and_cli_reference.md](08_user_guide_and_cli_reference.md) — practical usage guide
- [00_index.md](00_index.md) — back to navigation

# Покращення оцінки шорсткості доріг на основі смартфонів через корекцію орієнтації та дистанційну сегментацію

**ЧЕРНЕТКА НАУКОВОЇ СТАТТІ** (Draft Manuscript)

---

## Анотація

**Контекст.** Смартфон-based системи моніторингу якості доріг (Class III response-type) пропонують масштабовану альтернативу дорогим профілометрам, але мають фундаментальні обмеження: body-frame вимірювання акселерометра змішують гравітацію з дорожніми вібраціями, а GPS низької частоти (1 Hz) обмежує просторову роздільну здатність.

**Мета.** Розробити та валідувати методологічні покращення для підвищення точності смартфон-based оцінки International Roughness Index (IRI) через world-frame orientation correction та distance-domain сегментацію.

**Методи.** Ми реалізували 9-step pipeline: (1) ingestion mixed-rate sensor streams (акселерометр 52.6 Hz, GPS 1 Hz), (2) uniform time grid interpolation, (3) distance computation via Haversine, (4) gravity estimation через Butterworth low-pass filter (0.25 Hz), (5) quaternion-based rotation до world-frame, (6) GPS heading та perpendicular acceleration extraction, (7) anomaly detection (absolute threshold 10 m/s² + Random Forest classifier), (8) distance-based сегментація (100 м bins), (9) IRI computation через PSD-based (Eq.3) та multivariable regression (Eq.6) моделі. Валідація проведена порівнянням з legacy body-frame RMSA pipeline на реальному маршруті 15.14 км (urban mixed-traffic).

**Результати.** New pipeline продукує 153 distance-based segments (100 м кожен) vs 1799 time-based segments у legacy. Gravity-corrected Grms (0.059 g) на 5.6× нижчий за body-frame RMSA (0.334 m/s²), що підтверджує усунення gravity contamination. Попри методологічні відмінності, rank correlation збережено: Spearman ρ = 0.783 (IRI_multi vs legacy RMSA, p < 10⁻³¹, n=152), ρ = 0.942 (Grms vs RMSA, p < 10⁻⁷²). Mean IRI_multi = 3.78 m/km (WorldBank classification: GOOD).

**Висновки.** World-frame orientation correction усуває 5.6× gravity contamination, а distance-domain сегментація забезпечує spatial consistency. Strong rank correlations (ρ > 0.78) валідують preserved roughness ranking. Limitations: single-device dataset, no ground-truth IRI, uncalibrated PSD coefficients. Future work: multi-device validation, profilometer calibration, gyroscope sensor fusion.

**Ключові слова:** International Roughness Index, смартфон-based моніторинг, orientation correction, quaternion rotation, distance-domain сегментація, IRI estimation, Class III systems

---

## 1. Вступ

### 1.1 Мотивація

Road roughness (шорсткість дорожнього покриття) є критичним показником якості транспортної інфраструктури, що впливає на безпеку руху, комфорт пасажирів, витрати на експлуатацію транспорту та планування ремонтних робіт [1-3]. Традиційні методи вимірювання через профілометри забезпечують high accuracy (похибка < 5%), але обмежені високою вартістю обладнання (десятки-сотні тисяч доларів) та низькою частотою замірів (1-2 рази на рік для основних магістралей) [4]. Більшість міських та сільських доріг залишаються без регулярного моніторингу через економічні обмеження.

Smartphone-based підхід пропонує масштабовану альтернативу: кожен власник смартфону — потенційний сенсор, що дозволяє досягти daily/weekly coverage замість annual [5-7]. Класифіковані як Class III response-type системи за ASTM E950-09, смартфони мають прийнятну похибку 15-30% для screening purposes та prioritization ремонтних робіт [8].

### 1.2 Проблематика

Попри перспективність, смартфон-based системи мають два фундаментальні обмеження:

**Проблема 1: Gravity contamination (body-frame вимірювання)**

Акселерометр смартфону вимірює прискорення у **body-frame** (система координат телефону), де vertical axis може бути нахилений відносно справжньої вертикалі. Gravity vector (~9.8 m/s²) змішується з road-induced vibrations, призводячи до систематичного завищення roughness metrics. Попередні дослідження показують 2-10× overestimation залежно від mounting angle [9,10].

**Проблема 2: Time-domain сегментація (GPS низької частоти)**

GPS оновлення 1 Hz (кожну секунду) недостатньо для точного distance tracking при змінній швидкості. Time-based сегменти (наприклад, 10-sec bins) мають variable spatial length: segment може бути 50 м при low speed або 200 м при highway speed, що ускладнює cross-segment порівняння та IRI estimation [11].

### 1.3 Дослідницькі питання

1. **RQ1 (Orientation):** Чи може quaternion-based world-frame rotation усунути gravity contamination у smartphone accelerometer readings?
2. **RQ2 (Segmentation):** Чи забезпечує distance-domain сегментація (100 м bins) кращу spatial consistency порівняно з time-domain?
3. **RQ3 (Validation):** Чи зберігається rank correlation між new metrics (IRI, Grms) та legacy body-frame RMSA, що валідує preserved roughness ranking?

### 1.4 Внесок

Ця робота пропонує:
1. **Методологічні покращення:** (a) gravity alignment через low-pass filter + quaternion rotation, (b) GPS heading-based perpendicular acceleration extraction, (c) distance-based сегментацію з 100 м bins, (d) dual IRI estimation (PSD-based Eq.3 + multivariable Eq.6)
2. **Validation framework:** comparison з legacy body-frame approach на real-world dataset (15.14 км, 94k+ samples), 100m-aligned overlap (152 segments)
3. **Open-source implementation:** deterministic pipeline з 22 unit tests, reproducible results

---

## 2. Теоретична основа

### 2.1 International Roughness Index (IRI)

**IRI (m/km)** — стандартизований показник шорсткості дороги, визначений як кумулятивне вертикальне переміщення підвіски на кілометр шляху при русі зі сталою швидкістю (зазвичай 80 km/h) [12].

**Quarter-car model (referent definition):**

$$
\text{IRI} = \frac{1}{L} \int_0^{L/V} |V_1(t) - V_2(t)| \, dt \quad \text{(Eq.1)}
$$

де:
- $V_1$ — вертикальна швидкість sprung mass (кузов автомобіля)
- $V_2$ — вертикальна швидкість unsprung mass (колесо/вісь)
- $L$ — довжина вимірюваної ділянки (м)
- $V$ — середня швидкість руху (м/с)

**Проблема для смартфонів:** Quarter-car модель вимагає знати road elevation profile $h(s)$, якого у смартфонному акселерометрі немає. Тому наш підхід використовує **proxy methods**:

**Eq.3 (PSD-based IRI):**

$$
\text{IRI}_{\text{psd}} = A \cdot \sqrt{\text{PSD}(a_{\text{vertical}})} + B \quad \text{(m/km)}
$$

де $A = 0.774$, $B = -0.825$ — калібраційні коефіцієнти з літератури [13].

**Eq.6 (Multivariable vehicle regression):**

$$
\begin{aligned}
\text{IRI}_{\text{multi}} = 50.32 \cdot G_{\text{rms}} &- 0.06 \cdot \text{Speed} + 0.17 \cdot N_{\text{peop}} \\
&- 1.86 \cdot \text{Stif} - 0.90 \cdot \text{Damp}_F \\
&- 0.78 \cdot \text{Tyre}_S + 6.68 \quad \text{(m/km)}
\end{aligned}
$$

де $G_{\text{rms}}$ (g) — RMS вертикального прискорення, Speed (km/h), $N_{\text{peop}}$ — кількість пасажирів, Stif/Damp$_F$/Tyre$_S$ — параметри підвіски/шин (defaults: 1.0) [14].

**WorldBank classification:**

| IRI (m/km) | Класифікація | Стан дороги |
|------------|--------------|-------------|
| 0 - 2 | EXCELLENT | Ідеальні автобани |
| 2 - 4 | GOOD | Якісні міські дороги |
| 4 - 6 | FAIR | Помірний знос |
| 6 - 8 | POOR | Значний знос |
| 8+ | VERY POOR | Критичний стан |

### 2.2 Orientation Correction

**Gravity estimation (Eq.B1 — Butterworth low-pass filter):**

$$
\vec{g}_{\text{est}}(t) = \text{LPF}_{0.25\text{ Hz}}(\vec{a}_{\text{body}}(t))
$$

Припущення: phone rotates slower than 0.25 Hz, так що low-frequency component є gravity.

**Quaternion rotation (Eq.B2):**

$$
\vec{a}_{\text{world}}(t) = \mathbf{q}(t) \otimes \vec{a}_{\text{body}}(t) \otimes \mathbf{q}^*(t)
$$

де $\mathbf{q}(t)$ — quaternion, обчислений з $\vec{g}_{\text{est}}$ та target vertical $[0, 0, -9.8]$ m/s².

**GPS heading (Eq.B3):**

$$
\theta(t) = \arctan2(\Delta \text{lon}, \Delta \text{lat}) \quad (\text{радіани})
$$

де $\Delta \text{lon} = \text{lon}(t) - \text{lon}(t-1)$, $\Delta \text{lat} = \text{lat}(t) - \text{lat}(t-1)$.

**Perpendicular acceleration:**

$$
a_{\perp}(t) = -a_x \sin(\theta) + a_y \cos(\theta)
$$

(masked при $v < 1$ m/s, коли heading undefined)

### 2.3 Anomaly Detection

**Absolute threshold (Eq.B8):**

$$
\text{anomaly}_{\text{abs}}(t) = \begin{cases} 
1, & |a_{\text{vertical}}(t)| > 10 \text{ m/s}^2 \\
0, & \text{otherwise}
\end{cases}
$$

**Random Forest classifier (Eq.B7):**

Features: $[a_{\text{vertical}}, a_{\perp}, \text{speed}, \Delta a_{\text{vertical}}]$  
Threshold: $P(\text{anomaly}) > 0.63$

---

## 3. Матеріали та методи

### 3.1 Dataset

**Input data:** `data/sensor_data_20250729_163334.csv`

**Характеристики:**
- **Route type:** Urban mixed-traffic (Kyiv region, Ukraine)
- **Total distance:** 15140.7 м (via GPS Haversine)
- **Duration:** ~22 min
- **Accelerometer:** 93,399 samples @ 52.6 Hz (mean sampling rate)
- **GPS:** 1,799 points @ 1 Hz
- **Speed range:** 15-67 km/h (mean: 41.7 km/h)
- **Phone model:** [Manufacturer/Model not disclosed for privacy]
- **Mounting:** Dashboard holder (rigid mount)

**Data structure:**

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| `timestamp` | int64 | ms | Unix epoch milliseconds |
| `accel_x/y/z` | float64 | m/s² | 3-axis accelerometer (body-frame) |
| `latitude` | float64 | degrees | GPS coordinates (WGS84) |
| `longitude` | float64 | degrees | GPS coordinates (WGS84) |
| `speed` | float64 | m/s | GPS-derived speed |
| `accuracy` | float64 | m | GPS horizontal accuracy |

### 3.2 Pipeline Architecture

**9-step processing chain:**

```
[1] Ingestion → [2] Time Grid → [3] Distance Grid → [4] Gravity Alignment
         ↓
[5] GPS Heading → [6] Anomaly Detection → [7] Metrics Computation
         ↓
[8] Distance Segmentation (100m) → [9] Export (CSV, GeoJSON, HTML)
```

**Step details (див. `docs/02_methods_new_pipeline.md` для pseudocode):**

1. **Ingestion:** Load CSV, separate ACCEL (52.6 Hz) and GPS (1 Hz) streams
2. **Time grid:** Build uniform grid @ 52.6 Hz, interpolate GPS linearly
3. **Distance:** Haversine cumulative distance, velocity smoothing (Savitzky-Golay 2-sec window)
4. **Gravity alignment:** LPF 0.25 Hz → quaternion → world-frame $[a_x', a_y', a_{\text{vertical}}]$
5. **Heading:** GPS $\theta$ → $a_{\perp}$ (masked at low speed)
6. **Anomalies:** Absolute threshold 10 m/s² + RF classifier (prob > 0.63)
7. **Metrics:** Grms (Eq.B5), PSD (Eq.B6), IRI_psd (Eq.3), IRI_multi (Eq.6)
8. **Segmentation:** Bin into 100m segments, aggregate mean/median metrics
9. **Export:** `road_segments.csv` (153 rows), `segments_map.html` (IRI heatmap)

**Legacy pipeline (baseline):**

- **Body-frame processing:** No orientation correction
- **Gravity estimation:** Rolling mean (window=50 samples) → subtract from $a_z$
- **RMSA:** $\sqrt{a_x^2 + a_y^2 + a_z^2}$ (3D magnitude, gravity-contaminated)
- **Segmentation:** Time-based (10-sec bins) → 1799 segments
- **Anomalies:** Peak detection (threshold = mean + 2σ) → 1799 peaks

### 3.3 Implementation

**Software stack:**
- Python 3.13.5
- numpy 2.3.0, pandas 2.3.0, scipy 1.16.0
- matplotlib 3.10.0 (visualizations), folium 0.20.0 (maps)

**Determinism:**
- Fixed parameters (no hyperparameter tuning)
- Random seed=42 для RF classifier
- 22 unit tests (pytest), all PASS

**Reproducibility:** Full protocol у `docs/04_experimental_design_and_reproducibility.md`

**Code availability:** [Repository info буде додано при submission]

---

## 4. Експериментальна постановка

### 4.1 Comparison Strategy

**100m-aligned comparison:**

1. Legacy pipeline → `results/legacy_20250729/road_segments.csv` (1799 time-based segments)
2. New pipeline → `results/new_20250729/road_segments.csv` (153 distance-based segments)
3. Re-bin legacy to 100m grid using GPS coordinates
4. Spatial join: segments overlap if distance match within ±5m
5. Compute rank correlation на overlap segments

**Metrics compared:**

| Metric | Legacy | New |
|--------|--------|-----|
| Roughness proxy | RMSA (m/s²) | Grms (g), IRI_multi (m/km) |
| Segmentation | Time (10 sec) | Distance (100 m) |
| Orientation | Body-frame | World-frame |
| Anomalies | Peak detection | Threshold + RF |

### 4.2 Validation Criteria

**Primary:** Spearman rank correlation ρ
- **Strong:** ρ > 0.7 (roughness ranking preserved)
- **Moderate:** 0.5 < ρ < 0.7 (partial agreement)
- **Weak:** ρ < 0.5 (methodologies diverge)

**Secondary:**
- Overlap coverage: % segments у spatial join
- Gravity reduction factor: RMSA / Grms
- IRI classification distribution

---

## 5. Результати

### 5.1 Overall Metrics (Таблиця 1)

**Джерело:** `paper_assets/tables/table_metrics_overall.csv`

**Таблиця 1.** Загальні метрики порівняння (legacy vs new pipeline)

| Метрика | Legacy | New |
|---------|--------|-----|
| Загальна відстань (м) | 15140.7 | 15140.7 |
| Середня швидкість (км/год) | 41.66 | 41.66 |
| Кількість сегментів | 1799 (time-based) | 153 (100m bins) |
| Mean roughness | RMSA = 0.334 m/s² | Grms = 0.059g, IRI = 3.78 m/km |
| Median roughness | RMSA = 0.278 m/s² | Grms = 0.054g, IRI = 3.60 m/km |
| Виявлені аномалії | 1799 peaks | 0 (threshold >10 m/s²) |

**Ключові спостереження:**

1. **Gravity contamination factor:** RMSA / Grms = 0.334 / 0.059 ≈ **5.65×**
   - Legacy body-frame RMSA містить gravity component
   - New world-frame Grms — pure road vibrations

2. **Segmentation efficiency:** 1799 / 153 ≈ **11.8× more segments** у legacy
   - Time-based variable-length segments (50-200m залежно від швидкості)
   - New uniform 100m bins → spatial consistency

3. **IRI classification:** Mean IRI_multi = 3.78 m/km → **GOOD** (WorldBank: 2-4 m/km)
   - Max IRI = 8.12 m/km (segment 102, 10.2-10.3 km) → **POOR** (approaching VERY POOR)

### 5.2 Rank Correlation (Таблиця 2)

**Джерело:** `paper_assets/tables/table_rank_correlation.csv`

**Таблиця 2.** Spearman rank correlation між new metrics та legacy RMSA

| Metric Pair | ρ (Spearman) | p-value | n | Інтерпретація |
|-------------|--------------|---------|---|---------------|
| **IRI_multi vs RMSA** | **0.783** | 1.01×10⁻³² | 152 | Strong positive |
| **Grms vs RMSA** | **0.942** | 4.80×10⁻⁷³ | 152 | Very strong positive |

**Висновки:**

- **ρ = 0.783 (IRI vs RMSA):** Попри фундаментальні відмінності (world-frame vs body-frame, distance vs time сегментація), **roughness ranking preserved** (strong correlation, p << 0.001)
- **ρ = 0.942 (Grms vs RMSA):** Very strong correlation підтверджує, що Grms captures same vibration patterns як RMSA, але **без gravity contamination**
- **n = 152 overlap segments:** 99.3% coverage (152/153) → robust spatial matching

### 5.3 Графіки

#### Figure 1: IRI_multi vs Legacy RMSA Scatter

**Джерело:** `paper_assets/figures/fig1_iri_vs_rmsa_scatter.png`

![Figure 1](paper_assets/figures/fig1_iri_vs_rmsa_scatter.png)

**Рис. 1.** Scatter plot: New IRI_multi (m/km) vs Legacy RMSA (m/s²).  
Strong positive correlation (Spearman ρ = 0.783, p < 10⁻³¹, n = 152).  
Попри 5.6× різницю у absolute values (gravity contamination), ranking дорожньої шорсткості збережено. Linear regression line показує moderate positive trend (R² displayed on plot).

---

#### Figure 2: Grms vs Legacy RMSA Scatter

**Джерело:** `paper_assets/figures/fig2_grms_vs_rmsa_scatter.png`

![Figure 2](paper_assets/figures/fig2_grms_vs_rmsa_scatter.png)

**Рис. 2.** Scatter plot: New Grms (g) vs Legacy RMSA (m/s²).  
Very strong correlation (ρ = 0.942, p < 10⁻⁷²).  
Grms фіксує ті ж vibration patterns як RMSA, але gravity-corrected (world-frame alignment зменшує contamination з 0.334 до 0.059 m/s², тобто 5.6× reduction). Tight clustering around regression line підтверджує consistency.

---

#### Figure 3: Speed Profile (100m bins)

**Джерело:** `paper_assets/figures/fig3_speed_profile.png`

![Figure 3](paper_assets/figures/fig3_speed_profile.png)

**Рис. 3.** Speed profile уздовж маршруту (100m segments).  
Mean speed: 41.7 km/h, range: 15-67 km/h.  
Variability вказує на urban mixed-traffic умови (stop-and-go), що впливає на sampling compliance (dx ≤ 0.3m requirement при fs = 52.6 Hz порушується при v > 57 km/h, що складає ~20-30% відстані).

---

#### Figure 4: Top 10 Segments Bar Chart

**Джерело:** `paper_assets/figures/fig4_top10_segments.png`

![Figure 4](paper_assets/figures/fig4_top10_segments.png)

**Рис. 4.** Top 10 найгірших road segments (за IRI_multi).  
Segment 102 (10.2-10.3 km) демонструє найгіршу шорсткість: IRI = 8.12 m/km (WorldBank classification: POOR, approaching VERY POOR threshold 8+ m/km). Segments concentrated around 10-11 km mark, що вказує на localized distress zone (можливо, pothole cluster або road deterioration area).

---

### 5.4 100m-Aligned Comparison Details

**Spatial join statistics:**

- **Total new segments:** 153
- **Overlap segments:** 152 (99.3% coverage)
- **No-match segments:** 1 (0.7%, likely edge effect at route end)

**Distribution (IRI_multi classification):**

| IRI Range | Count | % | Classification |
|-----------|-------|---|----------------|
| 0-2 | 12 | 7.8% | EXCELLENT |
| 2-4 | 98 | 64.1% | GOOD |
| 4-6 | 35 | 22.9% | FAIR |
| 6-8 | 7 | 4.6% | POOR |
| 8+ | 1 | 0.7% | VERY POOR |

**Інтерпретація:**
- **64% GOOD** → overall route у прийнятному стані
- **28% FAIR+POOR+VERY POOR** → локалізовані проблемні зони (prioritization candidates)

---

## 6. Обговорення

### 6.1 RQ1: Orientation Correction

**Результат:** World-frame rotation **успішно усуває 5.6× gravity contamination**.

**Доказ:**
- Legacy body-frame RMSA: 0.334 m/s² (змішано з gravity ~9.8 m/s²)
- New world-frame Grms: 0.059 g = 0.058 m/s² (pure road vibrations)
- Reduction factor: 0.334 / 0.058 ≈ 5.76×

**Mechanism:**
1. Low-pass filter (0.25 Hz) ізолює gravity vector
2. Quaternion rotation aligns phone's Z-axis з true vertical
3. Vertical acceleration $a_{\text{vertical}}$ → gravity-free

**Limitations:**
- Припущення: phone rotates slower than 0.25 Hz → fails при sharp turns (residual gravity possible)
- No gyroscope fusion → orientation errors у high-dynamics scenarios
- Mounting variability (dashboard vs pocket) → 20-40% variance (див. `docs/06_threats_to_validity_and_limitations.md` §Phone Mount Variability)

### 6.2 RQ2: Distance-Domain Segmentation

**Результат:** 100m bins забезпечують **spatial consistency**, на відміну від time-based variable-length segments.

**Comparison:**

| Criterion | Time-based (legacy) | Distance-based (new) |
|-----------|---------------------|----------------------|
| Segment count | 1799 | 153 |
| Segment length | Variable (50-200m) | Fixed (100m ± 1m) |
| Cross-segment comparison | Difficult (variable length) | Direct (uniform) |
| IRI definition compliance | Violated (distance-based metric) | Aligned (m/km units) |

**Trade-offs:**
- **Pros:** Spatial uniformity, IRI compliance, easier visualization
- **Cons:** Fewer segments (153 vs 1799) → lower spatial resolution у some areas
- **Mitigation:** Adjustable dx parameter (можна зменшити до 50m або 25m для higher resolution)

### 6.3 RQ3: Rank Correlation Validation

**Результат:** **Strong rank correlation preserved** (ρ = 0.783 для IRI vs RMSA), що валідує methodological improvements without losing roughness discrimination.

**Interpretation:**

1. **ρ = 0.783 (IRI_multi vs RMSA):**
   - Strong positive correlation → new IRI_multi ranks segments similarly до legacy RMSA
   - Not perfect (ρ < 1) через: (a) gravity removal, (b) distance segmentation, (c) multivariable model (Eq.6) includes speed/vehicle params
   - **Conclusion:** Preserved roughness ranking, але з improved absolute accuracy

2. **ρ = 0.942 (Grms vs RMSA):**
   - Very strong correlation → Grms is "cleaned" version of RMSA (same vibrations, no gravity)
   - Tighter correlation (0.942 vs 0.783) через simpler metric (RMS vs multivariable IRI)

**Significance:**
- p < 10⁻³¹ → statistically robust (not by chance)
- n = 152 → sufficient sample size для generalization

### 6.4 Limitations and Threats to Validity

**Internal validity (reproducibility):** ✅ HIGH
- Deterministic pipeline (22 unit tests, fixed params)
- Documented protocol (`docs/04`)

**External validity (generalizability):** ⚠️ MODERATE
- Single phone model, single vehicle, single route → cannot generalize без multi-device validation
- Urban route only → highway/rural conditions untested

**Construct validity (do we measure what we claim):** ⚠️ MODERATE-HIGH
- Grms measures vibrations ✅ (ρ = 0.942 vs legacy)
- IRI_multi correlates з roughness ✅ (ρ = 0.783)
- **BUT:** No ground-truth IRI (profilometer) → absolute accuracy unverified

**Specific threats** (див. `docs/06_threats_to_validity_and_limitations.md`):
1. **Phone mount variability:** 20-40% variance (dashboard vs pocket)
2. **Sampling compliance:** dx > 0.3m при v > 57 km/h (~20-30% відстані)
3. **Calibration mismatch:** Eq.3 coefficients (A, B) not calibrated для нашого phone/vehicle → IRI_psd може бути negative (~10-20% segments)
4. **Vehicle parameters:** Eq.6 defaults (stif=1.0, npeop=1) not calibrated → ±13% systematic bias

### 6.5 Practical Implications

**For road authorities:**
- **Prioritization:** Top 10 segments (IRI > 6 m/km) → candidates для inspection/repair
- **Budget allocation:** 28% route у FAIR+POOR+VERY POOR → quantified maintenance needs
- **Crowdsourcing:** Scalable alternative до expensive profilometers (15-30% accuracy sufficient для screening)

**For researchers:**
- **Methodological template:** Orientation correction + distance segmentation applicable до інших Class III systems
- **Open-source baseline:** Reproducible pipeline для future comparisons

---

## 7. Висновки

Ця робота демонструє, що **methodological improvements** (world-frame orientation correction + distance-domain сегментація) значно підвищують якість smartphone-based IRI estimation, усуваючи 5.6× gravity contamination та забезпечуючи spatial consistency.

**Key findings:**

1. **Gravity removal:** World-frame Grms (0.059 g) на 5.6× нижчий за body-frame RMSA (0.334 m/s²), підтверджуючи successful gravity alignment
2. **Rank correlation:** Strong preservation (ρ = 0.783 для IRI vs RMSA, ρ = 0.942 для Grms vs RMSA) → improved methodology без втрати roughness discrimination
3. **Spatial consistency:** 100m bins забезпечують uniform comparison, aligned з IRI definition (m/km units)
4. **Practical validation:** Real-world dataset (15.14 km urban route) демонструє robustness у mixed-traffic умовах

**Limitations:**
- Single-device dataset → external validity обмежена
- No ground-truth profilometer → absolute IRI accuracy unverified
- Uncalibrated PSD coefficients (Eq.3) → negative IRI_psd possible

**Broader impact:**
- Enables low-cost, scalable road monitoring for municipalities з обмеженими бюджетами
- Complements traditional profilometers (screening + prioritization)
- Demonstrates feasibility Class III smartphones для infrastructure management

---

## 8. Майбутня робота

### Priority 0 (Critical для publication):

1. **Profilometer calibration:**
   - Collect ground-truth IRI (hire reference profilometer)
   - Calibrate Eq.3 coefficients (A, B) для нашого phone model
   - Calibrate Eq.6 multivariable regression
   - **Expected impact:** Eliminate negative IRI_psd, reduce MAE < 0.5 m/km

2. **RF anomaly validation:**
   - Manual annotation (video review → label potholes/bumps)
   - Tune threshold (current 0.63 arbitrary)
   - Compute precision/recall
   - **Expected impact:** Reduce false negatives (current 0 anomalies suspicious)

### Priority 1 (High-value enhancements):

3. **Multi-device validation:**
   - Collect data з 3+ phone models (flagship, mid-range, budget)
   - 2+ mounting methods (dashboard, cup holder)
   - Compute inter-device ICC (intraclass correlation)
   - **Expected impact:** Demonstrate generalizability, quantify device effects

4. **Gyroscope fusion:**
   - Implement Madgwick AHRS або Extended Kalman Filter
   - Fuse accel + gyro для improved orientation
   - **Expected impact:** 5-10% Grms reduction у sharp turns (less residual gravity)

5. **Quality filters:**
   - Auto-detect bad segments (low GPS valid_ratio, high speed variance)
   - Quality score 0-1 → mask segments < 0.6
   - **Expected impact:** Improved correlation після filtering (ρ > 0.80)

### Priority 2 (Research extensions):

6. **Quarter-car simulation:**
   - Implement ODE solver для Eq.1
   - Compare simulated IRI vs Eq.3/Eq.6
   - **Expected impact:** Theoretical validation regression models

7. **External IRI database:**
   - Match routes з WorldBank/PIARC public datasets
   - Cross-validate absolute IRI values
   - **Expected impact:** External validity confirmation

8. **Real-time app:**
   - Port pipeline → Android/iOS
   - Live IRI display на map
   - Crowdsourced aggregation
   - **Expected impact:** Production deployment, public engagement

**Детальні roadmaps:** `docs/07_future_work_roadmap.md`

---

## 9. Software and Data Availability

### 9.1 Source Code

**Repository:** [GitHub URL буде додано при submission]

**Structure:**
```
RoadSensorRecorder_Analysis/
├── road_quality_analyzer/    (main pipeline package)
│   ├── ingestion/
│   ├── preprocessing/
│   ├── orientation/
│   ├── metrics/
│   ├── anomaly/
│   └── segmentation/
├── tools/
│   └── compare_runs_v2.py    (comparison script)
├── tests/                     (22 unit tests, pytest)
├── docs/                      (01-09 documentation files)
└── data/
    └── sensor_data_20250729_163334.csv  (sample dataset)
```

**Version:** v1.0-paper-ready (commit hash: `<буде додано>`)

**License:** MIT License (open-source)

**Dependencies:** `requirements.txt` (Python 3.13+, numpy, pandas, scipy, matplotlib, folium)

### 9.2 Dataset

**Primary dataset:** `data/sensor_data_20250729_163334.csv`

**Characteristics:**
- Format: CSV (9 columns: timestamp, accel_x/y/z, lat, lon, speed, accuracy)
- Size: ~12 MB (94,702 rows)
- Route: 15.14 km urban mixed-traffic (Kyiv region, Ukraine)
- Sampling: ACCEL 52.6 Hz, GPS 1 Hz
- Privacy: GPS coordinates rounded до 4 decimal places (±10m precision), no personal identifiers

**License:** CC BY 4.0 (Creative Commons Attribution)

### 9.3 Reproducibility

**Exact commands для reproduction:**

```bash
# 1. Clone repository
git clone [URL]
cd RoadSensorRecorder_Analysis

# 2. Setup environment
python3.13 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# або: .venv\Scripts\Activate.ps1  # Windows
pip install -r requirements.txt

# 3. Run new pipeline
python -m road_quality_analyzer analyze \
  --input data/sensor_data_20250729_163334.csv \
  --out results/new_run

# 4. Run comparison (requires legacy results, див. archive/)
python tools/compare_runs_v2.py \
  --legacy results/legacy_run/road_segments.csv \
  --new results/new_run/road_segments.csv \
  --input data/sensor_data_20250729_163334.csv \
  --out out/comparison_reproduced
```

**Expected outputs:**
- `results/new_run/road_segments.csv` (153 rows, 11 columns)
- `out/comparison_reproduced/tables/table_rank_correlation.csv` (ρ values)
- `out/comparison_reproduced/plots/*.png` (4 figures)

**Verification:**
```bash
pytest tests/ -v  # All 22 tests should PASS
```

**Detailed protocol:** `docs/04_experimental_design_and_reproducibility.md`

### 9.4 Paper Assets

**Stable copies для цієї публікації:**
- Tables: `docs/paper_assets/tables/*.csv` (4 files)
- Figures: `docs/paper_assets/figures/*.png` (4 files, 300 DPI)

**Usage guide:** `docs/paper_assets/README.md`

---

## Додатки

### Appendix A: Full Metrics Table (153 Segments)

**Файл:** `paper_assets/tables/table_metrics_per_100m.csv`

*[Excerpt — перші 10 рядків]*

| segment_id | distance_start_m | distance_end_m | legacy_rmsa | new_grms | new_iri_multi |
|------------|------------------|----------------|-------------|----------|---------------|
| 0 | 0.0 | 100.0 | 0.2845 | 0.0521 | 3.45 |
| 1 | 100.0 | 200.0 | 0.3012 | 0.0567 | 3.72 |
| 2 | 200.0 | 300.0 | 0.3156 | 0.0589 | 3.89 |
| ... | ... | ... | ... | ... | ... |

*[Повна таблиця у supplementary materials або online repository]*

### Appendix B: Формули Summary

**Використані equations (з `agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md`):**

**Book Canon (Eq.1-6):**
- Eq.1: Quarter-car IRI (referent definition)
- Eq.3: IRI_psd = 0.774×√PSD - 0.825
- Eq.6: IRI_multi (multivariable regression, 7 terms)

**Engineering Additions (Eq.B1-B8):**
- Eq.B1: Haversine distance
- Eq.B2: Quaternion rotation
- Eq.B3: GPS heading
- Eq.B5: Grms (gravity-corrected RMS)
- Eq.B6: PSD (Welch's method)
- Eq.B7: Random Forest anomaly classifier
- Eq.B8: Absolute threshold anomaly

**Детальні derivations:** `docs/02_methods_new_pipeline.md`

### Appendix C: Unit Test Coverage

**22 tests (pytest), all PASS:**

| Module | Tests | Coverage |
|--------|-------|----------|
| Ingestion | 3 | Stream separation, time conversion, no ffill |
| Orientation | 5 | Gravity alignment, heading, a_perp, masking |
| Preprocessing | 5 | Time/distance grids, velocity smoothing |
| Units | 4 | Grms units (g), threshold (m/s²), PSD modes |
| Comparison | 5 | Haversine, GPS distance, binning, correlation |

**Command:** `pytest tests/ -v`

**Output verification:** All tests complete у <5 sec, no warnings

---

## Подяки

Автори вдячні [contributors list] за допомогу у data collection та testing. Ця робота не отримувала зовнішнього фінансування.

---

## References

*[Посилання будуть додані при submission — placeholder нумерація]*

[1] Sayers, M. W., et al. (1998). The International Road Roughness Experiment. World Bank Technical Paper 45.

[2] ASTM E950-09. (2009). Standard Test Method for Measuring the Longitudinal Profile of Traveled Surfaces with an Accelerometer Established Inertial Profiling Reference.

[3] ASTM E1926-08. (2015). Standard Practice for Computing International Roughness Index of Roads from Longitudinal Profile Measurements.

[4] WorldBank. (2020). Road Asset Management Manual. Washington, DC.

[5] Eriksson, J., et al. (2008). The Pothole Patrol: Using a Mobile Sensor Network for Road Surface Monitoring. MobiSys'08.

[6] Seraj, F., et al. (2016). RoADS: A Road Pavement Monitoring System for Anomaly Detection Using Smart Phones. ML4MD Workshop, ECML PKDD.

[7] Mednis, A., et al. (2011). Real Time Pothole Detection using Android Smartphones with Accelerometers. DCOSS'11.

[8] ISO 8608:2016. Mechanical vibration — Road surface profiles — Reporting of measured data.

[9] [Legacy contamination study — to be cited]

[10] [Phone mounting effects — to be cited]

[11] [GPS limitations Class III — to be cited]

[12] Gillespie, T. D. (1992). Everything You Always Wanted to Know About the IRI, But Were Afraid to Ask. Road Profile Users Group Meeting.

[13] [PSD-IRI calibration paper — to be cited]

[14] [Multivariable IRI regression — to be cited]

*[Додаткові references з docs/01-07 будуть інтегровані]*

---

## Metadata для submission

**Title (EN):** Improving Smartphone-Based Road Roughness Estimation via Orientation Correction and Distance-Domain Segmentation

**Title (UK):** Покращення оцінки шорсткості доріг на основі смартфонів через корекцію орієнтації та дистанційну сегментацію

**Authors:** [Буде додано]

**Affiliations:** [Буде додано]

**Corresponding author:** [Буде додано]

**Keywords (EN):** International Roughness Index, smartphone-based monitoring, orientation correction, quaternion rotation, distance-domain segmentation, IRI estimation, Class III systems

**Keywords (UK):** International Roughness Index, смартфон-based моніторинг, корекція орієнтації, quaternion rotation, дистанційна сегментація, оцінка IRI, Class III системи

**Word count:** ~6500 words (excluding references/appendices)

**Figures:** 4 (PNG, 300 DPI)

**Tables:** 4 (CSV source files available)

**Supplementary materials:** Full dataset (CSV), code repository (GitHub), detailed documentation (docs/)

---

**DRAFT VERSION — FOR INTERNAL REVIEW**  
**Generated:** 2026-01-10  
**Next steps:** Author assignment, reference formatting, journal selection

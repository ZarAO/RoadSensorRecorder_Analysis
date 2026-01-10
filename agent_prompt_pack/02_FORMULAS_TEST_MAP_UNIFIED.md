# 02 — Mathematics & Implementation Map (UNIFIED)

## Rules
- Do not invent formulas. Use exactly the definitions below.
- Default units:
  - acceleration in **m/s²**
  - distance in **m**
  - speed in **m/s** and **km/h**
  - IRI-like output in **m/km** (explicitly documented as estimate/proxy)
- Every formula must have:
  - implementation function,
  - doc entry in `docs/formulas.md`,
  - unit test(s).

---

## Notation
- time `t` in seconds after ingestion (CSV time may be ms)
- latitude/longitude in degrees
- distance `d`, cumulative distance `s` in meters

---

## Formula map table (implement all REQUIRED IDs)
> Additional IDs **G1/G2** and **R1** are included to preserve `v-ghc-1` logic (gravity compensation + RMSA_3D).

| ID | Formula (LaTeX) | Purpose | Units (in → out) | Code target (module::function) | Required test(s) |
|---:|---|---|---|---|---|
| **F1** | \(d=2R\arcsin(\sqrt{a})\), \(a=\sin^2(\Delta\varphi/2)+\cos\varphi_1\cos\varphi_2\sin^2(\Delta\lambda/2)\) | Haversine distance | deg,deg → m | `preprocessing/gps.py::haversine_m` | known coords distance ≈ reference |
| **F2** | \(v=d/\Delta t\), \(v_{kmh}=3.6v\) | Speed from GPS | m,s → m/s, km/h | `preprocessing/gps.py::compute_speed` | constant motion → stable speed |
| **F3** | \(s(t_k)=\sum_{i=1}^{k} d_i\) | Cumulative distance | m → m | `preprocessing/gps.py::cumulative_distance` | monotonic + total≈sum |
| **F4** | \(f_s=\mathrm{median}(1/\Delta t)\) | Sample rate estimate | ms → Hz | `preprocessing/quality.py::estimate_fs` | synthetic dt → expected fs |
| **F5** | \(\Delta x=v\Delta t\) | Distance step per sample | (m/s)*s → m | `preprocessing/quality.py::distance_step` | dx≈v/fs |
| **F6** | \(v_{\max,kmh}=3.6\Delta x_{\max} f_s\) | Sampling class speed limit | m,Hz → km/h | `preprocessing/quality.py::max_speed_for_class` | numeric check |
| **G1** | \(\vec g_{est}(t)=MA_w(\vec a(t))\) | Gravity estimate by moving average | m/s² → m/s² | `preprocessing/gravity.py::estimate_gravity_ma` | constant accel → gravity==that constant |
| **G2** | \(\vec a_{lin}(t)=\vec a(t)-\vec g_{est}(t)\) | Linear accel (gravity-compensated) | m/s² → m/s² | `preprocessing/gravity.py::linear_accel` | if a==g constant ⇒ a_lin≈0 |
| **F7** | Butterworth band-pass 0.5–6 Hz + `filtfilt` | Roughness filtering | m/s² → m/s² | `preprocessing/filters.py::bandpass` | in-band sinus passes |
| **F8** | \(RMS=\sqrt{\frac{1}{n}\sum a_i^2}\) | RMS / RMSA | m/s² → m/s² | `metrics/rmsa.py::rms` | RMS(const)=abs(const) |
| **R1** | \(RMSA\_3D=\sqrt{\frac{1}{n}\sum (a_x^2+a_y^2+a_z^2)}\) | 3D RMSA continuity metric | m/s² → m/s² | `metrics/rmsa.py::rmsa_3d` | isotropic const components check |
| **F9** | Welch PSD | PSD curve | m/s² → (m/s²)²/Hz | `metrics/psd.py::welch_psd` | PSD integral ≈ variance (approx) |
| **F10** | \(P=\int_{f_1}^{f_2}PSD(f)\,df\), \(\sqrt{P}\) | √PSD scalar (band power sqrt) | PSD → m/s² | `metrics/psd.py::psd_scalar_band_power_sqrt` | amplitude↑ ⇒ scalar↑ |
| **F10b** | \(\sqrt{\mathrm{mean}(PSD)}\) | √PSD scalar mean | PSD → m/s² | `metrics/psd.py::psd_scalar_mean_sqrt` | stable on noise |
| **F10c** | \(\sqrt{\mathrm{median}(PSD)}\) | √PSD scalar median | PSD → m/s² | `metrics/psd.py::psd_scalar_median_sqrt` | robust to outliers |
| **F11** | \(IRI=A\sqrt{PSD}+B\) | PSD→IRI estimate | m/s² → m/km | `metrics/iri_models.py::iri_psd_linear` | linearity vs A,B |
| **F12** | \(IRI=c_1G_{rms}+c_2Speed+\dots+c_0\) | Multi-linear IRI demo | mixed → m/km | `metrics/iri_models.py::iri_multi_linear` | synthetic expected output |
| **F14** | STOP/SLOW/MOVING thresholds | Motion states | km/h,s → state | `preprocessing/traffic.py::classify_motion_states` | synthetic speed profile |
| **F15** | `valid = MOVING ∧ ¬turn ∧ ¬hard_*` | Roughness mask | — | `preprocessing/quality.py::validity_mask` | braking/turn invalid |
| **F17** | \(z=\frac{|x-\mathrm{median}|}{1.4826\cdot MAD}\) | Robust peaks | m/s² → events | `metrics/peaks.py::detect_peaks_mad` | spike detection |
| **F18** | Interpolate \(a(t)\to a(s)\) | Distance-domain resample | time→distance | `segmentation/by_distance.py::resample_to_distance` | monotonic s |
| **F19** | Segment metrics on \([s_0,s_1]\) | 100m segments | mixed → row | `segmentation/by_distance.py::compute_segment_metrics` | segment sum≈total |

---

## Minimal test suite mapping (recommended)
- `tests/test_geo.py` → F1, F2, F3
- `tests/test_sampling_quality.py` → F4, F5, F6
- `tests/test_gravity.py` → G1, G2
- `tests/test_filters.py` → F7
- `tests/test_metrics.py` → F8, R1, F9, F10, F11, F12
- `tests/test_traffic.py` → F14
- `tests/test_quality_masks.py` → F15
- `tests/test_peaks.py` → F17
- `tests/test_segmentation_distance.py` → F18, F19


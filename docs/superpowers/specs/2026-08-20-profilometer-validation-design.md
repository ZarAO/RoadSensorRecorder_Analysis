# Smartphone-vs-Profilometer Validation and Eq.3 Calibration — Study Design

**Date:** 2026-08-20
**Status:** methodology spec (roadmap P0.1/P0.2); dissertation-core study
**Branch:** `v1-1-stage`

## 1. Purpose and claims under test

1. **Validation:** how well do the smartphone pipeline's roughness metrics
   (`sqrtPSD`, `grms`, `iri_multi`) rank and track certified profilometer IRI
   over the same road sections?
2. **Calibration (P0.1):** fit device-specific Eq.3 coefficients
   `IRI = A·sqrtPSD + B` against profilometer ground truth, producing the first
   usable `iri_psd` for this phone/vehicle — as a NEW named coefficient set;
   the book values stay untouched (integrity rule reconciliation, §7).
3. **Reliability finding:** the pre-v1.1 app loses GPS during screen-off drives
   (13 and 27 fixes per ~15-min drive vs 870/1089 on v1.1) — old recordings are
   unusable for distance-domain analysis. This is reported as a finding
   motivating Stage A/B, not as a metric comparison.

## 2. Data inventory (from recon, 2026-08-20)

**Ground truth** — «Форма даних про рівність за IRI», measured 2026-06-16,
steps 10/100/1000 m, parsed to tidy CSVs in
`storage/field_measurements/derived/`:

| Section | Span | Direction | Category | IRI (ch. mean) |
|---|---|---|---|---|
| М-03 км19+000–км30+078 | 11 078 m | Прямий | 1 | ≈1.40–1.56 |
| Т1016 км17+000–км0+205 | 16 795 m | Зворотній | 2 | ≈3.0–3.6 (spike 49.5 @10 m) |

Channels: **ch8=ch9=ch10 byte-identical in every file** → only ch1–ch8 carry
information. Interpretation (from inter-channel correlation structure):
multiple lateral sensor tracks of one pass, not repeated passes.
**Decision D1 — reference IRI per interval = mean(ch1..ch8)**; single-channel
sensitivity analysis reported alongside. Note: М-03 filename says «смуга 2»
while the form cell says lane 1 — recorded as a validity threat (§8).

**Smartphone** — 2026-08-20, Samsung SM-S948B, app v1.1 (CSV v3):

| Recording | Section match | Vehicle | Usable |
|---|---|---|---|
| new/…100807 (150 seg, 15.0 km) | М-03, 64% fixes ≤150 m, direction agrees | Ford Transit 2011, van, worn torsion beam, half_load | calibration + validation |
| new/…102552 (168 seg, 16.7 km) | Т1016, 100% fixes ≤150 m (mean 24.8 m) | same Transit | calibration + validation |
| new/…105145 (37 seg, 3.6 km, 92.8 km/h) | none (other route) | Cupra Formentor 2025, crossover, new suspension | vehicle-contrast illustration ONLY |
| old/…130807, old/…132552 | paired to the above by epoch time (≥99.9% overlap) | — (no profile) | reliability finding only |

Pipeline health on the two calibration runs: clean stop, fs=111 Hz,
gravity check OK, dx≤0.3 m share 100%, 0 anomalies (threshold uncalibrated —
noted, not fixed here).

## 3. Geo-matching (smartphone segments ↔ form intervals)

Match in geometry, not chainage (the smartphone `s=0` is arbitrary):

1. Reference geometry: form `_100` files → interval endpoints (lat/lon start,
   lat/lon end per 100 m interval).
2. For each smartphone **full** 100 m segment, compute its midpoint coordinate
   (from the run's GPS track at the segment's mid-chainage `s`).
3. Assign the segment to the form interval whose own midpoint is nearest
   (haversine); accept the pair only if that distance ≤ **60 m** (tolerance =
   interval half-length + GPS error; sensitivity at 40/80 m reported).
4. If several segments land on one interval (or vice versa) keep the nearest
   pair only — one-to-one matching, no double counting.
5. Exclusions: `partial`, `needs_class12_survey`, match distance over
   tolerance, and segments outside the section span (М-03 recording is longer
   than the section).

Direction: both drives were made in the same direction as the corresponding
form (verified: chainage-vs-time Spearman +1.00 / −1.00 against Прямий /
Зворотній), so no direction correction is needed. Lane offset on М-03 (dual
carriageway) is absorbed by the 60 m tolerance and flagged in §8.

The 10 m and 1000 m form steps are not used for the primary fit (10 m is far
below the smartphone's 100 m resolution; 1000 m gives n=12+17 points only);
the 1000 m tables serve as an aggregation cross-check.

## 4. Validation statistics (before any calibration)

Per road and pooled, on matched pairs:

- Spearman ρ and Pearson r: `sqrtPSD` vs IRI_ref, `grms` vs IRI_ref,
  `iri_multi(GENERIC)` vs IRI_ref.
- Bias of the uncalibrated metrics: mean error and MAE of `iri_multi` vs
  IRI_ref (recon preview: underestimates ≈2–5×, and `iri_psd_raw` < 0 on 100%
  of segments — the calibration motivation, reported honestly).
- Bland–Altman (bias, 95% limits of agreement) for `iri_multi` and, after
  calibration, for the calibrated `iri_psd`.

## 5. Calibration protocol (P0.1 primary, P0.2 secondary)

- **Model (primary):** `IRI_ref = A·sqrtPSD + B`, OLS on matched pairs from
  BOTH roads pooled; robust check with Theil–Sen. Fit inputs use the exact
  pipeline scalar (`mean_psd_sqrt`, band 0.5–6 Hz, post distress-removal) —
  the same number Eq.3 consumes in production.
- **Honest error estimate:** leave-one-road-out (LORO): fit on Т1016 → test on
  М-03, and vice versa; report R², MAE, RMSE per held-out road. The FINAL
  published coefficients come from the pooled fit; LORO quantifies transfer
  error. With n(roads)=2 this is stated as a limitation, not hidden.
- **Secondary (P0.2-lite):** `IRI_ref = a·grms + b·v_kmh + c` linear fit, same
  splits — reported for comparison with Eq.6's structure; a full Eq.6 refit
  waits for more roads/vehicles.
- **Success gates (from roadmap P0.1):** pooled R² > 0.85, MAE < 0.5 m/km,
  zero negative calibrated IRI on the study data. If a gate fails, the study
  reports the failure and its likely cause — no coefficient is shipped as
  "calibrated" below the gates; it ships clearly labeled experimental.
- **Provenance label:** coefficient set named `UA_2026_TRANSIT_S948B`
  (road pair М-03/Т1016, date, vehicle, phone) — never a silent replacement.

## 6. Deliverables

1. **Study pipeline** `studies/profilometer_validation/` (tracked):
   - `match.py` — geo-matching (pure functions, unit-tested);
   - `calibrate.py` — fits + statistics (unit-tested on synthetic data);
   - `run_study.py` — end-to-end: reads `storage/results/field_*` +
     `storage/field_measurements/derived/*_100.csv`, writes
     `studies/profilometer_validation/out/` (matched pairs CSV, stats JSON,
     figures PDF+PNG via matplotlib+scienceplots, study report MD);
   - deterministic (research rule): same inputs → identical outputs.
2. **Analyzer change (minimal):** optional `--iri-psd-A/--iri-psd-B` CLI
   flags; default = book values, behavior unchanged (test-pinned); the report
   prints which set was used. `IRI_PSD_COEFFICIENTS` constant untouched.
3. **Figures (scienceplots, PDF+PNG):** scatter `sqrtPSD`→IRI_ref with pooled
   fit and per-road markers; Bland–Altman before/after; chainage profile
   overlay (profilometer vs calibrated smartphone IRI along km, per road).
4. **Docs:** new `docs/10_profilometer_validation.md` (methods + results +
   limitations, UA); `00_index.md` link; `07_future_work_roadmap.md` P0.1
   status update.
5. **Dissertation draft:** `Dissertation/Валідація_смартфон_vs_профілометр.docx`
   (UA, academic structure: постановка → дані → методика → результати →
   обмеження → висновки; taблиці + фігури; no fabricated citations — the form
   is cited as the document it is; Eq.3 source cited as the ADB guidebook).
   Built with python-docx per the office-export skill; hidden-character scan
   before handoff (repo rule).

## 7. Integrity reconciliation (the no-retune rule vs P0.1)

`research-python.md`: “Never retune published IRI equation coefficients to
fit a dataset.” — bans silent in-place edits of the book constants.
Roadmap P0.1 prescribes a formal recalibration against independent
profilometer ground truth. Reconciliation applied here:

1. book constants in `iri.py` stay byte-identical (test-pinned);
2. fitted values live in the study output + optional CLI flags with a
   provenance name, and the run report states which set produced the numbers;
3. ground truth is independent (certified device, different date/operator);
4. R²/MAE/LORO and n are published next to the coefficients.

## 8. Threats to validity (reported in every deliverable)

- **Time gap:** profilometer 2026-06-16 vs smartphone 2026-08-20 (2 months;
  summer — low structural change expected, but unverified).
- **Lane ambiguity on М-03:** filename «смуга 2» vs form cell lane 1; dual
  carriageway; our lane unrecorded. Т1016 (single carriageway, 100% overlap)
  is the cleaner pair.
- **Channel semantics assumed** (8 lateral tracks averaged); single-channel
  sensitivity reported.
- **One vehicle/phone for calibration** (worn-suspension van — likely
  atypical); coefficients are explicitly device+vehicle-specific.
- **n(roads)=2**, one pass each; no repeatability estimate.
- **Anomaly threshold uncalibrated** (0 anomalies on a category-2 road with
  spikes to 49.5 m/km @10 m) — distress-removal step effectively inactive on
  this data; noted for P0 follow-up.

## 9. Non-goals

No modification of pipeline physics (filters, bands, segmentation); no Eq.6
refit; no web-admin integration of study outputs (possible Phase 2+); no
claims beyond the two roads / one vehicle / one phone actually measured.

## Amendment A1 (2026-08-20, after the first iteration + adversarial review)

Documented changes to §3/§5/§8 — the original text above is kept for the
record; this section overrides where it conflicts.

**A1.1 Primary matching switched to a windowed 10 m reference.** The first
iteration exposed a systematic grid-phase offset between the two independent
100 m partitions (constant ~41 m on Т1016, ~27 m on М-03): nearest-interval
matching mixes ~40% of a neighboring interval into every pair. The primary
pairing is now: project each segment's geojson endpoints onto the 10 m form
chainage (endpoint tolerance 60 m) and average the 10 m reference IRI over
that half-open window; windows with < 9 reference rows are excluded
(boundary-degraded). §3's original statement that the 10 m step "is not used
for the primary fit" is superseded: the 10 m rows are AVERAGED over ~100 m
windows, so no sub-resolution claim is made. The original nearest-100 matcher
is retained as a sensitivity check.

**A1.2 No device-wide Eq.3 coefficient is published.** Per-road Eq.3 slopes
disagree in sign (М-03 ≈ 0/negative, n.s. — range restriction; Т1016 positive)
— the pooled slope is a two-road contrast (df=1 between clusters), not a
device property. The planned `UA_2026_TRANSIT_S948B` set is therefore NOT
shipped; the CLI flags remain for future multi-road calibration. Gates P0.1:
honestly failed.

**A1.3 Reporting rules.** Per-road numbers are the headline; pooled values
are always labeled as carrying the between-road contrast. Every fitted model
(count disclosed) is reported with LORO. A speed-only baseline quantifies
speed endogeneity (the driver slows on rough spots, so speed itself predicts
the reference; any speed-bearing model partly measures driver behavior).
Effective sample sizes under lag-1 autocorrelation are reported; nominal-n
p-values are not to be quoted as precision claims. The bias correction of
Eq.6 is reported both in-sample (optimistic by construction) and LORO.

**A1.4 Corrected threat statements (supersede §8 wording).**
- Lane on М-03: a lane offset is a systematic difference of pavement surface
  (different rutting/fatigue), NOT an error absorbed by a longitudinal
  tolerance; the form metadata (lane 1) contradicts the filename («смуга 2»)
  and the conflict is unresolved. М-03 results carry this unquantified threat.
- Time gap: June 16 → August 20 spans the peak road-repair season; "low
  structural change" is NOT assumed. The roughest Т1016 windows (which carry
  the fit's leverage) are exactly the most likely to have been repaired.
- Channel semantics: correlation structure cannot distinguish lateral tracks
  from repeated passes or processing variants; mean(ch1..ch8) is an assumed
  lane summary, not a wheelpath IRI (ASTM MRI uses two wheelpaths). The
  lateral gradient differs between roads (Т1016 monotone 0.59 m/km spread,
  18% of mean), which perturbs the between-road contrast. Single-channel
  sensitivity is reported.
- М-03 null result: the profilometer's Spearman-Brown composite reliability
  on М-03 gives an attainable correlation ceiling ≈ 0.97, so the null is a
  genuine smartphone sensitivity limit in the 1.1–1.8 m/km band, not
  reference noise.


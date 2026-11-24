# Calibration model of the smartphone IRI estimate and the base-vs-improved proof (design)

Date: 2026-11-15. Status: approved 2026-11-15 with operator field constraints (§3, §5).

## Goal

The dissertation claims an improved METHOD, so it must contain (1) our own formula with a
derivation, an identification strategy and validated limits, and (2) a numerical proof
that every modification of the base method improves agreement with a reference. This
spec defines both as a deterministic study in `studies/profilometer_validation` and the
field data each step needs.

## 1. The model

R is the UNCLIPPED linear predictor of the guidebook regression path (Eq.6, nominal
vehicle parameters): `R = 50.32·Grms − 0.06·v + 3.31` (m/km; 3.31 = 0.17 − 1.86 −
0.90 − 0.78 + 6.68). The published `iri_multi = max(0, R)` loses information below zero
(97–99 % of the smooth-road pairs are clipped), so calibration acts on R and clipping
comes last:

```
IRI_cal = max(0, γ · [R − β · (v − v0)] + δ)                      (M1)
```

- β (m/km per km/h): residual speed effect of the phone–vehicle pair beyond the book
  term, identified ONLY from within-bin variation across passes of the same section
  at different speeds (bin fixed effects, `aggregate.py` demeaned estimator). Using the
  same section removes the endogeneity shown in §4.5 (drivers slow down on bad road).
- γ (dimensionless, amplitude) and δ (m/km, offset): inverse calibration, OLS of the
  reference IRI on the speed-normalised predictor `R_v0 = R − β·(v − v0)` across bins
  of all sections; v0 = 50 km/h (reported; it only moves δ).
- Candidate M2, pre-declared: the same with a sensor/vehicle noise floor removed in
  quadrature, `Grms_road = sqrt(max(0, Grms² − G0²))`, G0 estimated on the smoothest
  sections. M1 vs M2 is decided by leave-one-section-out MAE only (rule fixed now).

The book coefficients are not touched (research rule): the model is a calibration
layer on the book output, like the bias correction it generalises (bias-only = γ = 1,
β = 0).

## 2. Pilot on existing data (2026-11-15, scratch; becomes a study block)

Fit on the van, Т1016: γ = 1.845, δ = 0.255. MAE: van Т1016 0.522 (bias-only 0.651);
Cupra Т1016 0.597 (bias-only 0.709); share of reference on rough bins (≥ 6 m/km)
0.81 for the Cupra (bias-only 0.62). Fails on М-03: MAE 1.950 (bias-only 0.164),
because R there is −0.78…0.25 at 74–79 km/h — outside the fitted range and confounded
with speed. Conclusion: γ is real and transfers between vehicles on one road; β and
the low end need sections of different roughness driven at several speeds.

## 3. Validation and pre-declared gates

- Headline = EXTERNAL validation: fit on the G3 sections, test on the two
  profilometer roads (М-03, Т1016: other roads, other instrument, van and Cupra
  passes). With only 2–3 G3 sections (operator constraint, 2026-11-15) this is the
  check that does not reuse any fitted section.
- Leave-one-section-out (LOSO) across all sections (G3 + profilometer roads),
  spatial block cross-validation inside a section (200 m blocks, so autocorrelated
  neighbours never sit in train and test at once) and leave-one-vehicle-out (LOVO);
  in-sample numbers are never the headline.
- Uncertainty of γ, δ, β: block bootstrap by section (seeded), and n_eff-based CIs.
- Gates (fixed before the campaign): LOSO MAE < 0.5 m/km on rough AND smooth
  sections; mean predicted/reference on rough bins within 0.9–1.1; DSTU 3587 level
  agreement not worse than bias-only; ρ unchanged (monotone map). A failed gate is
  reported as a result, not hidden.

## 4. Base vs improved (ablation) on the same data

Every variant is run on the same recordings and matched to the same reference with the
same matcher; metrics: ρ, LOSO MAE, rough-bin ratio, DSTU level agreement, coverage.

| Variant | What is switched off | Needs |
|---|---|---|
| V_full | nothing (pipeline + M1/M2) | study |
| V_bias | calibration = bias only | study |
| V_book | no calibration (published Eq.6) | study |
| V_no_orient | gravity alignment off (device axis, gravity-mean removed) | analyzer flag |
| V_time_seg | 100 m segments replaced by fixed time windows | analyzer flag |
| V_no_speed_gate | IRI also for v < 20 and v > 100 km/h | analyzer policy (exists) |

Analyzer flags are experimental, default off, and pinned by tests so that the published
outputs stay byte-identical.

## 5. Field data needed (campaign protocol additions)

Operator constraints (2026-11-15): walking long sections on traffic roads is unsafe,
and rough roads cannot be driven fast without damaging the car. Hence:

- 2, at most 3 G3 sections of 600–700 m (>= 5 full 100 m segments per pass when the
  car starts and stops >= 100 m outside): one smooth (anchors the low end where М-03
  failed) and one rough AND internally uneven (the within-section range identifies γ);
  a third, medium one if possible. Low-traffic roads; each lane its own reference
  (>= 2 G3 passes in one marked wheel path, same-day calibration).
- Speeds follow the road, never the other way round: what identifies β is the spread
  between passes OF THE SAME SECTION (>= 15 km/h), not high speed. Rough: about
  20–25 / 30 / 40 km/h (never below 20 km/h, the analyzer's low-speed bound);
  smooth: about 40 / 55 / 70 km/h. An unsafe speed is skipped: 2 speeds still
  identify β, less precisely, and the CI shows it.
- Same phone, mount and vehicle configuration (one vehicle_id); a second vehicle
  optional for LOVO.

## 6. Now vs after the campaign

Now: unclipped column `iri_multi_raw` in the analyzer (additive); `calibration_model.py`
(fit/apply M1/M2, LOSO/LOVO, bootstrap) with tests; pilot block in the study; ablation
flags and the ablation block on the profilometer data; dissertation §2 (derivation) and
§4 (pilot, ablation). After the campaign: β, final γ/δ/G0, gates, §4.7, article 2.

## 7. Amendment 2026-11-21: first G3 section campaign (study block)

First campaign done: one rough section (G3 2026-11-21, about 1.2 km, mean IRI about
8.3 m/km, 100 m means 3.2-12.7), one lane, two G3 passes in one wheel path (Standard
Profiling; calibration dated 2026-01-29, not the survey day - stated as a limitation),
the Cupra at 30 / 40 / 50 / 60 km/h in the surveyed lane.

Block `g3_section_campaign` of `run_study.py` (inputs and numbers: docs/10):

- the reference is rebuilt from the raw G3 exports on every run; the segments are the
  analyzer CLI output with defaults; the matcher and its parameters are unchanged;
- beta from the four passes (within-bin estimator, t interval with dof =
  n_rows - n_bins - 1); leave-one-run-out re-estimates beta without the held-out pass
  (`calibration_model.leave_one_run_out`) - the error at an unseen speed;
- spatial block CV (200 m) uses the beta of all passes and is reported next to the
  bias-only baseline; block bootstrap of gamma/delta;
- external check on the profilometer roads with the same car (other tyres), nothing
  refitted, with the share of pairs inside the fitted speed and IRI ranges.

The gates of section 3 are defined on leave-one-section-out and are evaluated after the
second section; until then the block reports, it does not pass or fail. The next
section should be smooth (IRI about 1-3 m/km): one rough section does not identify
gamma (bootstrap CI 0.03-1.27).

## 8. Amendment 2026-11-22: second G3 section, gates evaluated

Second section done: about 390 m, rough (lane IRI 3.8-14.5 m/km on 10 m, mean 7.9),
both wheel paths there and back (Fast Profiling), the Cupra at 40 / 50 / 60 / 70 km/h.
The first odometer calibration of the day was wrong (factor 1.16176); the surveys used
are the tablet app's own REPROCESS with the factor of the second, taped calibration
(0.99483), documented in the field folder README. The section was meant to be moderate
(IRI 2.5-4, corrected from "smooth" on 2026-11-22: below IRI 2 the raw Eq.6 output is
mostly negative); a rough one was what could be found within the time budget.

Block `g3_two_sections` of `run_study.py` (block `g3_section_campaign` unchanged):

- per-section book error, constant offset k and beta; pooled beta and M1;
- leave-one-section-out over the G3 sections with beta, gamma, delta re-estimated on the
  training section (`calibration_model.leave_one_section_out`);
- the gates of section 3 on four held-out sets (each G3 section with the model of the
  other, each profilometer road with the model of both). "rho unchanged" is read as
  Spearman of M1 not lower than that of the book estimate.

Outcome (numbers: docs/10): the constant offset reproduces across sections (k 3.01 and
3.02 m/km) and transfers to the unseen section (MAE 3.03 -> 0.83); beta is identified
only by the long section (pooled 0.099 [0.069; 0.129]); gamma is not identified. The
MAE < 0.5 gate fails on all four held-out sets; the full model is not validated on
these data. A section with IRI 2.5-4 m/km is still the missing design point.

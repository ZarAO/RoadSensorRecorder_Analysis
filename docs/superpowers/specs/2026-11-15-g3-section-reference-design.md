# Walking Profiler G3 as a section reference (design)

Date: 2026-11-15. Status: implemented 2026-11-15 (operator fork: "section = reference, G3 passes = channels").

## Goal

Let the web admin use ARRB Walking Profiler G3 surveys as a reference next to the
profilometer xlsx form, so a smartphone run can be compared with a class-1 walking
profiler on short calibration sections (article 2, roadmap: G3 calibration).

## Decisions

1. **One reference = one road section; each G3 pass is a channel** (max 8), exactly
   like the 8 channels of the profilometer form. `iri_ref` stays the mean of the
   available channels, so pass-to-pass disagreement of the reference is visible in
   the existing "channel range" column and comparable with the profilometer case.
   Channels are meant to be repeats of ONE wheel path: passes of different lanes
   (the 2026-11-14 surveys went out in one lane and back in the other, on purpose)
   belong to separate references, each compared with the car pass in that lane.
2. **Same stored format.** The derived CSV keeps the profilometer column set
   (`km_*`, `m_*`, `iri_ch1..10`, `lat/lon/alt_start/end`); unused channels are
   empty, so `load_form_10m`, `load_reference_intervals` and the comparison job work
   unchanged (`mean(axis=1)` skips NaN). Step 10 m; chainage = metres from the start
   of the master pass (`km_* = 0`). Only full 10 m intervals are kept.
3. **10 m IRI = length-weighted mean of the device's 1 m IRI** (IRI is additive over
   length: it is the mean rectified slope of the quarter-car response).
4. **Master pass** = earliest survey (Information.txt Date/Time; file order if
   absent). Other passes are mapped onto its chainage:
   - by **profile cross-correlation** (25 mm profile, band 0.5–30 m, both
     directions, |lag| <= 50 m, overlap >= 100 m), accepted when the peak r >= 0.4;
   - otherwise by **GNSS**: direction from which master end the pass starts at,
     offset from projecting the pass start onto the master track; recorded as a
     warning with the rejected r.
   A pass covers a master interval only if it covers >= 90 % of its length.
5. **Coordinates** of interval ends come from the master's GNSS.csv by distance.
   Both device GNSS formats are read: the original (speed with a decimal comma) and
   the corrected one written by `scripts/georef_g3_spoofed.py`.
6. **Quality warnings** (Ukrainian, shown with the existing warnings icon):
   calibration (accelerometer/odometer/field offset) not done on the survey day;
   Reference Profiling speed above 1.1 km/h for a share of the pass; surface setting;
   each channel's alignment method and r; mean absolute difference between channels
   at 10 m.
7. **Upload**: `POST /references/g3`, multipart `files` = for every pass its
   ` IRI.csv`, ` GNSS.csv`, ` Profile.csv` (required) and ` Information.txt`
   (optional), grouped by the survey prefix; `road_name` required; `measured_at`
   optional (defaults to the master survey date). Unique `filename` =
   `G3 <date> <title1>+<title2>...`. Sources are kept under
   `storage/reference/<id>/source/`. 422 (Ukrainian) on a missing part or > 8 passes.
8. **Model**: `ReferenceDataset.kind` (`profilometer_form` | `walking_profiler_g3`,
   default for old rows) and `channels` (JSON list: survey, date_time, quality,
   direction, alignment, r, lag_m, length_m). Added by `_ADDED_COLUMNS`.
9. **UI**: calibration page gets a second upload row for G3 (multi-file picker, road
   name, optional date) and a kind chip in the references table; the reference
   detail page lists the channels with their surveys.

## Out of scope

Texture (MPD/ETD) — the surveys of 2026-11-14 used the "Concrete" setting on asphalt.
ProVAL/PPF parsing. Multi-day G3 merging rules beyond "passes of one section".

## Tests

Library: parsers (both GNSS formats), 10 m weighting, alignment of a synthetic
shifted/reversed profile, GNSS fallback, coverage rule, warnings. Backend: upload
201 with channels and kind, 422 cases, intervals endpoint mean over available
channels, comparison accepts a G3 reference. Frontend: upload call shape, kind chip.

# IDE Agent Prompt Pack (UNIFIED) — RoadSensorRecorder_Analysis (Python)

**Repo:** https://github.com/ZarAO/RoadSensorRecorder_Analysis  
**Branch target:** `v-ghc-1` (current app structure with `main.py` + `modules/`)

✅ **Important constraints**
- The IDE agent **must NOT** read any PDF or external document.
- This pack is self-contained: requirements, formulas, units, tests, outputs are specified here.
- This pack is **compatible** with your current `v-ghc-1` layout and also upgrades toward a clean `road_quality_analyzer` package.

---

## What this pack changes vs the previous 6-file pack
- Keeps the strong **v2 structure/plan** + **v3–v4 math**.
- Removes ambiguity between:
  - `python main.py` (legacy runner)  
  - `python -m road_quality_analyzer analyze ...` (new reproducible CLI)
- Defines a **single output contract**, plus an optional **legacy-export compatibility** mode.
- Adds the pieces that exist in `v-ghc-1` already (gravity compensation + RMSA_3D) so they are not lost.

---

## How to use in VS Code (GitHub Copilot Agent)
1. In your repo, create folder: `agent_prompt_pack/`
2. Copy these 6 files into it:
   - `00_README_AGENT_UNIFIED.md`
   - `01_PLAN_STRUCTURE_UNIFIED.md`
   - `02_FORMULAS_TEST_MAP_UNIFIED.md`
   - `03_METHODS_AND_FLAGS_UNIFIED.md`
   - `04_ACCEPTANCE_CHECKLIST_UNIFIED.md`
   - `05_PROMPT_TO_PASTE_UNIFIED.md`
3. Paste the content of `05_PROMPT_TO_PASTE_UNIFIED.md` into Copilot Agent.

---

## Canonical run command (must work)
```bash
python -m road_quality_analyzer analyze --input sensor_data_20250729_163334.csv --config configs/default.yaml --out out/run_001
```

## Legacy compatibility (must keep working)
`python main.py` must still run.
- Either as a thin wrapper that calls the canonical CLI, OR
- It reproduces the canonical artifacts in `results/...` and prints where outputs are.

---

## Output contract (canonical)
In `--out`:
- `segments.csv`
- `events.geojson`
- `roughness.geojson`
- `traffic_events.csv`
- `segments_map.html`
- `plots/*.png`
- `report.md`

Optional legacy-export (if enabled): also write in `results/results_<timestamp>/` with existing naming.

---

## File map (read in order)
1) `01_PLAN_STRUCTURE_UNIFIED.md` — architecture + step-by-step implementation plan (primary guide)  
2) `02_FORMULAS_TEST_MAP_UNIFIED.md` — formulas + units + formula→code→test mapping  
3) `03_METHODS_AND_FLAGS_UNIFIED.md` — behavior rules, traffic/low-speed handling, quality flags, outputs  
4) `04_ACCEPTANCE_CHECKLIST_UNIFIED.md` — DoD + runbook  
5) `05_PROMPT_TO_PASTE_UNIFIED.md` — single message to paste into the agent


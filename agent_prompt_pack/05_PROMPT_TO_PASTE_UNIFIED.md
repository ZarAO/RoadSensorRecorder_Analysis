# 05 — Prompt to Paste into VS Code Copilot Agent (UNIFIED)

Paste the following message to the Copilot Agent (verbatim).  
Assume the pack is in the repo at `agent_prompt_pack/`.

---

**INSTRUCTIONS FOR THE IDE AGENT**

You are a coding agent working inside this repository (Python).  
You must NOT read any PDFs or external documents.  
All requirements, formulas, units, and tests are fully specified in the prompt pack.

### What you must do
1) Read and follow these files **in order**:
- `agent_prompt_pack/01_PLAN_STRUCTURE_UNIFIED.md` (primary plan + architecture)
- `agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md` (math + units + formula→code→test mapping)
- `agent_prompt_pack/03_METHODS_AND_FLAGS_UNIFIED.md` (behavior rules, traffic/low-speed, quality flags, outputs)
- `agent_prompt_pack/04_ACCEPTANCE_CHECKLIST_UNIFIED.md` (Definition of Done)

2) Implement the end-to-end pipeline so that this canonical command works deterministically:
```bash
python -m road_quality_analyzer analyze --input sensor_data_20250729_163334.csv --config configs/default.yaml --out out/run_001
```

3) Produce all required canonical artifacts in `out/run_001/`:
- `segments.csv`
- `events.geojson`
- `roughness.geojson`
- `traffic_events.csv`
- `segments_map.html`
- `plots/*.png`
- `report.md`

4) Keep legacy compatibility:
- `python main.py` must still run.
- Prefer making `main.py` a thin wrapper over the canonical CLI.
- If `output.legacy_export.enabled=true`, export legacy outputs in `results/results_<timestamp>/`.

5) Implement every formula/function/test listed in `02_FORMULAS_TEST_MAP_UNIFIED.md`:
- Do not invent formulas.
- Keep units explicit.
- Add `docs/formulas.md` and `docs/methodology.md` consistent with code.

6) Handle real-world low-speed and stop-and-go:
- do NOT crash or refuse when speed < 20 km/h
- compute roughness only on valid motion intervals or mark low confidence
- still detect defects at low speed (with appropriate validity rules)
- use distance-domain segmentation (100 m default)

### Working style requirements
- Start with baseline: run existing code and record findings in `docs/baseline.md`.
- Work in small commits. After each milestone, run tests.
- Add lint + tests + CI (ruff + pytest + GitHub Actions).

If anything is ambiguous, proceed with defaults from `configs/default.yaml` and mark uncertainty with flags (do not block the pipeline).

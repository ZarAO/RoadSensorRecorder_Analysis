# Paper Assets — Стабільні артефакти для статті

**Призначення:** Копії таблиць та графіків з STAGE 2 comparison для вставки у наукову публікацію.

---

## Структура

```
paper_assets/
├── tables/          (4 CSV файли)
├── figures/         (4 PNG файли)
└── README.md        (цей файл)
```

---

## Tables (Таблиці)

### Table 1: Overall Metrics

**Файл:** `tables/table_metrics_overall.csv`

**Зміст:**
- `total_distance_m`: 15140.7 м (сумарна довжина маршруту)
- `legacy_num_segments`: 1799 (time-based)
- `new_num_segments`: 153 (100m distance-based)
- `legacy_rmsa_mean`: 0.3335 m/s² (body-frame, gravity-contaminated)
- `new_grms_mean`: 0.0590 g (world-frame, gravity-corrected)
- `new_iri_multi_mean`: 3.78 m/km (multivariable IRI, GOOD classification)

**Використання у статті:**
```markdown
**Table 1.** Overall comparison metrics (legacy vs new pipeline)

| Metric | Legacy | New |
|--------|--------|-----|
| Distance (m) | 15140.7 | 15140.7 |
| Segments | 1799 (time-based) | 153 (100m bins) |
| Mean roughness | RMSA=0.334 m/s² | Grms=0.059g, IRI=3.78 m/km |
```

---

### Table 2: Rank Correlation

**Файл:** `tables/table_rank_correlation.csv`

**Зміст:**
- `pair`: metric pairs ("iri_multi_vs_legacy_rmsa", "grms_vs_legacy_rmsa")
- `spearman_rho`: 0.7828, 0.9420
- `p_value`: 1.01e-32, 4.80e-73
- `n_overlap`: 152, 152
- `interpretation`: "strong positive", "very strong positive"

**Використання у статті:**
```markdown
**Table 2.** Spearman rank correlation between new metrics and legacy RMSA

| Metric Pair | ρ (Spearman) | p-value | n | Interpretation |
|-------------|--------------|---------|---|----------------|
| IRI_multi vs RMSA | 0.783 | 1.01×10⁻³² | 152 | Strong positive |
| Grms vs RMSA | 0.942 | 4.80×10⁻⁷³ | 152 | Very strong |
```

---

### Table 3: Per-Segment Metrics (100m)

**Файл:** `tables/table_metrics_per_100m.csv`

**Зміст:** 153 рядки (по одному на 100m сегмент)

**Columns:**
- `segment_id`, `distance_start_m`, `distance_end_m`
- `legacy_rmsa`, `new_grms`, `new_iri_multi`
- `legacy_valid_ratio`, `new_valid_ratio`

**Використання:** Детальні дані для додатків (Appendix A) або online repository

---

### Table 4: Top 10 Worst Segments

**Файл:** `tables/table_top10_worst_segments.csv`

**Зміст:** 10 найгірших сегментів за IRI_multi

**Columns:**
- `segment_id`, `distance_start_m`, `iri_multi`, `grms`, `speed_median_kmh`

**Використання:**
```markdown
**Table 4.** Top 10 roughest segments (by IRI_multi)

| Segment | Distance (m) | IRI (m/km) | Grms (g) | Speed (km/h) |
|---------|--------------|------------|----------|--------------|
| 102 | 10200-10300 | 8.12 | 0.108 | 35.2 |
| ... | ... | ... | ... | ... |
```

---

## Figures (Графіки)

### Figure 1: IRI_multi vs Legacy RMSA Scatter

**Файл:** `figures/fig1_iri_vs_rmsa_scatter.png`

**Розмір:** ~100 KB, 1200×800 px (300 DPI для друку)

**Зміст:**
- X-axis: Legacy RMSA (m/s²)
- Y-axis: New IRI_multi (m/km)
- 152 points (100m-aligned segments)
- Linear regression line (R² displayed)
- Spearman ρ = 0.783 annotation

**Підпис для статті:**
```markdown
**Figure 1.** Scatter plot: New IRI_multi vs Legacy RMSA.  
Strong positive correlation (Spearman ρ = 0.783, p < 0.0001, n = 152).  
Despite 5.6x difference in absolute values (gravity contamination),  
ranking of road roughness is preserved.
```

---

### Figure 2: Grms vs Legacy RMSA Scatter

**Файл:** `figures/fig2_grms_vs_rmsa_scatter.png`

**Розмір:** ~100 KB, 1200×800 px

**Зміст:**
- X-axis: Legacy RMSA (m/s²)
- Y-axis: New Grms (g)
- 152 points
- Spearman ρ = 0.942 (very strong correlation)

**Підпис для статті:**
```markdown
**Figure 2.** Scatter plot: New Grms vs Legacy RMSA.  
Very strong correlation (ρ = 0.942, p < 10⁻⁷⁰).  
Grms captures same vibration patterns as RMSA, but gravity-corrected  
(world-frame alignment reduces contamination from 0.334 to 0.059 m/s²).
```

---

### Figure 3: Speed Profile (100m bins)

**Файл:** `figures/fig3_speed_profile.png`

**Розмір:** ~80 KB, 1200×600 px

**Зміст:**
- X-axis: Distance (m)
- Y-axis: Median speed (km/h) per 100m segment
- Line plot showing speed variability (15-67 km/h range)
- Context for dx compliance (high speed → dx > 0.3m)

**Підпис для статті:**
```markdown
**Figure 3.** Speed profile along route (100m segments).  
Mean speed: 41.7 km/h, range: 15-67 km/h.  
Variability indicates urban mixed-traffic conditions (stop-and-go),  
affecting sampling compliance (dx ≤ 0.3m requirement at fs = 52.6 Hz).
```

---

### Figure 4: Top 10 Segments Bar Chart

**Файл:** `figures/fig4_top10_segments.png`

**Розмір:** ~70 KB, 1200×800 px

**Зміст:**
- X-axis: Segment ID
- Y-axis: IRI_multi (m/km)
- Bar chart (highest to lowest)
- Color-coded by IRI classification (orange/red for poor/very poor)

**Підпис для статті:**
```markdown
**Figure 4.** Top 10 roughest road segments (by IRI_multi).  
Segment 102 (10.2-10.3 km) shows worst roughness: IRI = 8.12 m/km  
(WorldBank classification: POOR, approaching VERY POOR threshold).  
Segments concentrated around 10-11 km mark suggest localized distress zone.
```

---

## Як використати у LaTeX

### Вставка таблиці

```latex
\begin{table}[ht]
\centering
\caption{Overall comparison metrics (legacy vs new pipeline)}
\label{tab:overall_metrics}
\begin{tabular}{lcc}
\toprule
Metric & Legacy & New \\
\midrule
Distance (m) & 15140.7 & 15140.7 \\
Segments & 1799 (time-based) & 153 (100m bins) \\
Mean roughness & RMSA=0.334 m/s² & Grms=0.059g, IRI=3.78 m/km \\
\bottomrule
\end{tabular}
\end{table}
```

### Вставка графіку

```latex
\begin{figure}[ht]
\centering
\includegraphics[width=0.8\textwidth]{paper_assets/figures/fig1_iri_vs_rmsa_scatter.png}
\caption{Scatter plot: New IRI\_multi vs Legacy RMSA. Strong positive correlation (Spearman $\rho = 0.783$, $p < 0.0001$, $n = 152$).}
\label{fig:iri_vs_rmsa}
\end{figure}
```

---

## Посилання у тексті (Markdown)

### Table

```markdown
As shown in Table 1 (see `paper_assets/tables/table_metrics_overall.csv`),
the new pipeline produces 153 distance-based segments compared to 1799 time-based
segments in the legacy approach.
```

### Figure

```markdown
Figure 1 demonstrates strong correlation (ρ = 0.783) between new IRI\_multi
and legacy RMSA, despite fundamental methodological differences
(see `paper_assets/figures/fig1_iri_vs_rmsa_scatter.png`).
```

---

## Версія даних

**Джерело:** STAGE 2 comparison output (`out/comparison/analysis/`)

**Генерація:**
```powershell
python tools/compare_runs_v2.py \
  --legacy results/legacy_20250729/ \
  --new results/new_20250729/ \
  --input data/sensor_data_20250729_163334.csv \
  --out out/comparison
```

**Дата генерації:** 2026-01-10 (STAGE 2)

**Commit hash:** `<поточний commit>` (see STAGE5_COMPLETION.md)

---

## Ліцензія

**Assets:** CC BY 4.0 (Creative Commons Attribution)  
**Data:** Sensor data збережено у `data/sensor_data_20250729_163334.csv`  
**Code:** MIT License (see repository root)

---

**Note:** Ці файли є стабільними копіями для публікації. Оригінальні артефакти у `out/comparison/analysis/` можуть бути перегенеровані з новими параметрами, але ці копії фіксують результати для статті.

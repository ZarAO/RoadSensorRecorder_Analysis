# Paper Assets — Стабільні артефакти для статті

**Призначення:** Копії таблиць та графіків з STAGE 2 comparison для вставки у наукову публікацію.

> ⚠ **Історичний зріз.** Це вихід прогону STAGE 2 (скрипт `tools/compare_runs_v2.py`
> та legacy-код, обидва видалені з репозиторію). Поточний пайплайн на тому самому
> CSV дає інші числа (152 сегменти, 15123.7 м, mean Grms 0.0467 g, mean IRI_multi
> 2.99 m/km) — див. [../05_results_legacy_vs_new.md](../05_results_legacy_vs_new.md).
> Таблиці містять і службовий сегмент `seg_id = -1`, який поточний код більше не
> створює.

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

**Зміст** (реальні назви колонок файлу):
- `distance_m`: 15140.7 м (сумарна довжина маршруту)
- `mean_speed_kmh`: 41.66
- `legacy_segments_count`: 1799 (time-based)
- `new_segments_count`: 153 (100m distance-based)
- `legacy_rmsa_mean` / `legacy_rmsa_median`: 0.3335 / 0.2778 m/s² (body-frame)
- `new_grms_mean` / `new_grms_median`: 0.0590 / 0.0544 g (world-frame)
- `new_iri_multi_mean` / `new_iri_multi_median`: 3.78 / 3.60 m/km
- `legacy_peaks_total`: 1799, `new_threshold_anomalies_total`: 0
- колонки `duration_s`, `fs_hz`, `dx_mean_m`, `dx_p95_m`, `share_dx_le_0_3m`
  присутні у заголовку, але порожні

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

**Зміст** (колонки `comparison, spearman_rho, p_value, n_segments`):
- `IRI_multi vs Legacy_RMSA`: ρ = 0.7829, p = 1.01e-32, n = 152
- `Grms vs Legacy_RMSA`: ρ = 0.9421, p = 4.80e-73, n = 152
- `IRI_multi_ranks vs RMSA_ranks`: ρ = 0.7829 (той самий показник на рангах)

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

**Зміст:** 153 рядки (включно зі службовим `seg_id = -1`)

**Columns:**
- `seg_id`, `s_start`, `s_end`
- `iri_multi`, `grms`, `mean_speed_kmh`, `valid_ratio`, `anomaly_count`
- `legacy_rmsa_mean`, `legacy_samples_count`
- `rank_new_iri_multi`, `rank_legacy_rmsa`

**Використання:** Детальні дані для додатків (Appendix A) або online repository

---

### Table 4: Top 10 Worst Segments

**Файл:** `tables/table_top10_worst_segments.csv`

**Зміст:** 10 найгірших сегментів за IRI_multi

**Columns:**
- `seg_id`, `s_start`, `s_end`, `iri_multi`, `grms`, `mean_speed_kmh`,
  `legacy_rmsa_mean`, `legacy_samples_count`
  (медіанної швидкості в жодній таблиці немає — рахується лише середня)

**Використання:**
```markdown
**Table 4.** Top 10 roughest segments (by IRI_multi)

| Segment | Distance (m) | IRI (m/km) | Grms (g) | Speed (km/h) |
|---------|--------------|------------|----------|--------------|
| 91 | 9100-9200 | 7.91 | 0.109 | 15.1 |
| 0 | 0-100 | 7.67 | 0.128 | 34.9 |
| ... | ... | ... | ... | ... |

(перший рядок файлу — службовий `seg_id = -1`, у статтю не йде)
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
- Y-axis: швидкість на 100 м сегмент (у таблицях збережено `mean_speed_kmh`)
- Line plot showing speed variability
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
Segment 91 (9.1-9.2 km) shows worst roughness among real segments:  
IRI = 7.91 m/km (WorldBank classification: POOR).  
Segments concentrated around the 9 km mark suggest a localized distress zone.
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

**Джерело:** STAGE 2 comparison output (`out/comparison/analysis/`; каталог і скрипт
у репозиторії відсутні — ці копії єдині, що лишились)

**Генерація:**
```powershell
python tools/compare_runs_v2.py \
  --legacy storage/results/legacy_20250729/ \
  --new storage/results/new_20250729/ \
  --input storage/data/sensor_data_20250729_163334.csv \
  --out out/comparison
```

**Дата генерації:** 2026-01-10 (STAGE 2)

**Commit hash:** `<поточний commit>` (see STAGE5_COMPLETION.md)

---

## Ліцензія

**Assets:** CC BY 4.0 (Creative Commons Attribution)  
**Data:** Sensor data збережено у `storage/data/sensor_data_20250729_163334.csv`  
**Code:** MIT License (see repository root)

---

**Note:** Ці файли є стабільними копіями для публікації. Оригінальні артефакти у `out/comparison/analysis/` можуть бути перегенеровані з новими параметрами, але ці копії фіксують результати для статті.

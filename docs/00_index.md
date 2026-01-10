# Документація проєкту Road Quality Analyzer

**Версія:** STAGE 3 (2025-01-10)  
**Призначення:** Повна науково-технічна документація для публікацій та відтворення експериментів

---

## Швидкий старт (2 команди)

### 1. Аналіз нових даних
```bash
python -m road_quality_analyzer analyze \
  --input data/sensor_data_20250729_163334.csv \
  --out out/new_analysis
```

### 2. Порівняння legacy vs new (paper-ready)
```bash
python tools/compare_runs_v2.py
```

**Результати:** `out/comparison/analysis/` (таблиці, графіки, GeoJSON)

---

## Навігація документації

### 📘 Теоретична база
- **[01 — Проблематика та постановка задачі](01_background_and_problem_statement.md)**
  - Що таке road roughness та IRI
  - Smartphone-based Class III response-type системи
  - Обмеження сенсорів та GPS
  - Чому потрібні orientation correction та distance-domain

### 🔬 Методологія

- **[02 — Методи нового пайплайну](02_methods_new_pipeline.md)**
  - Детальний алгоритм: ingestion → uniform grid → GPS → orientation → filters → metrics → segmentation
  - Orientation correction: gravity alignment + GPS heading + a_perp
  - Формули з `agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md`:
    - Eq.1: Quarter-car IRI (опціонально)
    - Eq.2-3: IRI з PSD (основний метод)
    - Eq.4-6: Мультиваріантна регресія IRI (vehicle-specific)
  - Sampling compliance: dx ≤ 0.3m, fs 80–120Hz
  - Threshold anomaly: |a_vertical| > 10 m/s²
  - Детермінізм та тестування (22 unit tests)

- **[03 — Методи legacy пайплайну](03_methods_legacy_pipeline.md)**
  - Чесний опис legacy підходу (modules/)
  - Mixed streams, ffill/bfill інтерполяція
  - Body-frame RMSA (без orientation correction)
  - Time-based сегментація (1799 segments)
  - Peak-based anomaly detection (7177 peaks)
  - Чому RMSA вищий: gravity contamination

### 🧪 Експеримент

- **[04 — Експериментальний дизайн та відтворюваність](04_experimental_design_and_reproducibility.md)**
  - Exact reproducibility protocol (input, команди, outputs)
  - Фіксація версій (commit hash, OS, Python 3.13.5)
  - Як повторити на іншому CSV
  - Де знайти артефакти STAGE 2

### 📊 Результати

- **[05 — Результати порівняння legacy vs new](05_results_legacy_vs_new.md)**
  - **Таблиця 1:** Overall metrics ([table_metrics_overall.csv](../out/comparison/analysis/tables/table_metrics_overall.csv))
  - **Таблиця 2:** Rank correlations ([table_rank_correlation.csv](../out/comparison/analysis/tables/table_rank_correlation.csv))
  - **Рис. 1:** IRI_multi vs Legacy RMSA scatter (ρ = 0.783, p < 0.0001)
  - **Рис. 2:** Grms vs Legacy RMSA scatter (ρ = 0.942)
  - **Рис. 3:** Speed profile (контекст для dx compliance)
  - **Рис. 4:** Top 10 worst segments bar chart
  - 100m-aligned comparison (152 overlap segments)
  - Інтерпретація Spearman correlation

### ⚠️ Обмеження

- **[06 — Загрози валідності та обмеження](06_threats_to_validity_and_limitations.md)**
  - Phone mount variability (tilt, vibration)
  - Sampling fs та dx compliance
  - Speed variability / stop-and-go
  - GPS noise and distance errors
  - Orientation estimation assumptions (gravity LPF)
  - Eq.3 calibration mismatch (A, B coefficients)
  - Eq.4-6 simulated vehicle limitations
  - Що вже пом'якшено, що залишається

### 🚀 Майбутнє

- **[07 — Roadmap майбутніх покращень](07_future_work_roadmap.md)**
  - **P0:** Calibration A,B для PSD model (ground truth per segment)
  - **P0:** RF anomaly classifier (a_vertical, a_perp, speed features)
  - **P1:** Sensor fusion з gyro (стабільність у поворотах)
  - **P1:** Multi-device comparison та normalization
  - **P1:** Automatic quality filters (low valid_ratio, invalid heading)
  - **P2:** Quarter-car mode (якщо є road profile)
  - **P2:** External validation campaign (repeat runs, inter-operator)

### 📖 Посібник користувача

- **[08 — User guide та CLI reference](08_user_guide_and_cli_reference.md)**
  - Install/venv setup
  - `analyze` command (всі параметри)
  - `main.py` wrapper (legacy compatibility)
  - Outputs опис (CSV/GeoJSON/HTML/plots/report)
  - Troubleshooting (типові проблеми)
  - FAQ (IRI_psd=0 why, anomalies=0 why, etc.)

### 🔄 Міграція (NEW)

- **[09 — Migration Notes](09_migration_notes.md)** *(STAGE 4)*
  - Legacy → new pipeline cleanup (January 2026)
  - What changed: removed `modules/`, updated `main.py`
  - Before vs After: CLI commands, outputs, metrics mapping
  - How to reproduce STAGE 1–2 without legacy
  - Legacy access: `archive/legacy_snapshot/`

---

## Існуюча документація (legacy, збережено)

- [BUGFIXES.md](BUGFIXES.md) - Історія виправлень
- [CHANGES_SUMMARY.md](CHANGES_SUMMARY.md) - Зміни в коді
- [IMPROVEMENTS_DOCUMENTATION.md](IMPROVEMENTS_DOCUMENTATION.md) - Покращення
- [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) - Огляд проєкту
- [QUICK_START.md](QUICK_START.md) - Швидкий старт (legacy версія)
- [RESEARCH_RESULTS.md](RESEARCH_RESULTS.md) - Результати досліджень
- [TECHNICAL_PARAMETERS.md](TECHNICAL_PARAMETERS.md) - Технічні параметри

---

## Ключові артефакти STAGE 2 (paper-ready)

### Таблиці
- [table_metrics_overall.csv](../out/comparison/analysis/tables/table_metrics_overall.csv)
- [table_metrics_per_100m.csv](../out/comparison/analysis/tables/table_metrics_per_100m.csv) (153 рядки)
- [table_top10_worst_segments.csv](../out/comparison/analysis/tables/table_top10_worst_segments.csv)
- [table_rank_correlation.csv](../out/comparison/analysis/tables/table_rank_correlation.csv)

### Графіки
- [plot_speed_profile.png](../out/comparison/analysis/plots/plot_speed_profile.png)
- [plot_grms_vs_rmsa.png](../out/comparison/analysis/plots/plot_grms_vs_rmsa.png) (ρ = 0.942)
- [plot_iri_multi_vs_legacy_proxy.png](../out/comparison/analysis/plots/plot_iri_multi_vs_legacy_proxy.png) (ρ = 0.783)
- [plot_top10_segments_bar.png](../out/comparison/analysis/plots/plot_top10_segments_bar.png)

### GeoJSON
- [new_roughness_100m.geojson](../out/comparison/analysis/geojson/new_roughness_100m.geojson) (153 LineStrings)
- [legacy_proxy_roughness_100m.geojson](../out/comparison/analysis/geojson/legacy_proxy_roughness_100m.geojson) (152 Points)

### Звіти
- [comparison_summary.md](../out/comparison/analysis/comparison_summary.md) (3100+ слів, 14 розділів)
- [STAGE2_COMPLETION.md](../out/comparison/STAGE2_COMPLETION.md) (детальний звіт STAGE 2)

---

## Як цитувати цей проєкт у науковій роботі

**Формат (без DOI):**

```
@software{road_quality_analyzer_2025,
  title={Road Quality Analyzer: Smartphone-based IRI estimation with orientation correction},
  author={RoadSensorRecorder Analysis Project},
  year={2025},
  version={STAGE 3},
  url={https://github.com/ZarAO/RoadSensorRecorder_Analysis},
  commit={main branch, 2025-01-10},
  note={Python 3.13.5, 22 unit tests, Spearman ρ=0.783 validation}
}
```

**У тексті статті вказати:**
- Repository: `ZarAO/RoadSensorRecorder_Analysis`
- Version/commit: main branch, дата 2025-01-10
- Python: 3.13.5
- Key libraries: pandas 2.3.2, numpy 2.3.2, scipy 1.16.1, matplotlib 3.10.6
- Test coverage: 22/22 PASS
- Validation: Spearman ρ = 0.783 (IRI_multi vs legacy RMSA, p < 0.0001)

**Ключові покращення для цитування:**
- Orientation correction (gravity alignment + GPS heading)
- Distance-based 100m segmentation
- ISO 2631-1 compliant metrics (Grms, PSD)
- Multi-method IRI estimation (Eq.3 PSD-based, Eq.4-6 vehicle-specific)
- Deterministic pipeline (фіксований seed, unit tests)

---

## Контакти та підтримка

**Документація оновлена:** 2025-01-10 (STAGE 3)

**Для питань:**
- Методологія: див. [02_methods_new_pipeline.md](02_methods_new_pipeline.md)
- Формули: `agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md`
- Тести: `tests/` (22 unit tests)
- Результати: [05_results_legacy_vs_new.md](05_results_legacy_vs_new.md)

**Репозиторій:** https://github.com/ZarAO/RoadSensorRecorder_Analysis

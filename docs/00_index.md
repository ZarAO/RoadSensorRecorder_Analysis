# Документація проєкту Road Quality Analyzer

**Версія:** STAGE 3 (2025-01-10)  
**Призначення:** Повна науково-технічна документація для публікацій та відтворення експериментів

---

## Швидкий старт

### Аналіз даних
```bash
python -m road_quality_analyzer analyze \
  --input storage/data/sensor_data_20250729_163334.csv \
  --out out/new_analysis
```

CLI має два обов'язкові параметри — `--input` і `--out` — та один
необов'язковий: `--low-speed-policy {very-poor|poor|invalid|ignore}`
(за замовчуванням `invalid`), який керує сегментами, пройденими повільніше за
20 км/год (див. [08](08_user_guide_and_cli_reference.md)).

**Веб-адмінка:** `web_admin/` (FastAPI + Angular 22) — керування файлами,
ранами, глобальна мапа, дашборд; див. розділ у `08_user_guide_and_cli_reference.md`.

**Результати:** `out/new_analysis/` — `road_segments.csv`, `recording_meta.json`,
`roughness.geojson`, `events.geojson`, `segments_map.html`, `report.md`, `plots/`.

> **Порівняння legacy vs new** виконувалось скриптом `tools/compare_runs_v2.py` на
> етапі STAGE 2. Ні скрипт, ні каталог `out/comparison/` більше не входять до
> репозиторію (видалені разом із legacy-кодом, див. [09](09_migration_notes.md)),
> тому числа з розділу [05](05_results_legacy_vs_new.md) з цього дерева не
> переобчислюються. Стабільні копії тих таблиць і графіків збережені у
> [docs/paper_assets/](paper_assets/README.md).

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
  - Формули із зовнішнього довідника `02_FORMULAS_TEST_MAP_UNIFIED.md`
    (коефіцієнти в коді — `analyzer/src/road_quality_analyzer/metrics/iri.py`):
    - Eq.1: Quarter-car IRI (опціонально)
    - Eq.2-3: IRI з PSD (основний метод)
    - Eq.4-6: Мультиваріантна регресія IRI (vehicle-specific)
  - Sampling compliance: dx ≤ 0.3m, fs 80–120Hz
  - Threshold anomaly: |a_vertical| > 10 m/s²
  - Детермінізм та тестування (163 unit tests, 11 файлів)

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
  - Фіксація версій (commit hash, OS, версія Python)
  - Як повторити на іншому CSV
  - Де знайти артефакти STAGE 2

### 📊 Результати

- **[05 — Результати порівняння legacy vs new](05_results_legacy_vs_new.md)**
  *(числа з прогону STAGE 2; копії таблиць і графіків — у `docs/paper_assets/`)*
  - **Таблиця 1:** Overall metrics (`table_metrics_overall.csv`)
  - **Таблиця 2:** Rank correlations (`table_rank_correlation.csv`)
  - **Рис. 1:** IRI_multi vs Legacy RMSA scatter (ρ = 0.783, p < 0.0001)
  - **Рис. 2:** Grms vs Legacy RMSA scatter (ρ = 0.942)
  - **Рис. 3:** Speed profile (контекст для dx compliance)
  - **Рис. 4:** Top 10 worst segments bar chart
  - 100m-aligned comparison (152 overlap segments)
  - Інтерпретація Spearman correlation

### ⚠ Обмеження

- **[06 — Загрози валідності та обмеження](06_threats_to_validity_and_limitations.md)**
  - Phone mount variability (tilt, vibration)
  - Sampling fs та dx compliance
  - Speed variability / stop-and-go
  - GPS noise and distance errors
  - Orientation estimation assumptions (gravity LPF)
  - Eq.3 calibration mismatch (A, B coefficients)
  - Eq.4-6 simulated vehicle limitations
  - Парадокс низької швидкості: найгірші ділянки дають найменш валідний вимір
    (`--low-speed-policy`, `needs_class12_survey`, `events_per_km`)
  - Що вже пом'якшено, що залишається

### 🚀 Майбутнє

- **[07 — Roadmap майбутніх покращень](07_future_work_roadmap.md)**
  - **P0:** Calibration A,B для PSD model (ground truth per segment)
  - **P0:** RF anomaly classifier (a_vertical, a_perp, speed features)
  - **P1:** Sensor fusion з gyro (стабільність у поворотах)
  - **P1:** Multi-device comparison та normalization
  - **P1:** Automatic quality filters (low GPS coverage, invalid heading)
  - **P2:** Quarter-car mode (якщо є road profile)
  - **P2:** External validation campaign (repeat runs, inter-operator)

### 📖 Посібник користувача

- **[08 — User guide та CLI reference](08_user_guide_and_cli_reference.md)**
  - Install/venv setup
  - `analyze` command (`--input`, `--out`, `--low-speed-policy` — інших параметрів немає)
  - `main.py` wrapper (auto-detect останнього CSV, автогенерація теки)
  - Outputs опис (CSV/GeoJSON/HTML/plots/report)
  - Troubleshooting (типові проблеми)
  - FAQ (IRI_psd=0 why, anomalies=0 why, etc.)

### 🎯 Валідація (NEW)

- **[10 — Валідація проти профілометра](10_profilometer_validation.md)** *(2026-08-20)*
  - Смартфон vs сертифікований профілометр: М-03 і Т1016, 274 пари 100 м
  - Т1016: Spearman ρ = 0.94 (iri_multi); М-03: межа чутливості у 1.1–1.8 м/км
  - Ендогенність швидкості, чесний негативний результат калібрування Eq.3 (P0.1)
  - Корекція зсуву Eq.6 (−1.55 м/км), LORO; старий застосунок — деградація GPS

### 🔄 Міграція (NEW)

- **[09 — Migration Notes](09_migration_notes.md)** *(STAGE 4)*
  - Legacy → new pipeline cleanup (January 2026)
  - What changed: removed `modules/`, updated `main.py`
  - Before vs After: CLI commands, outputs, metrics mapping
  - How to reproduce STAGE 1–2 without legacy
  - Legacy access: лише через історію git (каталог `archive/legacy_snapshot/`
    у робочому дереві відсутній)

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

## Ключові артефакти STAGE 2 (історична довідка)

> Каталог `out/comparison/` було видалено разом із legacy-кодом і скриптом
> `tools/compare_runs_v2.py`. Перелік нижче описує, які файли створював той прогін.
> Стабільні копії 4 таблиць і 4 графіків збережені у
> [docs/paper_assets/](paper_assets/README.md); решти файлів у дереві немає.

### Таблиці
- `tables/table_metrics_overall.csv`
- `tables/table_metrics_per_100m.csv` (153 рядки)
- `tables/table_top10_worst_segments.csv`
- `tables/table_rank_correlation.csv`

### Графіки
- `plots/plot_speed_profile.png`
- `plots/plot_grms_vs_rmsa.png` (ρ = 0.942)
- `plots/plot_iri_multi_vs_legacy_proxy.png` (ρ = 0.783)
- `plots/plot_top10_segments_bar.png`

### GeoJSON
- `geojson/new_roughness_100m.geojson` (153 LineStrings)
- `geojson/legacy_proxy_roughness_100m.geojson` (152 Points)

### Звіти
- `comparison_summary.md` (14 розділів)
- `STAGE2_COMPLETION.md` (детальний звіт STAGE 2)

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
  note={Python 3.11+, 163 unit tests, Spearman ρ=0.783 validation (STAGE 2)}
}
```

**У тексті статті вказати:**
- Repository: `ZarAO/RoadSensorRecorder_Analysis`
- Version/commit: main branch, дата 2025-01-10
- Python: >= 3.11 (перевірено на 3.14.4)
- Key libraries: версії з `pip freeze` вашого середовища
- Test coverage: 163/163 PASS (`pytest analyzer/tests -q`, 11 файлів)
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
- Формули: посилання `agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md` у документації
  вказує на зовнішній довідник із рівняннями (у репозиторії його немає). Фактичні
  коефіцієнти, які виконуються, — у `analyzer/src/road_quality_analyzer/metrics/iri.py`
- Тести: `analyzer/tests/` (163 unit tests у 11 файлах)
- Результати: [05_results_legacy_vs_new.md](05_results_legacy_vs_new.md)

**Репозиторій:** https://github.com/ZarAO/RoadSensorRecorder_Analysis

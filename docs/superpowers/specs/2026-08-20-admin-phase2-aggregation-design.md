# Web Admin Phase 2 — Reference View, Multi-Pass Aggregation, Run Comparison, Dashboard Breakdown, Dissertation Pipeline

**Дата:** 2026-08-20
**Статус:** скоуп затверджений користувачем усно («включаємо все, що нам допоможе, погнали»); деталізація — цей документ
**Гілка:** `v1-1-stage`
**Передумови:** Phase 3 (спека 2026-08-20-admin-calibration-design.md) — еталони, порівняння, набори коефіцієнтів уже працюють; користувач створив і підтвердив перший набір `eq6_bias_van_2026-08-20` (bias −1.611).

## 0. Мета фази (словами користувача)

«Вилизати всі вимірювання до ідеалу» = наблизити показники смартфона до еталонних,
наскільки це фізично можливо. Ключовий механізм — **мультипроїзні агреговані
порівняння**: кілька проїздів тієї самої ділянки усереднюються, що дає
повторюваність, зсув із довірчим інтервалом і чесний швидкісний член
(демінований fixed-effects оцінювач). Паралельно — безперервне наповнення
дисертаційних матеріалів (цільовий обсяг 120–200 сторінок docx; сирого
матеріалу — більше).

## 1. Сторінка еталона (перегляд даних профілометра)

Як сторінка рану, але для ReferenceDataset:

- **Backend:** `GET /api/references/{id}/intervals` — рядки intervals-CSV як JSON
  (NaN→null) з доданим `iri_ref` = mean(ch1..ch8); `GET /api/references/{id}/geojson`
  — FeatureCollection: LineString на інтервал з props `{interval_id, chainage_m, iri_ref}`
  (будується з lat/lon_start/end; кешується у data-dir еталона як `intervals.geojson`).
- **Frontend:** route `calibration/references/:id`. Секції: метадані (дорога, напрям,
  смуга, категорія, крок, span, ручна дата), мапа інтервалів через **той самий
  SegmentMap** (новий input `metricKey` — за замовчуванням `iri_multi`, тут `iri_ref`;
  палітра/пороги ті самі — IRI є IRI), профіль IRI за пікетажем (новий generic
  `MultiLineChart`), повні тексти попереджень парсера, таблиця інтервалів
  (віртуалізація не потрібна — max ~1700 рядків, пагінація по 200).
- Лінк «Відкрити» з рядка еталона на вкладці Калібрування.

## 2. Мультипроїзне агреговане порівняння (науковий центр фази)

**Сутність `AggregateComparison`:** `id, reference_id FK, run_ids JSON (список,
≥2), created_at, status (queued|running|done|failed), params JSON, result_dir,
summary JSON, error`. Видалення — з result_dir; при видаленні рану — агрегат,
що містить цей ран, позначається failed з поясненням (або видаляється) — рішення:
**залишається, у summary прапорець `stale=true`** (історія зберігається).

**Математика (нові чисті функції в study-пакеті, `profilometer_validation/aggregate.py`,
з тестами — це матеріал дисертації):**

1. Для кожного рану окремо — наявний матчинг `windowed_reference` (ті самі
   дефолти) → пари (chainage_m, iri_multi, iri_ref, mean_speed_kmh, seg_id, run_id).
2. **Бінінг по пікетажу еталона:** bin = floor(chainage_m/100)·100 + 50.
   У кожному біні: значення кожного проїзду, iri_ref = середнє по парах біна.
3. **Повторюваність:** pooled within-bin std проїздів
   σ_r = sqrt(mean_b(var_b(iri_multi))) (біни з ≥2 проїздами).
4. **Агрегований профіль:** mean_b(iri_multi) ± band (min–max по проїздах).
5. **Зсув із ДІ:** diff_b = mean_b(iri_multi) − iri_ref_b; bias = mean_b(diff_b);
   CI 95% — t-інтервал з ефективним n за lag-1 автокореляцією diff_b
   (наявний `effective_n`).
6. **Швидкісний член без ендогенності (якщо швидкості проїздів різняться):**
   демінований оцінювач: (diff_ib − mean_b diff) ~ (speed_ib − mean_b speed),
   OLS без вільного члена → slope, stderr, n. Активується, коли std середніх
   швидкостей проїздів > 3 км/год; інакше у summary `speed_effect: null` з
   поясненням.
7. Валідаційні метрики агрегованого профілю: Spearman ρ, MAE, RMSE
   (наявний `validation_stats` по бінах).

**Артефакти** (`storage/results/aggregates/agg<id>_<stamp>/`): `per_bin.csv`,
`per_pass_pairs.csv`, `aggregate_stats.json`, `chart_data.json`, `figures/`
(профіль з бандом vs еталон; повторюваність; діаграма diff~speed якщо є) —
matplotlib через study-пакет.

**API:** `POST /api/aggregate-comparisons {reference_id, run_ids[], params?}`
(гарди: усі рани done, ≥2, еталон 10 м не видалений; bbox перетин як у Phase 3),
`GET ''`, `GET /{id}`, `DELETE /{id}`, `GET /{id}/artifacts/{name}`.

**UI:** секція «Мультипроїзні порівняння» на вкладці Калібрування (створення:
еталон + мультивибір done-ранів; список зі статусами). Сторінка
`calibration/aggregates/:id`: KPI (проїздів, бінів, bias ± CI, σ_r повторюваність,
MAE агрегованого, ρ), профіль з бандом (MultiLineChart + band), блок швидкісного
ефекту, таблиця бінів (chainage, iri_ref, mean, std, n_passes, diff), кнопка
**«Створити набір коефіцієнтів»** — draft eq6_bias з params {bias}, stats_snapshot
розширюється: `{bias_ci_low, bias_ci_high, n_passes, n_bins, repeatability_sd,
rho, mae_aggregated}` + `aggregate_comparison_id` як провенанс (нова nullable FK
у CoefficientSet поруч із comparison_id; заповнюється одна з двох).

## 3. Порівняння двох ранів одного файлу (з оригінальної спеки Фази 2)

- `GET /api/files/{file_id}/compare?run_a=&run_b=` — обидва рани цього файлу,
  done; сегменти вирівняні по seg_id (той самий CSV → та сама сітка):
  `[{seg_id, s_start, iri_multi_a, iri_multi_b, delta_iri_multi, iri_psd_a,
  iri_psd_b, grms_a, grms_b, mean_speed_a, mean_speed_b}]` + summary
  `{segments, mean_delta_iri_multi, max_abs_delta, params_a, params_b}`
  (NaN→null; низькошвидкісний інваріант зберігається).
- UI: на сторінці рану кнопка «Порівняти з іншим раном» (селект done-ранів того
  ж файлу) → сторінка/діалог з таблицею дельт і підсумком. Головний юзкейс —
  показати ефект наборів коефіцієнтів (до/після реаналізу).

## 4. Дашборд: розбивка за vehicle_type

- `GET /api/dashboard` розширюється: `by_vehicle_type: {<type|null>: {files_total,
  runs_done, km_total, mean_iri_multi, low_speed_total}}`.
- UI: рядок чіпів типів авто над наявними картками; вибір чіпа фільтрує KPI й
  гістограму (бекенд повертає і глобальні, і по-типові гістограми; «всі» —
  за замовчуванням). З одним типом виглядає природно.

## 5. Калібрувальний UX-фікс (виявлено у проді, критично)

Користувач створив набір з phone_model=`zarichnyi-samsung-s26u`, а преамбула
пише `samsung SM-S948B` → набір **ніколи не резолвиться** (точний tier не
збігається, vehicle-tier вимагає NULL). Виправлення:

1. Діалог створення набору: phone_model **префілиться точним device-рядком**
   рану (з recording_meta.preamble.device, до коми) як select із двох опцій:
   «точний телефон (<device>)» / «будь-який телефон цього типу авто (NULL)».
   Вільний текст прибирається.
2. Confirm-діалог показує **резолюційний прев'ю**: «застосується до N файлів»
   (той самий підрахунок кандидатів, phone-aware); N=0 → червоне попередження
   «жоден наявний файл не збігається — перевірте телефон/тип авто».
3. Backend: `POST /api/coefficient-sets/preview-resolution {model, vehicle_type,
   phone_model}` → `{files_matched, filenames[]}` (для діалогу).
4. Міграція даних користувача: створити коректний draft
   (`eq6_bias_van_SM-S948B`, bias з comparison 2, phone_model=`samsung SM-S948B`)
   — підтвердження лишається за користувачем (spec Phase 3 §4: рішення ручне).

## 6. Дисертаційний конвеєр (постійний напрям)

- `Dissertation/chapters/` — робочі .md файли українською (склейка в docx —
  пізніше через office-export):
  `00_structure.md` (зміст, цільові обсяги по розділах, статус наповнення),
  `01_analysis.md` (предметна область, огляд методів, книга ADB, постановка задачі),
  `02_methods.md` (математичні моделі: PSD/Eq.3, Grms/Eq.4-6, сегментація 100 м,
  low-speed політика, контракт CSV v2.1/v3, калібрувальна методологія:
  bias-корекція, демінований швидкісний оцінювач, повторюваність),
  `03_system.md` (програмно-апаратний комплекс: Android-застосунок (стадії A/B),
  аналізатор, веб-адмінка фази 1–3, архітектурні рішення),
  `04_experiments.md` (валідація vs профілометр — з docs/10 і docx; калібрування;
  польовий протокол мультипроїздів; майбутні результати агрегації),
  `05_conclusions.md`, `06_appendices.md` (контракти, API, структури даних).
- Наповнення ЗАРАЗ з наявних матеріалів (docs/01–10, paper_draft_uk.md,
  валідаційний docx, README-и) — розгорнутий зв'язний текст, не тези.
  Цільовий обсяг цієї ітерації: ≥ 60% фінального (сирий матеріал має
  перевищувати фінальні 120–200 стор.).
- Правило `.claude/rules/dissertation-pipeline.md`: після кожного наукового
  результату — дописати відповідний розділ у тій же сесії; українська; без
  вигаданих цитат/чисел; без прихованих символів; жодних згенерованих маркерів.

## 7. Межі фази

- Без auth, без Postgres, без змін мобільного застосунку.
- Повний рефіт Eq.3 — тільки після 4–5 доріг (поза фазою).
- Автопідтвердження наборів — ні (незмінно).
- Редагування наборів — ні (draft→archive→новий draft).

## 8. Тестування

Study: юніти на aggregate.py (бінінг, σ_r, bias CI з effective n, демінований
slope на синтетиці з відомим ефектом). Backend: aggregate job на синтетичних
2-3 «проїздах» (зсунуті копії синтетичної дороги), guards, preview-resolution,
run-vs-run compare (align/NaN/policy-різниця), dashboard breakdown. Frontend:
специ на нові сторінки/чарти/діалоги (фікстури). Регресія: всі наявні сюїти.

## 9. Порядок реалізації (високорівнево)

1. aggregate.py у study-пакеті (математика + тести). 2. БД+API агрегатів + job.
3. Reference intervals/geojson API + SegmentMap metricKey. 4. Сторінка еталона.
5. Сторінка агрегата + створення набору з нього. 6. UX-фікс калібрування
(префіл, preview-resolution, draft-міграція). 7. Run-vs-run compare (backend+UI).
8. Dashboard breakdown. 9. Дисертаційні розділи 00–06 + правило. 10. Докі,
правила, регресія.

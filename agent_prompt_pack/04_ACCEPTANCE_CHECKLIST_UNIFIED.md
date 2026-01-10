# 04 — ACCEPTANCE CHECKLIST (UNIFIED)

Агент вважається таким, що виконав задачу, якщо **всі** пункти нижче виконані.

---

## A) Функціональні критерії
- [ ] Є новий запуск: `python -m road_quality_analyzer analyze ...`
- [ ] Є **orientation-корекція**:
  - [ ] `a_vertical` в world координатах (gravity aligned)
  - [ ] `a_perp` перпендикулярно напрямку руху (GPS heading)
- [ ] Є 100 м сегментація (не по рядках)
- [ ] Для кожного сегмента є IRI (m/km):
  - [ ] `IRI_psd` (Eq.3) на базі Welch PSD band-power
  - [ ] `IRI_multi` (Eq.4/5/6) з vehicle_type = LEV/DSD/GENERIC
- [ ] Є anomaly baseline з книги: `a_vertical > 10 m/s²`
- [ ] Є sampling compliance report (dx≤0.3 м, fs 80–120 Hz рекомендації)
- [ ] Є deterministic outputs: CSV + GeoJSON + HTML map + plots + report.md
- [ ] Legacy `python main.py` все ще працює

---

## B) Тестування (мінімум)
- [ ] `test_distance_haversine_or_enu.py` — відстань між двома точками ~еталон
- [ ] `test_orientation_gravity_alignment.py` — відновлення вертикалі після випадкового roll/pitch
- [ ] `test_psd_scalar_deterministic.py` — синус/сигнал дає очікуваний band power (в межі похибки)
- [ ] `test_segmentation_100m.py` — семпли правильно потрапляють в сегменти

---

## C) Репорт
`out/.../report.md` має містити:
- [ ] які режими включені (psd/multi/threshold)
- [ ] значення конфігів (segment_length, bandpass, PSD params, vehicle params)
- [ ] sampling compliance: fs, dx-статистика
- [ ] топ-10 сегментів за IRI (найгірші)
- [ ] окремий розділ “Assumptions & limitations”:
  - [ ] quarter-car IRI потребує профілю (як у книзі)
  - [ ] wheel size не входить у формули книги (лише метадані)

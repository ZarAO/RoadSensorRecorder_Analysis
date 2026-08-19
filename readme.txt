Road Quality Analyzer
=====================

PURPOSE
-------
Аналіз якості дорожнього покриття на основі даних з сенсорів смартфона.
Розраховує IRI (International Roughness Index) та візуалізує результати.

HOW TO RUN
----------
1. Встановити залежності (analyzer ставиться в editable-режимі з ./analyzer):
   pip install -r requirements.txt
   (еквівалент напряму: pip install -e ./analyzer)

2. Запустити аналіз:
   python -m road_quality_analyzer analyze --input storage/data/sensor_data_20250729_163334.csv --out storage/results/my_analysis

   Або через wrapper:
   python main.py --input storage/data/sensor_data_20250729_163334.csv --out storage/results/my_analysis

INPUT FORMAT
------------
CSV контракту v2: необов'язкова преамбула з рядків '#', далі рівно 7 колонок
Time,Type,X,Y,Z,Latitude,Longitude. Type - одне з Accelerometer | Gyroscope |
Location. Рядки сенсорів мають порожні Latitude/Longitude, рядки Location -
порожні X,Y,Z. Time - epoch-ms на монотонному годиннику (див. README.md).

OUTPUTS
-------
Результати зберігаються у вказаній директорії (--out):
- road_segments.csv - метрики по 100м сегментах (IRI, Grms, speed)
- segments_map.html - інтерактивна карта (відкрити у браузері)
- roughness.geojson - сегменти з геометрією та метриками
- events.geojson - аномалії як точки
- plots/ - діагностичні графіки (PNG + PDF)
- report.md - технічний звіт

TESTS
-----
.venv\Scripts\python.exe -m pytest analyzer/tests -q   (114 passed)

DOCUMENTATION
-------------
Детальна документація: docs/08_user_guide_and_cli_reference.md
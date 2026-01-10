Road Quality Analyzer
=====================

PURPOSE
-------
Аналіз якості дорожнього покриття на основі даних з сенсорів смартфона.
Розраховує IRI (International Roughness Index) та візуалізує результати.

HOW TO RUN
----------
1. Встановити залежності:
   pip install -r requirements.txt

2. Запустити аналіз:
   python -m road_quality_analyzer analyze --input data/sensor_data_20250729_163334.csv --out results/my_analysis

   Або через wrapper:
   python main.py --input data/sensor_data_20250729_163334.csv --out results/my_analysis

OUTPUTS
-------
Результати зберігаються у вказаній директорії (--out):
- road_segments.csv - метрики по 100м сегментах (IRI, Grms, speed)
- segments_map.html - інтерактивна карта (відкрити у браузері)
- roughness.geojson - сегменти з геометрією
- plots/ - діагностичні графіки (PNG)
- report.md - технічний звіт

DOCUMENTATION
-------------
Детальна документація: docs/08_user_guide_and_cli_reference.md
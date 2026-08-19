# Веб-адмінка Road Quality Analyzer — дизайн-спека

**Дата:** 2026-08-19
**Статус:** затверджено користувачем (дизайн-діалог), реалізація відкладена — чекає команди "старт"
**Гілка:** `v1-1-stage`

## 1. Мета

Локальна веб-адмінка для керування повним циклом аналізу якості доріг: завантаження CSV-записів
з Android-додатка, запуск аналізу, перегляд результатів (графіки, звіт, мапи) та глобальна мапа
всіх проаналізованих зон. Локальний запуск зараз; архітектура не блокує майбутній публічний хостинг.

## 2. Стек (затверджено)

- **Backend:** Python, FastAPI + SQLAlchemy, SQLite (`admin.db`); аналайзер імпортується
  як бібліотека (editable install пакета `road_quality_analyzer`) — виклик `analyze()` у процесі,
  без subprocess.
- **Frontend:** Angular 22, standalone components. Юніт-тести (`.spec.ts`) — поруч із
  компонентами за конвенцією Angular CLI; e2e (Playwright) — окремо, за потреби, пізніше.
- **БД:** тільки метадані (файли, рани, статуси, зведені метрики). Артефакти — на файловій
  системі у `storage/results/`. Міграція на Postgres при хостингу = зміна connection string.

## 3. Структура (монорепо RoadSensorRecorder_Analysis)

```
RoadSensorRecorder_Analysis/
  analyzer/                    # науковий пакет (src-layout, уже реструктуризовано)
    pyproject.toml
    src/road_quality_analyzer/
    tests/
  web_admin/
    backend/
      src/                     # FastAPI-застосунок
        api/                   # роутери: files, runs, global_map, dashboard
        core/                  # config (шляхи storage/, БД), job queue
        db/                    # моделі + session
        services/              # analysis_service, global_map_service, dashboard_service
      tests/                   # pytest: API + сервіси зі стабом аналайзера
      admin.db                 # SQLite (у .gitignore)
    frontend/                  # Angular 22 (згенеровано CLI)
  storage/
    data/                      # вхідні CSV
    results/                   # артефакти ранів: <csv-stem>__run<N>_<timestamp>/
  docs/  main.py  README.md
```

## 4. Модель даних

**SourceFile**: `id`, `filename`, `size_bytes`, `uploaded_at`, `source_deleted` (bool),
метадані прев'ю: `duration_s`, `fs_hz`, `gps_coverage_ratio` (обчислюються при завантаженні
легким проходом по CSV).

**AnalysisRun**: `id`, `file_id` (FK), `created_at`, `started_at`, `finished_at`,
`status` (`queued|running|done|failed`), `params` (JSON: `low_speed_policy`, майбутні опції),
`result_dir`, `summary` (JSON: segments_total, km_total, mean_iri_multi, low_speed_count,
partial_count, events_total), `error` (текст при failed), `log_path`.

Видалення файлу НЕ видаляє його рани — файл позначається `source_deleted=true`.
Видалення рану видаляє його каталог артефактів і запис.

## 5. API (REST, `/api`)

| Метод | Шлях | Дія |
|---|---|---|
| POST | `/files` | upload CSV у `storage/data/` (валідація заголовка контракту v2 одразу) |
| GET | `/files` | список з метаданими і кількістю ранів |
| DELETE | `/files/{id}` | видалення файлу (рани лишаються) |
| POST | `/runs` | запуск аналізу: `{file_id, params}` → ран у черзі |
| POST | `/runs/run-all-unanalyzed` | рани для всіх файлів без успішного рану |
| GET | `/runs`, `/runs/{id}` | список / деталі рану |
| GET | `/runs/{id}/log` | стрім лога (SSE) |
| GET | `/runs/{id}/artifacts/{name}` | віддача артефактів (PNG/HTML/CSV/MD/GeoJSON) |
| DELETE | `/runs/{id}` | видалення рану з артефактами |
| POST | `/global-map/rebuild` | перезбирання глобальної мапи |
| GET | `/global-map` | merged GeoJSON: останній успішний ран кожного файлу |
| GET | `/dashboard` | зведення: км, розподіл IRI, топ-10 найгірших сегментів |
| GET | `/files/{id}/compare?run_a=&run_b=` | порівняння двох ранів (Фаза 2) |

**Виконання:** in-process черга (`ThreadPoolExecutor(max_workers=1)`) — один ран за раз;
статуси і лог у БД/файлі. Без Celery/Redis (YAGNI локально).

## 6. Frontend — вкладки

1. **Файли** — список, drag&drop upload з прев'ю метаданих, видалення, кнопки
   "Аналізувати" (діалог з вибором `low-speed policy`) і "Аналізувати всі нові".
2. **Результати** — список ранів зі статусами; сторінка рану: PNG-графіки, відрендерений
   `report.md`, таблиця сегментів, персональна folium-мапа (iframe), стрім лога для running.
3. **Глобальна мапа** — нативна Leaflet-мапа: merged GeoJSON з `/api/global-map`;
   кольори за шкалою IRI; сегменти `needs_class12_survey` — маджента `#FF00FF` з легендою
   "Потребує обстеження профілометром (клас 1/2)"; клік по сегменту → сторінка рану.
   Кнопка "Оновити глобальну мапу" → `POST /global-map/rebuild`.
4. **Дашборд** — всього км/файлів/ранів, гістограма IRI, топ-10 найгірших сегментів з лінками.

## 7. Тестування

- Backend: pytest — API-тести (TestClient) + сервіси зі стабом `analyze()` (без реальних
  прогонів у юніт-тестах); один інтеграційний smoke на синтетичному CSV.
- Frontend: Angular CLI unit specs поруч із компонентами.
- Аналайзер не змінюється; його 163 тести — незалежний контур.

## 8. Майбутній хостинг (не зараз, але не блокуємо)

- Аутентифікація — FastAPI middleware/Depends seam (зараз відсутня свідомо).
- SQLite → Postgres: SQLAlchemy URL з конфіга.
- Статика фронтенду: `ng build` → віддається FastAPI/reverse proxy.
- Ліміти на upload і конкурентні рани — конфіг.

## 9. Фази реалізації

- **Фаза 1:** backend (моделі, files/runs/artifacts, черга) → frontend (Файли, Результати) →
  глобальна мапа → дашборд.
- **Фаза 2:** порівняння ранів одного файлу (таблиця дельт метрик по сегментах).

## 10. Підготовка оточення (на старті реалізації)

- Перевірити Node.js для Angular CLI; згенерувати frontend через `ng new` (standalone, routing).
- Додати path-scoped рули в репо: `web-admin-backend.md` (FastAPI-конвенції),
  `web-admin-frontend.md` (Angular 22 standalone).
- Актуальні доки Angular 22/FastAPI — через Context7 MCP, не з пам'яті.

## 11. Non-goals (зафіксовано)

Без аутентифікації зараз; без Celery/Redis; без Docker до хостингу; без числового IRI для
низькошвидкісних сегментів будь-де в адмінці (інваріант аналайзера поширюється на UI).

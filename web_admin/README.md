# Web Admin

Локальна адмінка для Road Quality Analyzer: FastAPI + SQLite backend
(`web_admin/backend/`), Angular 22 frontend (`web_admin/frontend/`).
Повний опис функціоналу — `../docs/08_user_guide_and_cli_reference.md`
(розділ «Веб-адмінка» і підрозділ «Калібрування (Phase 3)»).

## Передумови

```bash
# З кореня репозиторію
pip install -e ./analyzer                        # аналізатор як бібліотека
pip install -e studies/profilometer_validation    # Phase 3: порівняння з профілометром
pip install -r web_admin/backend/requirements.txt # FastAPI, SQLAlchemy, openpyxl, ...
```

`profilometer_validation` встановлюється editable окремо — його немає у
жодному `requirements.txt` (як і `analyzer`, це свідомий вибір workspace-схеми
проєкту). Без нього backend впаде на імпорті `src/services/comparison.py`.

Frontend:

```bash
cd web_admin/frontend
npm install
```

## Змінні середовища (backend)

Усі мають робочі значення за замовчуванням (каталоги під `storage/` у корені
репозиторію) — задавати потрібно лише для нетипового розташування (тести,
інший том):

| Змінна | За замовчуванням | Призначення |
|--------|-------------------|-------------|
| `RQA_DATA_DIR` | `storage/data` | завантажені вхідні CSV |
| `RQA_RESULTS_DIR` | `storage/results` | артефакти ранів і порівнянь |
| `RQA_REFERENCE_DIR` | `storage/reference` | еталони профілометра (Phase 3) |
| `RQA_DB_URL` | `sqlite:///web_admin/backend/admin.db` | рядок підключення SQLAlchemy |
| `RQA_QUEUE_INLINE` | вимкнено | синхронне виконання черги (тести) |

## Запуск (два термінали)

```powershell
# Backend (FastAPI, http://127.0.0.1:8000)
cd web_admin/backend
..\..\.venv\Scripts\python.exe -m uvicorn src.main:app --reload

# Frontend (Angular dev server, http://localhost:4200)
cd web_admin/frontend
npx ng serve --proxy-config proxy.conf.json
```

## Тести

```bash
cd web_admin/backend && python -m pytest        # стаб аналізатора; повний цикл — -m slow
cd web_admin/frontend && npx ng test --watch=false
```

# Regulation monitor

Мониторит проекты НПА с `regulation.gov.ru`, сопоставляет их с перечнем НПА из `C:\PY\PythonProject\rag_norm\qdrant_chunks.json`, отслеживает смену **Stage/Status** и дополняет Excel-реестр.

## Быстрый старт (локально)

1) Установить зависимости:

```bash
pip install -r requirements.txt
```

2) Создать `.env` (или задать переменные окружения):

- `RAG_NORM_QDRANT_CHUNKS=C:\PY\PythonProject\rag_norm\qdrant_chunks.json`
- `STATE_DB_PATH=./data/state.sqlite3`
- `EXCEL_PATH=./data/Output.xlsx`
- `PROJECT_SOURCE=portal` — живой портал `regulation.gov.ru`
- `RUN_PROGRESS_INTERVAL=2000` — писать прогресс в лог не чаще, чем раз в N записей (минимум 50)
- `RUN_METRICS_JSON_PATH=./data/last_run_metrics.json` — снимок метрик после прогона (успех и ошибка)

3) Запуск:

```bash
python -m reg_monitor
```

Источник обращается к публичному endpoint сайта
`POST /api/public/PublicProjects/GetFiltered`, сортирует по `creationDate` по убыванию
и хранит водяной знак `portal_last_creation_date`. Следующий ручной запуск читает проекты
с этой даты и новее, дополняет `Output.xlsx`, а новые строки подсвечивает цветом, который
отличается от уже использованных цветов подсветки.

## Где смотреть данные и отладка

Справочник НПА в виде таблицы: **`debug/npa_docs_catalog.md`**. Остальное — в **`debug/README.md`** (пути к SQLite, Excel, команды пересборки).


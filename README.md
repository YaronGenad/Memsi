# Priority Interface

Internal tool for working against Priority ERP. Pulls invoices and transaction
lines from OData, keeps a local copy in PostgreSQL, generates monthly customer
billing and supplier payment reports, tracks inventory across active warehouses,
and runs demand forecasts for luggage by branch and product category.

Runs on whoever's machine needs it. No server, no web client, no extra access
beyond the company network.

## What it does

* **Data Request** - monthly billing report for all customers, with a sheet per
  customer plus a supplier payments sheet.
* **Customer Reports** - multi-month report, one Excel sheet per month.
* **Branch Reports** - monthly report broken down by branch.
* **Inventory Tracking** - real-time PARTBAL pulls from warehouses flagged
  active.
* **Inventory Analysis** - filter by brand / material / size across a date
  range.
* **Product Identification** - export unidentified items to CSV, fill in
  brand-grade / size / material, import back. Writes go straight to the DB,
  changes take effect immediately, no restart.
* **Forecasting** - 5 models (naive-prev / regime-aware / flight-rate / causal / per-cell weekly) per branch and per category,
  with context for war / military operation / holidays / summer peak. Every
  run is saved with backtest metrics (MAE / RMSE / MAPE) computed against the
  last 6 months.
* **Updates** - edit customer pricing, supplier prices, luggage classifier
  entries, and forecast events. Every change goes into the audit log.

## Architecture

```
Priority ERP (OData)
        |
        v
fetch_combined.py        pulls with month-level cache; tenacity retry
        |
        v
PostgreSQL (cache)       documents, logfile, cache_metadata
        |
        v
domain_repository.py     data access layer; in-memory cache + audit log on writes
        |
        v
gui_app.py + tabs/       PyQt6 (via qtpy); QThread workers from tabs/_base.py
```

A desktop app talking directly to a local PostgreSQL or to a shared DB on the
internal network. To run on multiple machines, point them at the same DB.

## Layers

| Layer | Files | Role |
|-------|-------|------|
| Entry | `gui_app.py` | Builds the main window, registers 8 tabs, runs DB and Priority API health checks |
| UI tabs | `tabs/` | One tab per feature. All inherit `tabs/_base.py:BaseTabWorker` |
| Shared widgets | `tabs/_widgets.py` | `MonthYearPicker`, `DateRangePicker`, `ExcelExporter` |
| ERP fetch | `fetch_combined.py` | OData with pagination, retry, year-month cache |
| Cache | `cache_manager.py` | INSERTs into `documents` and `logfile` with ON CONFLICT (the partial unique index handling on logfile lives here) |
| Domain | `domain_repository.py` | The only module that talks directly to the business tables (prices, branches, warehouses, luggage). In-memory cache with RLock + audit log |
| Forecast | `forecast_engine.py`, `forecast_weekly_cell.py`, `causal_forecast.py`, `forecast_evaluation.py`, `forecast_cache.py`, `forecast_db.py`, `forecast_tab.py` | 5 forecast models (see "Forecasting models" below) + Newsvendor; backtest on last 6 months; pickle cache keyed by hash of inputs |
| DB infra | `db_config.py` | `ThreadedConnectionPool` with lazy init + `get_conn()` context manager |
| Migrations | `migrate.py`, `migrations/` | Simple runner with a `schema_version` table. Runs `.sql` and `.py` files in alphabetic order |
| Logging | `logger.py` | TimedRotatingFileHandler at `~/.memsi/logs/memsi.log` |

## Database tables

```
documents               Priority documents (DOCUMENTS_D)
logfile                 transaction lines (LOGFILE) with a partial unique index on 6 columns
cache_metadata          which (data_type, year_month) pairs have been pulled

forecast_history        sales history fed to the models
forecast_events         events the forecast factors in
forecast_runs           saved runs (who, when, which slice)
forecast_predictions    one row per (run, model, year_month)
forecast_metrics        MAE / RMSE / MAPE per run per model

customers               customer code (Priority) -> pricing tier
pricing_tiers           ELAL / AIR_FRANCE_KLM / DELTA / QAS_LAUFER / etc.
customer_repair_prices       repair price by tier and SKU
customer_replacement_prices  replacement price by tier and luggage type
supplier_repair_prices       repair payment to supplier (not customer-dependent)
supplier_replacement_prices  replacement payment to supplier
branches                branch code -> Hebrew display name
warehouses              warehouse map, including active / inactive flags
luggage_identification  product description -> category (467 rows currently)
domain_audit_log        who changed what, when, with old and new values (insert-only)

schema_version          tracks which migrations have run
```

## Forecasting models

`forecast_engine.py` runs five models in parallel, each with event context.
Internal function names (`forecast_arima`/`forecast_prophet`/`forecast_xgboost`)
were kept for API stability but the implementations were swapped in Sprint C4
after a 12-model sandbox showed the originals were overfitting on 38 months
of data with regime shifts:

* **חודש קודם** (was ARIMA) - naive last-value with ±σ from rolling 12-month
  std. MAE=242 on per-cell backtest, the best simple baseline on this data.
* **מותאם-regime** (was Prophet) - naive_prev scaled by historical ratio of
  the target regime vs current regime. Sane response to context: HIGH→+74%,
  MEDIUM→-23%, LOW unchanged.
* **תחזית-טיסות** (was XGBoost) - `rate = qty/flights` over last 6 months,
  prediction = `rate × planned_flights[ym]` from IAA flight schedule.
* **סיבתי** (Causal) - `repairs = n_core_branches × rate[regime] × flights / 100K`.
  MAPE 14.9% on backtest.
* **פר-cell (שבועי)** (Sprint C5) - LinearRegression over week × branch ×
  category (~70K training cells with 30+ features). 22% better than naive
  on non-zero cells.
* **Newsvendor** - on the average of the first three models, returns
  `order_quantity` and `safety_stock`. Recalculated per horizon in the
  procurement tab (mean × h, std × √h).

`forecast_evaluation.backtest()` trains each model on `series[:-6]` and
evaluates on the last 6 months. MAE / RMSE / MAPE are persisted to
`forecast_metrics` and shown in the UI next to each model name.

`forecast_cache.py` pickles trained outputs keyed by a deterministic hash of
(model, series, horizon, context, events). Default TTL is one week. Repeat
runs with the same inputs return instantly.

## Setup

```
git clone https://github.com/genadyarony-code/MemsiInterface.git
cd MemsiInterface/priority_interface
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` with the actual API and DB values.

First run:

```
python migrate.py
python gui_app.py
```

`migrate.py` creates the domain tables and seeds them from the legacy code
modules (pricing dicts, branch names, warehouses, luggage identification).
Safe to re-run; it checks `schema_version` and skips what already ran.

`gui_app.py` bootstraps the older cache schema (`documents`, `logfile`,
`cache_metadata`) through `db_setup.py` on every launch. That's idempotent
and harmless if the tables already exist.

> **First-run note.** The first time `nightly_sync.py` runs after install, it
> performs an `initial_sync` of `logfile_full` — pulling the full historical
> LOGFILE for every active SKU. This takes roughly **12 minutes for ~1,400
> SKUs** and runs automatically; no flag needed. Every subsequent night only
> the `incremental_sync` (rolling last 30 days) runs, and finishes in
> seconds.

## Dependencies

```
PyQt6 + qtpy        UI
psycopg2-binary     DB
pandas, openpyxl    DataFrames + Excel
requests, tenacity  HTTP + retry
statsmodels         ARIMA
prophet             Prophet
xgboost             XGBoost
scipy               Newsvendor (norm.ppf)
matplotlib          forecast tab charts
python-bidi         RTL handling for matplotlib
python-dotenv       .env loader
```

## Adding a customer / changing a price / adding a luggage description

Everything goes through the **Updates** tab. Writes hit the DB with user
attribution, take effect immediately, and show up in the audit log panel at
the bottom.

The legacy code files (`pricing_data.py`, `branch_names.py`,
`product_identification.py`) still load as a fallback if the DB is
unreachable, but in normal operation the DB is the source of truth.

## Logs

`~/.memsi/logs/memsi.log` with daily rotation, keeping the last 30 files.

## Not in scope

* **Web app** - not needed yet. Runs internally, accessed over the local
  network only. If branch document capture becomes a need later, that will be
  a separate FastAPI + web form project pointing at the same DB.
* **ML classifier for luggage** - the vocabulary is closed and small (under
  500 variations). Deterministic rules (regex with whitespace normalization)
  are enough and easy to audit.
* **Multi-user auth** - no permission layer beyond the Windows `USERNAME`
  written into the audit log. Anyone with DB access can edit everything.
  That's fine for a small internal tool.
* **Comprehensive tests** - no test suite. Verification is done manually
  against a local copy of production data. That's the tradeoff for internal
  tooling.

## Known limitations

* **`forecast_tab.py` size** - the file is 1,788 lines with `ForecastTab`
  alone spanning 1,307. A future refactor should split it into
  `forecast_tab.py` (coordinator), `forecast_tab_builders.py` (UI
  construction), and `forecast_charts.py` (chart classes). Deferred from
  Sprint C7 (v0.16.1) to avoid risking a wide change just before
  deployment. Tracked as tech debt; touching this file should be done
  carefully until the split happens.

## Nightly sync

`nightly_sync.py` is the unattended job that keeps the local copy fresh.
It pulls the rolling last 30 days of `DOCUMENTS_D` / `LOGFILE` from Priority
(catches retroactive edits), refreshes `PARTBAL`, and downloads any new
IAA monthly flight-traffic PDFs that have been published since the last run.
Every run logs to `sync_runs` so the GUI status bar can show
"נתונים נכון ל-{timestamp}".

### Scheduling (Windows)

```powershell
# Run every night at 23:00. Replace the path with your install location.
schtasks /create /TN "MemsiNightlySync" /SC DAILY /ST 23:00 ^
    /TR "python.exe C:\path\to\priority_interface\nightly_sync.py" /F
```

> **Bundle case (TODO).** `nightly_sync.py` currently has no `__main__` entry
> point in the PyInstaller spec, so the bundled `PriorityInterface.exe` cannot
> run the nightly job. Users running from a bundle still need a Python
> interpreter + checkout for nightly sync. A future change can either add a
> second `EXE()` target (e.g. `nightly_sync.exe`) or wire a `--nightly-sync`
> flag into `gui_app.py`.

### Scheduling (Linux/macOS)

```cron
0 23 * * * cd /path/to/priority_interface && /usr/bin/python3 nightly_sync.py
```

### Flags

```
python nightly_sync.py                  # full run (rolling 30d + PARTBAL + IAA)
python nightly_sync.py --days 14        # smaller window
python nightly_sync.py --skip-iaa       # skip IAA PDF fetch
python nightly_sync.py --triggered-by manual   # label this run in sync_runs
```

Logs land in `~/.memsi/logs/nightly_YYYY-MM-DD.log`. The IAA PDF cache lives
in `.iaa_pdfs/` (gitignored — re-downloads as needed).

## Maintenance

* Logs filling up: `~/.memsi/logs/` is capped at 30 daily files.
* DB growing: `cache_metadata` is the index of what's already cached. Old
  months can be removed via `clear_month_data` (not exposed in the UI).
* Forecasts looking off after an `forecast_engine.py` change: bump
  `MODEL_VERSION` in `forecast_engine.py` — that invalidates the disk cache
  automatically. (You can also delete `forecast_models_cache/` manually.)
* New migration: drop a file into `migrations/` with a higher numeric prefix,
  run `python migrate.py`. `schema_version` ensures it doesn't run twice.
* Stale sync runs: `SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT 30`
  shows recent runs and their `records_pulled`/`errors_count`.

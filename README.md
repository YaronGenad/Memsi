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
* **Forecasting** - ARIMA / Prophet / XGBoost per branch and per category,
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
| Forecast | `forecast_engine.py`, `forecast_evaluation.py`, `forecast_cache.py`, `forecast_db.py`, `forecast_tab.py` | ARIMA / Prophet / XGBoost + Newsvendor; backtest on last 6 months; pickle cache keyed by hash of inputs |
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

`forecast_engine.py` runs three models in parallel, each with event context:

* **ARIMA** - SARIMAX(1,1,1)x(1,1,1,12), captures yearly seasonality. Falls
  back to MA(6) if it fails to converge.
* **Prophet** - with regressors for war / operation / ceasefire / holiday /
  summer peak / routine / November.
* **XGBoost** - lag features (1, 2, 3, 12) + rolling means + sin/cos of month
  + event flags.
* **Newsvendor** - on the average of the three models, returns
  `order_quantity` and `safety_stock`.

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

## Maintenance

* Logs filling up: `~/.memsi/logs/` is capped at 30 daily files.
* DB growing: `cache_metadata` is the index of what's already cached. Old
  months can be removed via `clear_month_data` (not exposed in the UI).
* Forecasts looking off after an `forecast_engine.py` change: delete
  `forecast_models_cache/`. The old pickled outputs are tied to the previous
  logic.
* New migration: drop a file into `migrations/` with a higher numeric prefix,
  run `python migrate.py`. `schema_version` ensures it doesn't run twice.

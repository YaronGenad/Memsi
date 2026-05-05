# MemsiInterface

A production desktop application for real-time ERP data integration, inventory management, and multi-model demand forecasting across a multi-branch retail network.

Built for an operational environment with 150+ retail locations, 20+ airline service accounts, and millions of NIS in monthly transaction volume.

---

## What it does

MemsiInterface connects directly to a Priority ERP instance via OData API, caches transactional data locally in PostgreSQL, and surfaces it through a tabbed GUI with reporting, inventory tracking, and demand forecasting capabilities.

The system runs as a standalone Windows desktop application — no web server, no cloud dependency, no manual data exports.

---

## Architecture

```
Priority ERP (OData API)
        │
        ▼
 fetch_combined.py          ← API client with caching layer
        │
        ▼
 PostgreSQL (local cache)   ← documents, transactions, forecast history
        │
   ┌────┴────────────────────────────┐
   ▼                                 ▼
cache_manager.py             forecast_engine.py
(document & transaction      (ARIMA / Prophet / XGBoost
 cache with month-level       with event-aware modeling)
 invalidation)
        │
        ▼
   gui_app.py + tabs/        ← Tkinter-based tabbed GUI
```

---

## Key design decisions

**PostgreSQL over SQLite** — Multi-user access, concurrent reads from reporting and forecasting processes, and the need for composite unique indexes ruled out SQLite early. The schema uses `CREATE TABLE IF NOT EXISTS` throughout — safe to re-run on every startup without a migration guard.

**Local cache layer** — Priority API calls are expensive and rate-sensitive. `cache_manager.py` tracks which year-month ranges are already cached per data type, so repeat queries hit local storage. Cache invalidation is explicit and month-granular.

**Multi-model forecasting with event injection** — `forecast_engine.py` runs three models (ARIMA, Prophet, XGBoost) and allows event overlays (holidays, seasonal spikes, external disruptions) via a CSV-driven event registry. Models are compared per branch per product category.

**Product identification pipeline** — Free-text product descriptions from ERP are classified into structured categories via a rule-based classifier (`product_identification.py`). This was chosen over an ML classifier because the vocabulary is closed and deterministic rules are auditable by operations staff.

**Fail-fast startup validation** — On launch, the app verifies DB connectivity and ERP API reachability before rendering the UI. Status is surfaced in a persistent status bar throughout the session.

---

## Tech stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| GUI | Tkinter + ttk | Ships with Python, no additional packaging |
| Database | PostgreSQL | Concurrent access, composite indexes, production-grade |
| ERP integration | Priority OData API | Standard interface, token-based auth |
| Forecasting | ARIMA, Prophet, XGBoost | Ensemble approach; model selection per use case |
| Packaging | PyInstaller | Single-executable deployment for non-technical users |
| Logging | Python `logging` + daily rotation | 30-day rolling log retention |

---

## Modules

| File | Role |
|------|------|
| `gui_app.py` | Main window, tab layout, startup validation |
| `forecast_tab.py` | Forecasting UI — model selection, event overlay, branch view |
| `forecast_engine.py` | Core forecasting logic (ARIMA / Prophet / XGBoost) |
| `forecast_evaluation.py` | Model comparison and accuracy scoring |
| `fetch_combined.py` | Priority API client with local cache integration |
| `cache_manager.py` | PostgreSQL-backed document and transaction cache |
| `inventory_manager.py` | Real-time inventory queries (PARTBAL) |
| `product_identification.py` | Rule-based product category classifier |
| `domain_repository.py` | Data access layer — all DB queries in one place |
| `db_setup.py` | Schema bootstrap — idempotent, runs on every startup |
| `pricing_data.py` | Pricing rules and customer-to-pricelist mappings |
| `logger.py` | Daily rotating logs to `~/.memsi/logs/` |

---

## Database schema

| Table | Contents |
|-------|----------|
| `documents` | ERP transaction documents — unique key: `docno` |
| `logfile` | Transaction lines — composite unique index on 6 fields |
| `cache_metadata` | Cache coverage tracking — key: `(data_type, year_month)` |
| `forecast_history` | Historical sales for forecasting — key: `(branch, product_type, year_month)` |
| `forecast_events` | Event registry for model injection — key: `year_month` |

---

## Application tabs

1. **Data Request** — Monthly billing report generation across all accounts
2. **Customer Reports** — Multi-month aggregated view per customer
3. **Branch Reports** — Branch-level breakdown and comparison
4. **Inventory Tracking** — Real-time stock queries from ERP
5. **Inventory Analysis** — Filtering by brand, material, and size dimensions
6. **Product Identification** — CSV-based handling of unclassified products
7. **Forecasting** — ARIMA / Prophet / XGBoost with event injection and branch snapshot
8. **Updates** — Price list and product catalog maintenance

---

## Setup

### Requirements

- Python 3.11 / 3.12
- Windows 10 / Windows 11
- PostgreSQL (local or shared server)
- Network access to the Priority ERP instance

### Installation

```bash
git clone https://github.com/genadyarony-code/MemsiInterface.git
cd MemsiInterface
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

```bash
copy .env.example .env
```

Edit `.env` with your environment values — see `.env.example` for required fields. Never commit `.env` to version control.

### Run

```bash
python gui_app.py
```

The application initializes the database schema and validates connectivity on first launch.

---

## What's not here

| Feature | Why not | Path forward |
|---------|---------|--------------|
| Web interface | Desktop deployment requirement | FastAPI + React frontend |
| ML-based classifier | Closed vocabulary, deterministic rules preferred | Worth revisiting if product catalog grows significantly |
| Automated retraining | Out of scope for v1 | Scheduled job with model versioning |
| Multi-user auth | Single-operator use case | Role-based access if deployed as a service |

---

## Author

**Yaron Genad** — [LinkedIn](https://linkedin.com/in/yaron-genad) · [Medium](https://medium.com/@yaron.genad)

# -*- coding: utf-8 -*-
import psycopg2
import pandas as pd
import os
from db_config import DB_CONFIG

EVENTS_CSV = os.path.join(os.path.dirname(__file__), 'forecast_events.csv')

CREATE_FORECAST_HISTORY = """
CREATE TABLE IF NOT EXISTS forecast_history (
    id              SERIAL PRIMARY KEY,
    branch          TEXT NOT NULL,
    luggage_type    TEXT NOT NULL,
    year_month      TEXT NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE (branch, luggage_type, year_month)
);
"""

CREATE_FORECAST_EVENTS = """
CREATE TABLE IF NOT EXISTS forecast_events (
    year_month       TEXT PRIMARY KEY,
    is_war           SMALLINT DEFAULT 0,
    is_military_op   SMALLINT DEFAULT 0,
    is_ceasefire     SMALLINT DEFAULT 0,
    jewish_holiday   SMALLINT DEFAULT 0,
    season           SMALLINT DEFAULT 0,
    is_summer_peak   SMALLINT DEFAULT 0,
    travel_impact    TEXT DEFAULT 'normal',
    notes            TEXT DEFAULT ''
);
"""


class ForecastDB:
    def __init__(self):
        self.conn = psycopg2.connect(**DB_CONFIG)

    def close(self):
        if self.conn and not self.conn.closed:
            self.conn.close()

    def setup_tables(self):
        """יצירת טבלאות אם לא קיימות + טעינת אירועים מ-CSV"""
        with self.conn.cursor() as cur:
            cur.execute(CREATE_FORECAST_HISTORY)
            cur.execute(CREATE_FORECAST_EVENTS)
        self.conn.commit()
        self._load_events_from_csv()

    def _load_events_from_csv(self):
        """טוען forecast_events.csv לטבלה — מדלג על שורות קיימות"""
        if not os.path.exists(EVENTS_CSV):
            return
        df = pd.read_csv(EVENTS_CSV)
        with self.conn.cursor() as cur:
            for _, row in df.iterrows():
                cur.execute("""
                    INSERT INTO forecast_events
                        (year_month, is_war, is_military_op, is_ceasefire,
                         jewish_holiday, season, is_summer_peak, travel_impact, notes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (year_month) DO NOTHING
                """, (
                    str(row['year_month']),
                    int(row['is_war']),
                    int(row['is_military_op']),
                    int(row['is_ceasefire']),
                    int(row['jewish_holiday']),
                    int(row['season']),
                    int(row['is_summer_peak']),
                    str(row['travel_impact']),
                    str(row['notes']),
                ))
        self.conn.commit()

    # ------------------------------------------------------------------ #
    #  forecast_history                                                    #
    # ------------------------------------------------------------------ #

    def upsert_history(self, branch: str, luggage_type: str,
                       year_month: str, quantity: int):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO forecast_history (branch, luggage_type, year_month, quantity)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (branch, luggage_type, year_month)
                DO UPDATE SET quantity = EXCLUDED.quantity, updated_at = NOW()
            """, (branch, luggage_type, year_month, quantity))
        self.conn.commit()

    def bulk_upsert_history(self, records: list[dict]):
        """records: [{'branch','luggage_type','year_month','quantity'}]"""
        with self.conn.cursor() as cur:
            for r in records:
                cur.execute("""
                    INSERT INTO forecast_history (branch, luggage_type, year_month, quantity)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (branch, luggage_type, year_month)
                    DO UPDATE SET quantity = EXCLUDED.quantity, updated_at = NOW()
                """, (r['branch'], r['luggage_type'], r['year_month'], r['quantity']))
        self.conn.commit()

    def get_history(self, branches: list[str] | None = None,
                    luggage_types: list[str] | None = None) -> pd.DataFrame:
        """מחזיר DataFrame: branch, luggage_type, year_month, quantity"""
        query = "SELECT branch, luggage_type, year_month, quantity FROM forecast_history"
        conditions, params = [], []
        if branches:
            conditions.append("branch = ANY(%s)")
            params.append(branches)
        if luggage_types:
            conditions.append("luggage_type = ANY(%s)")
            params.append(luggage_types)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY branch, luggage_type, year_month"
        return pd.read_sql_query(query, self.conn, params=params or None)

    def get_covered_months(self) -> set[str]:
        """חודשים שכבר קיימים ב-forecast_history"""
        with self.conn.cursor() as cur:
            cur.execute("SELECT DISTINCT year_month FROM forecast_history")
            return {row[0] for row in cur.fetchall()}

    def get_branches(self) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT DISTINCT branch FROM forecast_history ORDER BY branch")
            return [r[0] for r in cur.fetchall()]

    # ------------------------------------------------------------------ #
    #  forecast_events                                                     #
    # ------------------------------------------------------------------ #

    def get_events(self) -> pd.DataFrame:
        return pd.read_sql_query(
            "SELECT * FROM forecast_events ORDER BY year_month",
            self.conn
        )

    def get_event(self, year_month: str) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM forecast_events WHERE year_month = %s", (year_month,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    def upsert_event(self, year_month: str, **kwargs):
        fields = ['is_war', 'is_military_op', 'is_ceasefire',
                  'jewish_holiday', 'season', 'is_summer_peak',
                  'travel_impact', 'notes']
        data = {f: kwargs.get(f) for f in fields if f in kwargs}
        if not data:
            return
        set_clause = ", ".join(f"{k} = %s" for k in data)
        with self.conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO forecast_events (year_month, {', '.join(data.keys())})
                VALUES (%s, {', '.join(['%s'] * len(data))})
                ON CONFLICT (year_month) DO UPDATE SET {set_clause}
            """, [year_month] + list(data.values()) + list(data.values()))
        self.conn.commit()

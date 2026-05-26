# -*- coding: utf-8 -*-
"""
002_seed_from_code.py — no-op (Sprint C7.3).

ההיסטוריה: גרסה מקורית של המיגרציה הזאת זרעה את ה-domain tables
(pricing_tiers, branches, warehouses, luggage_identification) מתוך
4 קבצי Python ישנים: pricing_data, branch_names, warehouse_config,
product_identification.

ב-Sprint A2 הקבצים האלה הוסרו לחלוטין — הנתונים עברו לחיות ב-DB,
וה-domain_repository הוא היחיד שמדבר אל הטבלאות. ההערה במיגרציה
אמרה "schema_version מסמן ב-applied, היא לא תרוץ שוב" — וזה היה נכון
על המכונה של הדב. אבל על **מכונה חדשה** עם DB ריק, migrate.py דווקא
**יריץ** את המיגרציה הזאת ויקרוס ב-ModuleNotFoundError על pricing_data.

הפתרון: הופכים את הקובץ ל-no-op. במכונות שכבר רצה — schema_version
כבר מסמן applied, אין שינוי. במכונה חדשה — ירוץ ריק וייסמן applied.
הנתונים יזרמו בכל מקרה דרך Updates tab + domain_repository כשהמשתמש
יוסיף לקוחות/סניפים/מחסנים.
"""


def run(conn):
    """No-op. ראה docstring למעלה לפרטים."""
    return

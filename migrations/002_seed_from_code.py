# -*- coding: utf-8 -*-
"""
002_seed_from_code.py - מעביר את ה-domain data מקבצי הקוד הקיימים
(pricing_data.py, branch_names.py, warehouse_config.py,
product_identification.py) לטבלאות שנוצרו ב-001.

מריץ INSERT ... ON CONFLICT DO NOTHING כדי שאפשר יהיה להריץ מחדש בבטחה.
"""
from pricing_data import (
    CUSTOMER_REPAIR_PRICING,
    CUSTOMER_REPLACEMENT_PRICING,
    REPAIR_PRICING,
    REPLACEMENT_PRICING,
    SUPPLIER_REPAIR_PRICING,
    SUPPLIER_REPLACEMENT_PRICING,
)
from branch_names import BRANCH_NAMES
from warehouse_config import APPROVED_WAREHOUSES
from product_identification import LUGGAGE_IDENTIFICATION


SEED_USER = 'seed:002'


def run(conn):
    cur = conn.cursor()

    # 1) pricing_tiers - כל ה-keys מ-REPAIR_PRICING ∪ REPLACEMENT_PRICING
    tiers = set(REPAIR_PRICING.keys()) | set(REPLACEMENT_PRICING.keys())
    for t in sorted(tiers):
        cur.execute("""
            INSERT INTO pricing_tiers (code, updated_by)
            VALUES (%s, %s) ON CONFLICT (code) DO NOTHING
        """, (t, SEED_USER))

    # 2) customers - מ-CUSTOMER_REPAIR_PRICING (זהה ל-REPLACEMENT לפי הבדיקה)
    customers = dict(CUSTOMER_REPAIR_PRICING)
    customers.update(CUSTOMER_REPLACEMENT_PRICING)  # למקרה של חוסר התאמה
    for code, tier in customers.items():
        cur.execute("""
            INSERT INTO customers (code, pricing_tier, updated_by)
            VALUES (%s, %s, %s) ON CONFLICT (code) DO NOTHING
        """, (code, tier, SEED_USER))

    # 3) customer_repair_prices: tier x sku => price
    for tier, prices in REPAIR_PRICING.items():
        for sku, price in prices.items():
            cur.execute("""
                INSERT INTO customer_repair_prices
                    (pricing_tier, part_sku, price, updated_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (pricing_tier, part_sku) DO NOTHING
            """, (tier, sku, price, SEED_USER))

    # 4) customer_replacement_prices
    for tier, prices in REPLACEMENT_PRICING.items():
        for ltype, price in prices.items():
            cur.execute("""
                INSERT INTO customer_replacement_prices
                    (pricing_tier, luggage_type, price, updated_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (pricing_tier, luggage_type) DO NOTHING
            """, (tier, ltype, price, SEED_USER))

    # 5) supplier_repair_prices
    for sku, price in SUPPLIER_REPAIR_PRICING.items():
        cur.execute("""
            INSERT INTO supplier_repair_prices (part_sku, price, updated_by)
            VALUES (%s, %s, %s) ON CONFLICT (part_sku) DO NOTHING
        """, (sku, price, SEED_USER))

    # 6) supplier_replacement_prices
    for ltype, price in SUPPLIER_REPLACEMENT_PRICING.items():
        cur.execute("""
            INSERT INTO supplier_replacement_prices
                (luggage_type, price, updated_by)
            VALUES (%s, %s, %s) ON CONFLICT (luggage_type) DO NOTHING
        """, (ltype, price, SEED_USER))

    # 7) branches
    for code, name in BRANCH_NAMES.items():
        cur.execute("""
            INSERT INTO branches (code, name, updated_by)
            VALUES (%s, %s, %s) ON CONFLICT (code) DO NOTHING
        """, (code, name, SEED_USER))

    # 8) warehouses - APPROVED_WAREHOUSES כולל גם "לא פעיל" בשם.
    # מסמן is_active = False אם הטקסט מכיל "לא פעיל".
    for code, name in APPROVED_WAREHOUSES.items():
        is_active = 'לא פעיל' not in (name or '') and not name.startswith('***')
        cur.execute("""
            INSERT INTO warehouses
                (code, name, is_active, is_approved, updated_by)
            VALUES (%s, %s, %s, TRUE, %s)
            ON CONFLICT (code) DO NOTHING
        """, (code, name, is_active, SEED_USER))

    # 9) luggage_identification: description => category
    seen = set()
    for category, descriptions in LUGGAGE_IDENTIFICATION.items():
        for desc in descriptions:
            # PRIMARY KEY=description; אם יש כפילות בין קטגוריות, ניקח הראשון
            if desc in seen:
                continue
            seen.add(desc)
            cur.execute("""
                INSERT INTO luggage_identification
                    (description, category, updated_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (description) DO NOTHING
            """, (desc, category, SEED_USER))

    conn.commit()
    cur.close()

    # סיכום
    with conn.cursor() as cur2:
        for tbl in ['pricing_tiers', 'customers',
                    'customer_repair_prices', 'customer_replacement_prices',
                    'supplier_repair_prices', 'supplier_replacement_prices',
                    'branches', 'warehouses', 'luggage_identification']:
            cur2.execute(f"SELECT COUNT(*) FROM {tbl}")
            n = cur2.fetchone()[0]
            print(f"    {tbl}: {n} rows")

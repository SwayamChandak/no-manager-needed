"""
db/seed.py — Populate the store schema with realistic seed data.

All timestamps are relative to date.today() so the seed is always
meaningful regardless of when it is run.

Usage:
    python -m db.seed
"""

import asyncio
import json
import random
import uuid
from datetime import date, datetime, timedelta, timezone

import asyncpg

try:
    from config import settings
    _DATABASE_URL = settings.database_url
except Exception:
    import os
    _DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ─── Deterministic UUIDs ──────────────────────────────────────────────────────
P001 = uuid.UUID("a1b2c3d4-0001-0001-0001-000000000001")
P002 = uuid.UUID("a1b2c3d4-0002-0002-0002-000000000002")
P003 = uuid.UUID("a1b2c3d4-0003-0003-0003-000000000003")
P004 = uuid.UUID("a1b2c3d4-0004-0004-0004-000000000004")
P005 = uuid.UUID("a1b2c3d4-0005-0005-0005-000000000005")

CAMP_042 = uuid.UUID("b1c2d3e4-0042-0042-0042-000000000042")
CAMP_039 = uuid.UUID("b1c2d3e4-0039-0039-0039-000000000039")

PRODUCTS = [
    (P001, "P001", "Laptop Pro 15",      "Electronics", 1299.99, 850.00),
    (P002, "P002", "Wireless Mouse",     "Accessories",   29.99,  12.00),
    (P003, "P003", "USB-C Hub",          "Accessories",   49.99,  18.00),
    (P004, "P004", "Mechanical Keyboard","Peripherals",   89.99,  40.00),
    (P005, "P005", 'Monitor 27"',        "Electronics",  349.99, 200.00),
]

INVENTORY = [
    (P001, 45,  10, "ok"),
    (P002, 12,  20, "low"),
    (P003,  0,  15, "out_of_stock"),
    (P004,  8,  15, "low"),
    (P005, 23,   5, "ok"),
]

REGIONS = ["North America", "EMEA", "APAC"]

# Product weights for order item generation (P001 gets more share)
PRODUCT_WEIGHTS = [40, 20, 15, 15, 10]

rng = random.Random(42)  # deterministic seed


def _utc(d: date, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)


async def seed(dsn: str) -> None:
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn=dsn)
    today = date.today()

    try:
        # ── products ──────────────────────────────────────────────────────────
        print("[seed] Inserting products …")
        for pid, sku, name, cat, price, cost in PRODUCTS:
            await conn.execute(
                """
                INSERT INTO store.products
                    (product_id, sku, name, category, base_price, unit_cost, is_active)
                VALUES ($1, $2, $3, $4, $5, $6, TRUE)
                ON CONFLICT (product_id) DO NOTHING
                """,
                pid, sku, name, cat, price, cost,
            )

        # ── inventory ─────────────────────────────────────────────────────────
        print("[seed] Inserting inventory …")
        for pid, qty, threshold, status in INVENTORY:
            await conn.execute(
                """
                INSERT INTO store.inventory (product_id, stock_qty, reorder_threshold, status)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (product_id) DO NOTHING
                """,
                pid, qty, threshold, status,
            )

        # ── customers (10 rows, spread across 3 regions) ──────────────────────
        print("[seed] Inserting customers …")
        customer_ids: list[uuid.UUID] = []
        customer_regions: list[str] = []
        for i in range(10):
            cid = uuid.UUID(f"c0c0c0c0-{i:04d}-{i:04d}-{i:04d}-{i:012d}")
            region = REGIONS[i % 3]
            await conn.execute(
                """
                INSERT INTO store.customers (customer_id, email, name, region)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (customer_id) DO NOTHING
                """,
                cid,
                f"customer{i:04d}@example.com",
                f"Customer {i:04d}",
                region,
            )
            customer_ids.append(cid)
            customer_regions.append(region)

        # ── orders + order_items ──────────────────────────────────────────────
        print("[seed] Inserting orders and order items …")
        # Normal days: 20 orders; yesterday: 9 orders; today: 12 orders
        day_order_counts: dict[date, int] = {}
        for offset in range(14, 1, -1):          # days 14..2 ago
            day_order_counts[today - timedelta(days=offset)] = rng.randint(18, 22)
        day_order_counts[today - timedelta(days=1)] = 9   # yesterday — the drop
        day_order_counts[today] = 12

        price_map = {pid: price for pid, _, _, _, price, _ in PRODUCTS}

        for day, n_orders in day_order_counts.items():
            is_yesterday = (day == today - timedelta(days=1))
            is_today = (day == today)
            for i in range(n_orders):
                oid = uuid.uuid4()
                cid = rng.choice(customer_ids)
                hour = rng.randint(8, 20)
                minute = rng.randint(0, 59)
                created = _utc(day, hour, minute)
                # Recent orders are 'pending', older ones 'completed'
                age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
                status = "pending" if age_hours < 1 else "completed"
                completed_at = created + timedelta(minutes=30) if status == "completed" else None

                # Choose 1-3 products per order; P001 is weighted higher
                n_items = rng.randint(1, 3)
                chosen_products = rng.choices(PRODUCTS, weights=PRODUCT_WEIGHTS, k=n_items)
                # Deduplicate while preserving order
                seen: set[uuid.UUID] = set()
                items: list[tuple] = []
                for prod in chosen_products:
                    if prod[0] not in seen:
                        seen.add(prod[0])
                        qty = rng.randint(1, 3)
                        items.append((prod[0], qty, prod[4]))

                total = sum(qty * price for _, qty, price in items)

                await conn.execute(
                    """
                    INSERT INTO store.orders
                        (order_id, customer_id, status, total_amount, created_at, completed_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (order_id) DO NOTHING
                    """,
                    oid, cid, status, total, created, completed_at,
                )
                for pid, qty, unit_price in items:
                    await conn.execute(
                        """
                        INSERT INTO store.order_items
                            (order_id, product_id, quantity, unit_price)
                        VALUES ($1, $2, $3, $4)
                        """,
                        oid, pid, qty, unit_price,
                    )

        # ── campaigns ─────────────────────────────────────────────────────────
        print("[seed] Inserting campaigns …")
        await conn.execute(
            """
            INSERT INTO store.campaigns
                (campaign_id, external_id, name, channel, status, budget, spend_to_date, start_date)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (campaign_id) DO NOTHING
            """,
            CAMP_042, "CAMP_042", "Summer Tech Sale", "paid_search",
            "active", 10000.00, 4230.50, today - timedelta(days=14),
        )
        await conn.execute(
            """
            INSERT INTO store.campaigns
                (campaign_id, external_id, name, channel, status, budget, spend_to_date,
                 start_date, paused_at, paused_reason)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (campaign_id) DO NOTHING
            """,
            CAMP_039, "CAMP_039", "Brand Awareness Q1", "social_ads",
            "paused", 15000.00, 9800.00, today - timedelta(days=30),
            datetime.now(timezone.utc) - timedelta(days=2),
            "ROAS below 1.5 threshold",
        )

        # ── campaign_products ─────────────────────────────────────────────────
        print("[seed] Inserting campaign products …")
        for camp, prod in [(CAMP_042, P001), (CAMP_042, P002)]:
            await conn.execute(
                """
                INSERT INTO store.campaign_products (campaign_id, product_id)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
                """,
                camp, prod,
            )

        # ── campaign_metrics (7 days each) ────────────────────────────────────
        print("[seed] Inserting campaign metrics …")
        for day_offset in range(7):
            day = today - timedelta(days=day_offset + 1)
            # CAMP_042 — healthy ROAS
            roas_042 = round(rng.uniform(2.1, 3.4), 2)
            spend_042 = round(rng.uniform(500, 700), 2)
            revenue_042 = round(spend_042 * roas_042, 2)
            await conn.execute(
                """
                INSERT INTO store.campaign_metrics
                    (campaign_id, date, spend, impressions, clicks, conversions, revenue, roas)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (campaign_id, date) DO NOTHING
                """,
                CAMP_042, day, spend_042,
                rng.randint(8000, 12000), rng.randint(400, 800),
                rng.randint(15, 35), revenue_042, roas_042,
            )
            # CAMP_039 — below-threshold ROAS
            roas_039 = round(rng.uniform(0.9, 1.4), 2)
            spend_039 = round(rng.uniform(300, 500), 2)
            revenue_039 = round(spend_039 * roas_039, 2)
            await conn.execute(
                """
                INSERT INTO store.campaign_metrics
                    (campaign_id, date, spend, impressions, clicks, conversions, revenue, roas)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (campaign_id, date) DO NOTHING
                """,
                CAMP_039, day, spend_039,
                rng.randint(5000, 9000), rng.randint(200, 500),
                rng.randint(5, 15), revenue_039, roas_039,
            )

        # ── complaints ────────────────────────────────────────────────────────
        print("[seed] Inserting complaints …")
        yesterday = today - timedelta(days=1)
        # 10 out-of-stock complaints, mostly yesterday
        oos_complaint_days = [yesterday] * 7 + [today - timedelta(days=2)] * 3
        for i, day in enumerate(oos_complaint_days):
            created = _utc(day, rng.randint(9, 22))
            await conn.execute(
                """
                INSERT INTO store.complaints (type, category, description, status, created_at)
                VALUES ('complaint', 'item_out_of_stock', $1, 'open', $2)
                """,
                f"Item out of stock — order #{1000 + i}", created,
            )
        # 8 slow-shipping complaints
        for i in range(8):
            day = today - timedelta(days=rng.randint(1, 5))
            await conn.execute(
                """
                INSERT INTO store.complaints (type, category, description, status, created_at)
                VALUES ('complaint', 'slow_shipping', $1, 'open', $2)
                """,
                f"Shipping delayed beyond expected date #{2000 + i}",
                _utc(day, rng.randint(8, 21)),
            )
        # 4 wrong-item complaints
        for i in range(4):
            day = today - timedelta(days=rng.randint(1, 4))
            await conn.execute(
                """
                INSERT INTO store.complaints (type, category, description, status, created_at)
                VALUES ('complaint', 'wrong_item', $1, 'open', $2)
                """,
                f"Received wrong item #{3000 + i}",
                _utc(day, rng.randint(10, 20)),
            )
        # 8 positive reviews
        for i in range(8):
            day = today - timedelta(days=rng.randint(0, 6))
            await conn.execute(
                """
                INSERT INTO store.complaints
                    (type, product_id, description, rating, sentiment, status, created_at)
                VALUES ('review', $1, $2, $3, 'positive', 'open', $4)
                """,
                rng.choice([P001, P002, P004, P005]),
                f"Great product, very happy! #{4000 + i}",
                rng.randint(4, 5),
                _utc(day, rng.randint(9, 21)),
            )
        # 3 neutral reviews
        for i in range(3):
            day = today - timedelta(days=rng.randint(0, 6))
            await conn.execute(
                """
                INSERT INTO store.complaints
                    (type, product_id, description, rating, sentiment, status, created_at)
                VALUES ('review', $1, $2, $3, 'neutral', 'open', $4)
                """,
                rng.choice([P002, P003, P004]),
                f"It's okay, nothing special #{5000 + i}",
                3,
                _utc(day, rng.randint(10, 18)),
            )
        # 5 negative reviews
        for i in range(5):
            day = today - timedelta(days=rng.randint(0, 4))
            await conn.execute(
                """
                INSERT INTO store.complaints
                    (type, product_id, description, rating, sentiment, status, created_at)
                VALUES ('review', $1, $2, $3, 'negative', 'open', $4)
                """,
                rng.choice([P001, P003]),
                f"Very disappointed, item was unavailable #{6000 + i}",
                rng.randint(1, 2),
                _utc(day, rng.randint(9, 22)),
            )

        # ── inventory_events — stockout for Laptop Pro 15 yesterday ──────────
        print("[seed] Inserting inventory events …")
        stockout_time = _utc(yesterday, 13, 45)
        await conn.execute(
            """
            INSERT INTO store.inventory_events
                (product_id, event_type, quantity_delta, stock_after, notes, created_at)
            VALUES ($1, 'stockout', 0, 0, $2, $3)
            """,
            P001,
            "Stock depleted during Summer Tech Sale campaign",
            stockout_time,
        )

        print("[seed] Done — all seed data inserted successfully.")

    finally:
        await conn.close()


def main() -> None:
    if not _DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to your .env file or set the "
            "environment variable before running db.seed."
        )
    asyncio.run(seed(_DATABASE_URL))


if __name__ == "__main__":
    main()

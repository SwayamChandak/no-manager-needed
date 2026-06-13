"""
db/seed_extra.py — Bulk data extension for the store schema.

Adds on top of the base seed (db/seed.py):
  • 15 new products + inventory records
  • 50 additional customers
  • 60 days of order history at higher volume (~20-35 orders/day)
  • Price history entries for all products
  • 4 new campaigns across remaining channels (email, display, affiliate, social_ads)
  • 30 days of campaign metrics per new campaign
  • Campaign-product associations
  • 3 promotions (2 expired, 1 active)
  • 80 complaints + 60 reviews spread over 30 days
  • 40 restock orders across low/out-of-stock products
  • 80 inventory events (sale, restock, adjustment, stockout, writeoff)
  • 35 support tickets

Usage:
    python -m db.seed_extra
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

rng = random.Random(77)


def _utc(d: date, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)


# ─── Existing product UUIDs from base seed ────────────────────────────────────
P001 = uuid.UUID("a1b2c3d4-0001-0001-0001-000000000001")
P002 = uuid.UUID("a1b2c3d4-0002-0002-0002-000000000002")
P003 = uuid.UUID("a1b2c3d4-0003-0003-0003-000000000003")
P004 = uuid.UUID("a1b2c3d4-0004-0004-0004-000000000004")
P005 = uuid.UUID("a1b2c3d4-0005-0005-0005-000000000005")

EXISTING_PRODUCTS = [P001, P002, P003, P004, P005]


def _pid(n: int) -> uuid.UUID:
    """Generate a deterministic product UUID for new products (range 6-20)."""
    return uuid.UUID(f"a2b3c4d5-{n:04d}-{n:04d}-{n:04d}-{n:012d}")


def _cid(n: int) -> uuid.UUID:
    """Generate a deterministic campaign UUID for new campaigns (range 101-104)."""
    return uuid.UUID(f"b2c3d4e5-{n:04d}-{n:04d}-{n:04d}-{n:012d}")


# ─── New products ─────────────────────────────────────────────────────────────
# (product_id, sku, name, category, base_price, unit_cost)
NEW_PRODUCTS = [
    (_pid(6),  "P006", "Noise-Cancelling Headphones", "Electronics", 199.99,  90.00),
    (_pid(7),  "P007", "Webcam 4K",                   "Electronics",  89.99,  35.00),
    (_pid(8),  "P008", "Ergonomic Chair",              "Furniture",   399.99, 180.00),
    (_pid(9),  "P009", "Standing Desk",                "Furniture",   649.99, 300.00),
    (_pid(10), "P010", "Desk Lamp LED",                "Accessories",  34.99,  12.00),
    (_pid(11), "P011", "USB-C Charging Dock",          "Accessories",  59.99,  20.00),
    (_pid(12), "P012", "Portable SSD 1TB",             "Storage",     109.99,  50.00),
    (_pid(13), "P013", "Laptop Stand",                 "Accessories",  44.99,  15.00),
    (_pid(14), "P014", "Wireless Keyboard",            "Peripherals",  69.99,  28.00),
    (_pid(15), "P015", "Smart Plug 4-Pack",            "Smart Home",   29.99,   9.00),
    (_pid(16), "P016", "HDMI Cable 2m",                "Accessories",  12.99,   3.00),
    (_pid(17), "P017", 'Monitor 32" 4K',               "Electronics", 499.99, 230.00),
    (_pid(18), "P018", "Tablet Pro 11",                "Electronics", 749.99, 350.00),
    (_pid(19), "P019", "Bluetooth Speaker",            "Electronics",  79.99,  30.00),
    (_pid(20), "P020", "Cable Management Kit",         "Accessories",  19.99,   5.00),
]

NEW_PRODUCT_IDS = [p[0] for p in NEW_PRODUCTS]
ALL_PRODUCT_IDS = EXISTING_PRODUCTS + NEW_PRODUCT_IDS  # 20 total

# Base price lookup for all products
PRICE_MAP: dict[uuid.UUID, float] = {
    P001: 1299.99, P002: 29.99, P003: 49.99, P004: 89.99, P005: 349.99,
    **{p[0]: p[4] for p in NEW_PRODUCTS},
}

# Inventory for new products: {product_id: (stock_qty, reorder_threshold, status)}
NEW_INVENTORY: dict[uuid.UUID, tuple[int, int, str]] = {
    _pid(6):  (32,  10, "ok"),
    _pid(7):  (18,  10, "ok"),
    _pid(8):  (5,    8, "low"),
    _pid(9):  (3,    5, "low"),
    _pid(10): (67,  15, "ok"),
    _pid(11): (41,  10, "ok"),
    _pid(12): (22,  10, "ok"),
    _pid(13): (55,  15, "ok"),
    _pid(14): (14,  20, "low"),
    _pid(15): (89,  20, "ok"),
    _pid(16): (120, 30, "ok"),
    _pid(17): (0,    5, "out_of_stock"),
    _pid(18): (9,   10, "low"),
    _pid(19): (38,  15, "ok"),
    _pid(20): (75,  20, "ok"),
}

# Order generation weights — must match len(ALL_PRODUCT_IDS) = 20
ORDER_WEIGHTS = [
    25, 15, 12, 10, 8,   # P001–P005 (existing)
    10,  8,  4,  3, 12,  # P006–P010
     9,  7,  9,  8, 14,  # P011–P015
    18,  5,  6, 10, 15,  # P016–P020
]

# ─── New campaigns ────────────────────────────────────────────────────────────
CAMP_101 = _cid(101)  # email
CAMP_102 = _cid(102)  # display
CAMP_103 = _cid(103)  # affiliate (completed)
CAMP_104 = _cid(104)  # social_ads (paused)

# ─── Static text pools ────────────────────────────────────────────────────────
REGIONS = ["North America", "EMEA", "APAC", "LATAM", "ANZ"]

COMPLAINT_TEXTS: dict[str, list[str]] = {
    "item_out_of_stock": [
        "The item I ordered shows as in stock but was cancelled after payment.",
        "Tried to order but the item ran out during checkout.",
        "Website said available but I got an out-of-stock notification afterwards.",
        "My order was cancelled — product listed as out of stock at fulfilment.",
        "Can't believe it was listed as available and now it's not.",
        "Product was in my cart but became unavailable at the payment step.",
        "Ordered based on the stock display but received a cancellation email.",
    ],
    "order_cancelled": [
        "My order was cancelled without any explanation.",
        "Received a cancellation email two days after placing the order.",
        "Order cancelled — very frustrating experience.",
        "I waited three days only to find out my order was cancelled.",
        "No notification until I checked my account — already cancelled.",
        "Cancellation email received 48 hours after the original order.",
        "Order cancelled the day before the expected delivery date.",
    ],
    "slow_shipping": [
        "Package promised in two days, it has been six and still not delivered.",
        "Tracking shows no movement for four consecutive days.",
        "Shipping is extremely slow compared to what was advertised.",
        "Expected delivery was last week — still waiting.",
        "The carrier has not updated the tracking status in days.",
        "I paid for expedited shipping but it has been over a week.",
        "Standard delivery is taking three times as long as usual.",
    ],
    "wrong_item": [
        "Received a completely different product from what I ordered.",
        "Got the wrong colour and model — this is unacceptable.",
        "The item delivered does not match the description at all.",
        "I ordered one product but received something entirely different.",
        "Wrong size, wrong brand — nothing matches my order.",
        "The box label was correct but the contents were wrong.",
        "Received a duplicate of another item instead of what I ordered.",
    ],
    "damaged": [
        "Product arrived with a cracked screen.",
        "Packaging was completely crushed and the item is broken.",
        "Item was clearly damaged in transit and is unusable.",
        "Dented casing and broken components on arrival.",
        "Dead pixels on the screen straight out of the box.",
        "One corner of the device was shattered.",
        "Internal parts rattling — obviously damaged during shipping.",
    ],
    "billing": [
        "I was charged twice for the same order.",
        "Refund has not shown up after ten business days.",
        "An extra charge appeared on my card statement.",
        "Invoice amount does not match what I was quoted at checkout.",
        "I never authorised this charge — please investigate urgently.",
        "Discount code was applied but the full price was still charged.",
        "Card was charged but the order shows as pending — nothing received.",
    ],
    "other": [
        "The product does not match the description on the website.",
        "I cannot log into my account to track my order.",
        "The size guide on the website is misleading.",
        "Customer service has not responded to multiple emails.",
        "Return process is overly complicated.",
        "Gift wrapping was not applied despite being selected.",
        "Account locked after failed login attempts — need assistance.",
    ],
}

REVIEW_TEXTS: dict[str, list[str]] = {
    "positive": [
        "Absolutely love this product! Exactly as described.",
        "Fast delivery and great quality. Will buy again.",
        "Exceeded my expectations — highly recommend.",
        "Perfect condition on arrival, very satisfied.",
        "Five stars — this is exactly what I needed.",
        "Outstanding build quality and excellent value for money.",
        "Works perfectly straight out of the box.",
        "Packaging was excellent and the product is superb.",
        "Best purchase I have made this year. Really impressed.",
        "Prompt delivery and the product is fantastic.",
    ],
    "neutral": [
        "Decent product, nothing special but does the job.",
        "Average quality for the price. Gets the task done.",
        "Works as expected; packaging was a bit damaged.",
        "Okay product, delivery was slow but the item itself is fine.",
        "It is alright — not as impressive as the photos suggest.",
        "Does what it says on the tin. No complaints but nothing wow either.",
    ],
    "negative": [
        "Disappointed with the quality for this price.",
        "Stopped working after one week — very poor quality.",
        "Item does not match description. Misleading product photos.",
        "Would not recommend — cheaply made and fragile.",
        "Had to return it — did not work as advertised.",
        "Extremely fragile. Broke within days of normal use.",
        "Customer support was no help when I raised the issue.",
        "Not worth the price at all. Feel cheated.",
    ],
}

TICKET_ISSUES = [
    ("Customer unable to complete checkout — payment gateway timeout", "high"),
    ("Laptop Pro 15 order cancelled post-payment — requesting full refund", "critical"),
    ("Wrong item delivered — customer requests prepaid return label", "high"),
    ("Tracking number not updating for 5+ days", "medium"),
    ("Double charge on order — billing dispute raised", "high"),
    ("Customer cannot log into account — locked out", "medium"),
    ("Product damaged in transit — replacement or refund requested", "high"),
    ("Promo code not applied at checkout — requesting credit", "low"),
    ("Order arrived missing one item — partial delivery", "medium"),
    ("Request for VAT invoice for business purchase", "low"),
    ("Refund not received after 14 business days", "high"),
    ("Return request — item not as described on website", "medium"),
    ("Website showing incorrect stock levels — customer complaint", "medium"),
    ("Customer requesting expedited re-ship due to carrier delay", "medium"),
    ('Bulk order enquiry — 50+ units of Monitor 27"', "medium"),
    ("Campaign promo discount not reflected in cart total", "medium"),
    ("Package delivered to wrong address — urgent reroute needed", "critical"),
    ("Customer complaint about Summer Tech Sale — out-of-stock items", "high"),
    ('Monitor 32" 4K — flickering screen reported on arrival', "high"),
    ("Ergonomic Chair missing assembly bolt", "medium"),
    ("Bluetooth Speaker — no audio from left channel", "high"),
    ("Customer escalation — third consecutive delayed order", "critical"),
    ("Smart Plug not pairing with home assistant app", "medium"),
    ("Repeated promotional emails after unsubscribe request", "high"),
    ("International shipping surcharge dispute", "medium"),
    ("Noise-Cancelling Headphones — battery drains within 2 hours", "high"),
    ("Account merge request — two accounts under same email", "low"),
    ("USB-C Hub causing device overheating — safety concern", "critical"),
    ("Standing Desk delivery slot rescheduling request", "low"),
    ("Gift wrapping not applied despite being selected at checkout", "low"),
    ("Tablet Pro 11 — touchscreen unresponsive in top-right quadrant", "high"),
    ("Order cancellation within 30-minute window — agent override needed", "medium"),
    ("Portable SSD data corruption reported after firmware update", "critical"),
    ("Customer requests size/compatibility chart correction on website", "low"),
    ("Webcam 4K — driver incompatibility with Windows 11 reported", "medium"),
]


async def seed_extra(dsn: str) -> None:
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn=dsn)
    today = date.today()

    try:
        # ── 1. New products ───────────────────────────────────────────────────
        print("[seed_extra] Inserting 15 new products …")
        for pid, sku, name, cat, price, cost in NEW_PRODUCTS:
            await conn.execute(
                """
                INSERT INTO store.products
                    (product_id, sku, name, category, base_price, unit_cost, is_active)
                VALUES ($1, $2, $3, $4, $5, $6, TRUE)
                ON CONFLICT (product_id) DO NOTHING
                """,
                pid, sku, name, cat, price, cost,
            )

        # ── 2. Inventory for new products ─────────────────────────────────────
        print("[seed_extra] Inserting inventory records for new products …")
        for pid, (qty, threshold, status) in NEW_INVENTORY.items():
            await conn.execute(
                """
                INSERT INTO store.inventory (product_id, stock_qty, reorder_threshold, status)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (product_id) DO NOTHING
                """,
                pid, qty, threshold, status,
            )

        # ── 3. Customers (50 new) ─────────────────────────────────────────────
        print("[seed_extra] Inserting 50 new customers …")
        customer_ids: list[uuid.UUID] = []
        for i in range(50):
            cid = uuid.UUID(f"d1d2d3d4-{i:04d}-{i:04d}-{i:04d}-{i:012d}")
            region = rng.choice(REGIONS)
            await conn.execute(
                """
                INSERT INTO store.customers (customer_id, email, name, region)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (customer_id) DO NOTHING
                """,
                cid,
                f"user{i:04d}@shopmail.com",
                f"Shopper {i:04d}",
                region,
            )
            customer_ids.append(cid)

        # ── 4. Orders + order_items (60 days) ─────────────────────────────────
        print("[seed_extra] Inserting orders and order items (60 days) …")
        for day_offset in range(60, 0, -1):
            day = today - timedelta(days=day_offset)
            is_weekend = day.weekday() in (5, 6)
            n_orders = rng.randint(8, 14) if is_weekend else rng.randint(18, 35)

            for _ in range(n_orders):
                oid = uuid.uuid4()
                cid = rng.choice(customer_ids)
                created = _utc(day, rng.randint(7, 22), rng.randint(0, 59))
                age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
                if age_hours < 1:
                    status = "pending"
                elif rng.random() < 0.06:
                    status = "cancelled"
                else:
                    status = "completed"

                completed_at = (
                    created + timedelta(minutes=rng.randint(15, 90))
                    if status == "completed"
                    else None
                )

                # 1–4 distinct products per order, weighted by popularity
                chosen_pids = rng.choices(ALL_PRODUCT_IDS, weights=ORDER_WEIGHTS, k=rng.randint(1, 4))
                seen: set[uuid.UUID] = set()
                items: list[tuple[uuid.UUID, int, float]] = []
                for pid in chosen_pids:
                    if pid not in seen:
                        seen.add(pid)
                        qty = rng.randint(1, 3)
                        items.append((pid, qty, PRICE_MAP[pid]))

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
                        INSERT INTO store.order_items (order_id, product_id, quantity, unit_price)
                        VALUES ($1, $2, $3, $4)
                        """,
                        oid, pid, qty, unit_price,
                    )

        # ── 5. Price history ──────────────────────────────────────────────────
        print("[seed_extra] Inserting price history …")
        for pid, base_price in PRICE_MAP.items():
            # Older price point (6 months ago, since expired)
            old_price_6m = round(base_price * rng.uniform(0.88, 1.12), 2)
            from_6m = _utc(today - timedelta(days=180))
            to_6m   = _utc(today - timedelta(days=90))
            await conn.execute(
                """
                INSERT INTO store.price_history
                    (product_id, price, effective_from, effective_to, changed_by)
                VALUES ($1, $2, $3, $4, $5)
                """,
                pid, old_price_6m, from_6m, to_6m, "pricing_team",
            )
            # Mid price point (3 months ago, also expired)
            old_price_3m = round(base_price * rng.uniform(0.93, 1.07), 2)
            from_3m = _utc(today - timedelta(days=90))
            to_3m   = _utc(today - timedelta(days=30))
            await conn.execute(
                """
                INSERT INTO store.price_history
                    (product_id, price, effective_from, effective_to, changed_by)
                VALUES ($1, $2, $3, $4, $5)
                """,
                pid, old_price_3m, from_3m, to_3m, "pricing_team",
            )
            # Current price (effective_to = NULL means still active)
            await conn.execute(
                """
                INSERT INTO store.price_history
                    (product_id, price, effective_from, effective_to, changed_by)
                VALUES ($1, $2, $3, NULL, $4)
                """,
                pid, base_price, _utc(today - timedelta(days=30)), "pricing_team",
            )

        # ── 6. New campaigns ──────────────────────────────────────────────────
        print("[seed_extra] Inserting 4 new campaigns …")
        campaigns_data = [
            # (id, external_id, name, channel, status, budget, spend_to_date,
            #  start_date, end_date, paused_at, paused_reason)
            (
                CAMP_101, "CAMP_101", "Back to School Email Blast", "email",
                "active", 8000.00, 3100.00,
                today - timedelta(days=20), None, None, None,
            ),
            (
                CAMP_102, "CAMP_102", "Display Retargeting Q2", "display",
                "active", 5000.00, 2400.00,
                today - timedelta(days=15), None, None, None,
            ),
            (
                CAMP_103, "CAMP_103", "Affiliate Winter Push", "affiliate",
                "completed", 12000.00, 11800.00,
                today - timedelta(days=60), today - timedelta(days=10), None, None,
            ),
            (
                CAMP_104, "CAMP_104", "Social Media Flash Sale", "social_ads",
                "paused", 6000.00, 2900.00,
                today - timedelta(days=25), None,
                datetime.now(timezone.utc) - timedelta(days=3),
                "CTR below 0.8% threshold — paused for creative refresh",
            ),
        ]
        for row in campaigns_data:
            camp_id, ext_id, name, channel, status, budget, spend, start, end, paused_at, paused_reason = row
            await conn.execute(
                """
                INSERT INTO store.campaigns
                    (campaign_id, external_id, name, channel, status, budget, spend_to_date,
                     start_date, end_date, paused_at, paused_reason)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (campaign_id) DO NOTHING
                """,
                camp_id, ext_id, name, channel, status, budget, spend,
                start, end, paused_at, paused_reason,
            )

        # ── 7. Campaign-product associations ──────────────────────────────────
        print("[seed_extra] Inserting campaign-product links …")
        camp_product_pairs = [
            (CAMP_101, _pid(6)),  (CAMP_101, _pid(14)), (CAMP_101, _pid(7)),
            (CAMP_102, P005),     (CAMP_102, _pid(17)), (CAMP_102, _pid(18)),
            (CAMP_103, P001),     (CAMP_103, _pid(12)), (CAMP_103, _pid(9)),
            (CAMP_104, _pid(19)), (CAMP_104, _pid(15)), (CAMP_104, _pid(11)),
        ]
        for camp_id, prod_id in camp_product_pairs:
            await conn.execute(
                """
                INSERT INTO store.campaign_products (campaign_id, product_id)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
                """,
                camp_id, prod_id,
            )

        # ── 8. Campaign metrics (30 days per new campaign) ────────────────────
        print("[seed_extra] Inserting campaign metrics (30 days × 4 campaigns) …")
        camp_configs = {
            CAMP_101: {"roas": (1.8, 3.2), "spend": (300, 500)},
            CAMP_102: {"roas": (1.5, 2.8), "spend": (200, 400)},
            CAMP_103: {"roas": (2.0, 3.8), "spend": (400, 600)},
            CAMP_104: {"roas": (0.6, 0.9), "spend": (250, 450)},
        }
        for camp_id, cfg in camp_configs.items():
            for day_offset in range(1, 31):
                day = today - timedelta(days=day_offset)
                roas = round(rng.uniform(*cfg["roas"]), 2)
                spend = round(rng.uniform(*cfg["spend"]), 2)
                revenue = round(spend * roas, 2)
                await conn.execute(
                    """
                    INSERT INTO store.campaign_metrics
                        (campaign_id, date, spend, impressions, clicks, conversions, revenue, roas)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (campaign_id, date) DO NOTHING
                    """,
                    camp_id, day, spend,
                    rng.randint(4000, 15000), rng.randint(150, 900),
                    rng.randint(5, 40), revenue, roas,
                )

        # ── 9. Promotions ─────────────────────────────────────────────────────
        print("[seed_extra] Inserting 3 promotions …")
        promotions = [
            {
                "promo_id": "PROMO_BTS2025",
                "product_ids": json.dumps([str(_pid(6)), str(_pid(14)), str(_pid(7))]),
                "discount_pct": 15.0,
                "duration_hours": 72,
                "starts_at": _utc(today - timedelta(days=20)),
                "expires_at": _utc(today - timedelta(days=17)),
                "status": "expired",
            },
            {
                "promo_id": "PROMO_FLASH01",
                "product_ids": json.dumps([str(_pid(15)), str(_pid(16)), str(_pid(20))]),
                "discount_pct": 20.0,
                "duration_hours": 24,
                "starts_at": _utc(today - timedelta(days=3)),
                "expires_at": _utc(today - timedelta(days=2)),
                "status": "expired",
            },
            {
                "promo_id": "PROMO_SUMMER2",
                "product_ids": json.dumps([str(P001), str(P005), str(_pid(17)), str(_pid(18))]),
                "discount_pct": 10.0,
                "duration_hours": 168,
                "starts_at": _utc(today),
                "expires_at": _utc(today + timedelta(days=7)),
                "status": "active",
            },
        ]
        for promo in promotions:
            await conn.execute(
                """
                INSERT INTO store.promotions
                    (promo_id, product_ids, discount_pct, duration_hours, starts_at, expires_at, status)
                VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7)
                ON CONFLICT (promo_id) DO NOTHING
                """,
                promo["promo_id"], promo["product_ids"], promo["discount_pct"],
                promo["duration_hours"], promo["starts_at"], promo["expires_at"], promo["status"],
            )

        # ── 10. Complaints and reviews ────────────────────────────────────────
        print("[seed_extra] Inserting 80 complaints …")
        complaint_categories = list(COMPLAINT_TEXTS.keys())
        for _ in range(80):
            day = today - timedelta(days=rng.randint(0, 29))
            cat = rng.choice(complaint_categories)
            text = rng.choice(COMPLAINT_TEXTS[cat])
            c_status = rng.choices(
                ["open", "in_progress", "resolved", "closed"],
                weights=[40, 20, 25, 15],
            )[0]
            resolved_at = (
                _utc(day + timedelta(days=rng.randint(1, 5)))
                if c_status in ("resolved", "closed")
                else None
            )
            await conn.execute(
                """
                INSERT INTO store.complaints
                    (type, category, description, status, created_at, resolved_at)
                VALUES ('complaint', $1, $2, $3, $4, $5)
                """,
                cat, text, c_status,
                _utc(day, rng.randint(7, 23), rng.randint(0, 59)),
                resolved_at,
            )

        print("[seed_extra] Inserting 60 reviews …")
        for _ in range(60):
            day = today - timedelta(days=rng.randint(0, 29))
            sentiment = rng.choices(
                ["positive", "neutral", "negative"],
                weights=[50, 20, 30],
            )[0]
            text = rng.choice(REVIEW_TEXTS[sentiment])
            rating = {"positive": rng.randint(4, 5), "neutral": 3, "negative": rng.randint(1, 2)}[sentiment]
            pid = rng.choice(ALL_PRODUCT_IDS)
            await conn.execute(
                """
                INSERT INTO store.complaints
                    (type, product_id, description, rating, sentiment, status, created_at)
                VALUES ('review', $1, $2, $3, $4, 'open', $5)
                """,
                pid, text, rating, sentiment,
                _utc(day, rng.randint(8, 22), rng.randint(0, 59)),
            )

        # ── 11. Restock orders ────────────────────────────────────────────────
        print("[seed_extra] Inserting 40 restock orders …")
        low_stock_pids = [
            _pid(8), _pid(9), _pid(14), _pid(17), _pid(18),
            P002, P003, P004,
        ]
        restock_statuses = ["pending", "confirmed", "received", "cancelled"]
        restock_weights  = [30, 35, 25, 10]
        for _ in range(40):
            pid = rng.choice(low_stock_pids)
            qty = rng.randint(20, 200)
            r_status = rng.choices(restock_statuses, weights=restock_weights)[0]
            days_ago = rng.randint(0, 30)
            created = _utc(today - timedelta(days=days_ago))
            received_at = (
                _utc(today - timedelta(days=max(0, days_ago - rng.randint(3, 10))))
                if r_status == "received"
                else None
            )
            await conn.execute(
                """
                INSERT INTO store.restock_orders
                    (product_id, quantity, status, estimated_arrival, created_at, received_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                pid, qty, r_status,
                f"{rng.randint(3, 14)} business days",
                created, received_at,
            )

        # ── 12. Inventory events ──────────────────────────────────────────────
        print("[seed_extra] Inserting 80 inventory events …")
        event_types   = ["sale", "restock", "adjustment", "stockout", "writeoff"]
        event_weights = [50, 25, 10, 10, 5]
        event_notes   = {
            "sale":       "Sale via storefront",
            "restock":    "Supplier delivery received",
            "adjustment": "Manual stock correction",
            "stockout":   "Stock fully depleted",
            "writeoff":   "Damaged goods written off",
        }
        for _ in range(80):
            pid = rng.choice(ALL_PRODUCT_IDS)
            event_type = rng.choices(event_types, weights=event_weights)[0]
            delta = {
                "sale":       -rng.randint(1, 5),
                "restock":     rng.randint(10, 100),
                "adjustment":  rng.randint(-3, 3),
                "stockout":    0,
                "writeoff":   -rng.randint(1, 3),
            }[event_type]
            stock_after = max(0, rng.randint(0, 50))
            day = today - timedelta(days=rng.randint(0, 59))
            await conn.execute(
                """
                INSERT INTO store.inventory_events
                    (product_id, event_type, quantity_delta, stock_after, notes, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                pid, event_type, delta, stock_after, event_notes[event_type],
                _utc(day, rng.randint(6, 23), rng.randint(0, 59)),
            )

        # ── 13. Support tickets ───────────────────────────────────────────────
        print("[seed_extra] Inserting 35 support tickets …")
        ticket_statuses        = ["open", "in_progress", "resolved", "closed"]
        ticket_status_weights  = [30, 25, 30, 15]
        for i, (issue, priority) in enumerate(TICKET_ISSUES):
            t_status = rng.choices(ticket_statuses, weights=ticket_status_weights)[0]
            days_ago = rng.randint(0, 29)
            created  = _utc(today - timedelta(days=days_ago), rng.randint(8, 20))
            resolved_at = (
                _utc(today - timedelta(days=max(0, days_ago - rng.randint(1, 7))))
                if t_status in ("resolved", "closed")
                else None
            )
            resolution_notes = (
                "Issue resolved — customer notified by email."
                if t_status in ("resolved", "closed")
                else None
            )
            await conn.execute(
                """
                INSERT INTO store.support_tickets
                    (ticket_id, issue_description, priority, status,
                     resolution_notes, created_at, resolved_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (ticket_id) DO NOTHING
                """,
                f"TKT-{1000 + i:04d}", issue, priority, t_status,
                resolution_notes, created, resolved_at,
            )

        print("[seed_extra] Done — all extra seed data inserted successfully.")
        print(f"  Products:          {len(NEW_PRODUCTS)} new")
        print(f"  Customers:         50 new")
        print(f"  Orders:            ~60 days × avg 22/day")
        print(f"  Price history:     {len(PRICE_MAP) * 3} entries (3 per product)")
        print(f"  Campaigns:         4 new")
        print(f"  Campaign metrics:  {4 * 30} rows")
        print(f"  Promotions:        3")
        print(f"  Complaints:        80")
        print(f"  Reviews:           60")
        print(f"  Restock orders:    40")
        print(f"  Inventory events:  80")
        print(f"  Support tickets:   {len(TICKET_ISSUES)}")

    finally:
        await conn.close()


def main() -> None:
    if not _DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to your .env file or set the "
            "environment variable before running db.seed_extra."
        )
    asyncio.run(seed_extra(_DATABASE_URL))


if __name__ == "__main__":
    main()

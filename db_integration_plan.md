# Database Integration Plan

## Overview

This plan replaces every hardcoded dict returned by the five tool files (`tools/analytics.py`, `tools/inventory.py`, `tools/crm.py`, `tools/campaigns.py`, `tools/actions.py`) with real `asyncpg` queries against a PostgreSQL `store` schema, wires the ops agent internal tables (`public` schema) so the agent persists its own reasoning and action history, configures `AsyncPostgresSaver` from `langgraph-checkpoint-postgres` as the LangGraph checkpointer so graph state survives process restarts and HITL pauses work across server restarts, and ensures the whole system initialises and tears down cleanly from `main.py`. Integration happens in 11 phases, each independently reviewable and implementable — no phase depends on code from a later phase.

---

## Phase 1 — Infrastructure: Docker Compose + PostgreSQL

### Goal

Get PostgreSQL 16 running locally so all subsequent phases have a target to connect to.

### New file: `docker-compose.yml` (project root)

The file must define a single service named `postgres` using the `postgres:16` image. It must:

- Accept credentials from environment variables `POSTGRES_USER`, `POSTGRES_PASSWORD`, and set `POSTGRES_DB=ops_agent`
- Expose port `5432:5432`
- Mount a named volume `pgdata` to `/var/lib/postgresql/data` for data persistence across container restarts
- Define a healthcheck using `pg_isready -U ${POSTGRES_USER} -d ops_agent` with a 5-second interval, 5-second timeout, and 5 retries

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ops_agent
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ops_agent"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

### Update: `.env.example`

Add the following block to `.env.example` (create it if it does not exist):

```
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=ops_agent
POSTGRES_USER=ops_user
POSTGRES_PASSWORD=ops_password
DATABASE_URL=postgresql+asyncpg://ops_user:ops_password@localhost:5432/ops_agent
```

### Command to start

```bash
docker compose up -d
```

Verify it is healthy before proceeding:

```bash
docker compose ps
# postgres service should show "healthy"
```

---

## Phase 2 — DDL: Apply Schemas

### Goal

Create all tables in both schemas against the running `ops_agent` database.

### New file: `db/migrations/001_public_schema.sql`

Copy the DDL exactly from the **Database Schema** section of `PROJECT_PLAN.md`. This file must create, in order:

1. `CREATE EXTENSION IF NOT EXISTS "pgcrypto";`
2. `CREATE TABLE sessions (...)` — with all columns, CHECK constraints, and default values as written in `PROJECT_PLAN.md`
3. `CREATE TABLE specialist_findings (...)` — including `UNIQUE (session_id, domain)`
4. `CREATE TABLE root_causes (...)`
5. `CREATE TABLE hitl_requests (...)` — including `UNIQUE` on `session_id`
6. `CREATE TABLE executed_actions (...)`
7. `CREATE TABLE incidents (...)`
8. All indexes listed in `PROJECT_PLAN.md`:
   - `idx_sessions_intent`, `idx_sessions_status`, `idx_sessions_created_at`
   - `idx_specialist_findings_session_id`
   - `idx_root_causes_session_id`
   - `idx_incidents_intent`, `idx_incidents_created_at`, `idx_incidents_qdrant_point`

Do **not** include `checkpoints`, `checkpoint_blobs`, or `checkpoint_writes` — those are auto-created by `AsyncPostgresSaver.from_conn_string()` in Phase 9.

### New file: `db/migrations/002_store_schema.sql`

Copy the DDL exactly from the **Full DDL** section of `schema.md`. This file must create, in order:

1. `CREATE EXTENSION IF NOT EXISTS "pgcrypto";` (idempotent; safe to repeat)
2. `CREATE SCHEMA IF NOT EXISTS store;`
3. All 14 tables in dependency order (parents before children):
   - `store.products`
   - `store.inventory`
   - `store.inventory_events`
   - `store.restock_orders`
   - `store.customers`
   - `store.orders`
   - `store.order_items`
   - `store.price_history`
   - `store.promotions`
   - `store.campaigns`
   - `store.campaign_metrics`
   - `store.campaign_products`
   - `store.complaints`
   - `store.support_tickets`
4. All indexes from `schema.md`:
   - `idx_orders_customer_id`, `idx_orders_status`, `idx_orders_created_at`
   - `idx_order_items_order_id`, `idx_order_items_product_id`
   - `idx_inventory_events_product_id`, `idx_inventory_events_event_type`, `idx_inventory_events_created_at`
   - `idx_campaign_metrics_campaign_id`, `idx_campaign_metrics_date`
   - `idx_complaints_type`, `idx_complaints_customer_id`, `idx_complaints_product_id`, `idx_complaints_category`, `idx_complaints_sentiment`, `idx_complaints_created_at`
   - `idx_support_tickets_status`, `idx_support_tickets_priority`, `idx_support_tickets_created_at`

### How to apply

Run both files against the live database in order:

```bash
psql postgresql://ops_user:ops_password@localhost:5432/ops_agent \
    -f db/migrations/001_public_schema.sql

psql postgresql://ops_user:ops_password@localhost:5432/ops_agent \
    -f db/migrations/002_store_schema.sql
```

### Alternative: `db/migrate.py`

Create a Python script `db/migrate.py` that reads `DATABASE_URL` from the environment (via `config.settings.database_url`) and applies both migration files using `asyncpg`. The script calls `asyncpg.connect(dsn=settings.database_url)`, reads each `.sql` file, executes it with `conn.execute(sql)`, and commits. Run it with:

```bash
python -m db.migrate
```

---

## Phase 3 — Seed Data

### Goal

Populate the `store` schema with enough realistic data so every tool function returns meaningful, non-empty results when the agents run the "Why did sales drop yesterday?" scenario.

### New file: `db/seed.sql`

The file must contain INSERT statements with **deterministic UUIDs** (hardcoded hex strings, not `gen_random_uuid()` calls) so that foreign key references across INSERT statements are consistent. Required data, by entity group:

#### `store.products` — 5 rows

Use hardcoded UUIDs matching the placeholder IDs from `schema.md` (P001–P005 map to UUIDs at seed time):

```sql
INSERT INTO store.products (product_id, sku, name, category, base_price, unit_cost, is_active)
VALUES
  ('a1b2c3d4-0001-0001-0001-000000000001', 'P001', 'Laptop Pro 15',       'Electronics', 1299.99, 850.00, TRUE),
  ('a1b2c3d4-0002-0002-0002-000000000002', 'P002', 'Wireless Mouse',       'Accessories',   29.99,  12.00, TRUE),
  ('a1b2c3d4-0003-0003-0003-000000000003', 'P003', 'USB-C Hub',            'Accessories',   49.99,  18.00, TRUE),
  ('a1b2c3d4-0004-0004-0004-000000000004', 'P004', 'Mechanical Keyboard',  'Peripherals',   89.99,  40.00, TRUE),
  ('a1b2c3d4-0005-0005-0005-000000000005', 'P005', 'Monitor 27"',          'Electronics',  349.99, 200.00, TRUE);
```

#### `store.inventory` — 5 rows

One row per product, stock quantities from the seed table in `schema.md`:

```sql
INSERT INTO store.inventory (product_id, stock_qty, reorder_threshold, status)
VALUES
  ('a1b2c3d4-0001-0001-0001-000000000001', 45,  10, 'ok'),
  ('a1b2c3d4-0002-0002-0002-000000000002', 12,  20, 'low'),
  ('a1b2c3d4-0003-0003-0003-000000000003',  0,  15, 'out_of_stock'),
  ('a1b2c3d4-0004-0004-0004-000000000004',  8,  15, 'low'),
  ('a1b2c3d4-0005-0005-0005-000000000005', 23,   5, 'ok');
```

#### `store.customers` — ~10 rows

Vary the `region` column across `'North America'`, `'EMEA'`, and `'APAC'` so `get_revenue_by_region` returns all three buckets.

#### `store.orders` — ~200 rows

Spread `created_at` timestamps across the last 14 days ending today (`CURRENT_DATE`). Include:
- Normal order volume for days 3–14 (approx 18–22 orders/day)
- A simulated drop yesterday (`CURRENT_DATE - 1`): approx 8–10 orders, representing a ~55% drop
- Orders for today (`CURRENT_DATE`): approx 12 orders (partial day)
- `status = 'completed'` for all orders older than 1 hour; `status = 'pending'` for very recent ones

#### `store.order_items` — ~400 rows

2 line items per order on average, each referencing one of the 5 product UUIDs. Use realistic `unit_price` values matching `base_price` from `store.products`, and ensure `Laptop Pro 15` (P001) accounts for a disproportionate share of revenue so the revenue-by-product tool shows a clear winner.

#### `store.campaigns` — 2 rows

```sql
INSERT INTO store.campaigns
  (campaign_id, external_id, name, channel, status, budget, spend_to_date, start_date)
VALUES
  ('b1c2d3e4-0042-0042-0042-000000000042', 'CAMP_042', 'Summer Tech Sale',     'paid_search', 'active', 10000.00, 4230.50, CURRENT_DATE - 14),
  ('b1c2d3e4-0039-0039-0039-000000000039', 'CAMP_039', 'Brand Awareness Q1',   'social_ads',  'paused', 15000.00, 9800.00, CURRENT_DATE - 30);
```

For `CAMP_039`, also set `paused_at = CURRENT_TIMESTAMP - INTERVAL '2 days'` and `paused_reason = 'ROAS below 1.5 threshold'`.

#### `store.campaign_products` — 2 rows

Link `CAMP_042` to Laptop Pro 15 and Wireless Mouse:

```sql
INSERT INTO store.campaign_products (campaign_id, product_id)
VALUES
  ('b1c2d3e4-0042-0042-0042-000000000042', 'a1b2c3d4-0001-0001-0001-000000000001'),
  ('b1c2d3e4-0042-0042-0042-000000000042', 'a1b2c3d4-0002-0002-0002-000000000002');
```

#### `store.campaign_metrics` — 7 rows per campaign (14 total)

One row per campaign per day for the last 7 days. For `CAMP_042`: ROAS between 2.1 and 3.4. For `CAMP_039`: ROAS between 0.9 and 1.4 (below threshold — explains why it was paused).

#### `store.complaints` — ~30 rows

Mix of `type = 'complaint'` and `type = 'review'` covering the last 7 days. For complaints, use categories: `'item_out_of_stock'` (10 rows, spiking yesterday), `'slow_shipping'` (8 rows), `'wrong_item'` (4 rows). For reviews: ratings 1–5, with `sentiment` values `'positive'` (8 rows), `'neutral'` (3 rows), `'negative'` (5 rows).

#### `store.inventory_events` — stockout events for Laptop Pro 15

```sql
INSERT INTO store.inventory_events (product_id, event_type, quantity_delta, stock_after, notes, created_at)
VALUES (
  'a1b2c3d4-0001-0001-0001-000000000001',
  'stockout',
  0,
  0,
  'Stock depleted during Summer Tech Sale campaign',
  (CURRENT_DATE - 1)::timestamptz + INTERVAL '13 hours 45 minutes'
);
```

This timestamp (13:45 yesterday) matches the scenario where the campaign was paused at 13:30 and stock hit zero at 13:45.

### How to apply

```bash
psql postgresql://ops_user:ops_password@localhost:5432/ops_agent -f db/seed.sql
```

### Alternative: `db/seed.py`

Create `db/seed.py` — a Python script that generates all seed data programmatically using `asyncpg` and `datetime.date.today()` so all timestamps are always relative to the current date, regardless of when the script is run. This is preferable for CI environments where the seed file is run on different dates. The script must:

1. Compute `today = date.today()` and derive all `created_at` values as `today - timedelta(days=N)`
2. Use the same hardcoded UUID constants as `db/seed.sql`
3. Insert all rows in dependency order (products → inventory → customers → orders → order_items → campaigns → campaign_products → campaign_metrics → complaints → inventory_events)
4. Be idempotent — use `INSERT ... ON CONFLICT DO NOTHING` for all rows keyed on deterministic UUIDs

Run with:

```bash
python -m db.seed
```

---

## Phase 4 — DB Connection Layer (`db/` module)

### Goal

Create a shared `asyncpg` connection pool that all tool files import. The pool is initialised once at application startup and torn down at shutdown.

### New file: `db/__init__.py`

Empty file to make `db/` a Python package.

### New file: `db/connection.py`

This module manages a module-level `asyncpg` pool. It must contain exactly these four components:

**Module-level variable:**
```python
import asyncpg
from typing import Optional

_pool: Optional[asyncpg.Pool] = None
```

**`init_pool(dsn: str, min_size: int = 2, max_size: int = 10) -> None`**

Async function called once at startup. Creates the pool and stores it in `_pool`:

```python
async def init_pool(dsn: str, min_size: int = 2, max_size: int = 10) -> None:
    global _pool
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=min_size, max_size=max_size)
```

**`get_pool() -> asyncpg.Pool`**

Synchronous accessor. Raises `RuntimeError` if called before `init_pool()`:

```python
def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool is not initialised. Call await init_pool() first.")
    return _pool
```

**`close_pool() -> None`**

Async function called at shutdown:

```python
async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
```

### Tool function signature: `async def`

All tool functions across `tools/analytics.py`, `tools/inventory.py`, `tools/crm.py`, `tools/campaigns.py`, and `tools/actions.py` will be converted to `async def`. LangChain's `@tool` decorator supports async functions natively — a tool decorated with `@tool` whose body is `async def` is automatically awaited by the LangChain tool runner. This is the cleanest approach for this stack because:

- LangGraph executes the graph asynchronously (via `graph.ainvoke(...)`)
- Mixing `asyncio.run()` inside an already-running event loop raises `RuntimeError: This event loop is already running`
- `asyncpg` pools expose async-only methods (`pool.fetch(...)`, `pool.fetchrow(...)`, `pool.fetchval(...)`, `pool.execute(...)`)

With `async def` tools, the DB call pattern inside every tool is simply:

```python
pool = get_pool()
rows = await pool.fetch(sql, param1, param2)
```

No thread pool executors or `asyncio.run_coroutine_threadsafe()` are needed.

### Pool method reference

| Use case | Method | Return type |
|---|---|---|
| Multiple rows (SELECT with GROUP BY, JOIN) | `pool.fetch(sql, *args)` | `list[asyncpg.Record]` |
| Single row (aggregate, RETURNING) | `pool.fetchrow(sql, *args)` | `asyncpg.Record \| None` |
| Single scalar value (COUNT, SUM) | `pool.fetchval(sql, *args)` | scalar |
| INSERT / UPDATE / DELETE (no return) | `pool.execute(sql, *args)` | `str` (status tag) |

### Optional: `db/queries.py`

If multiple tools share the same SQL fragment — for example, both `get_revenue_timeseries` and `detect_anomaly` aggregate `store.orders` by date — extract the shared query into `db/queries.py` as a named string constant. This file is only created if at least two tools share identical or near-identical SQL to avoid premature abstraction.

---

## Phase 5 — Config Updates

### Goal

Add PostgreSQL connection settings to `config.py` so every part of the codebase reads credentials from one place.

### File to edit: `config.py`

The current `Settings` class has `postgres_url: Optional[str] = None`. Replace it with the following block (add after the existing `checkpoint_backend` line):

```python
# PostgreSQL connection
postgres_host: str = "localhost"
postgres_port: int = 5432
postgres_db: str = "ops_agent"
postgres_user: str = ""
postgres_password: str = ""
database_url: str = ""  # postgresql+asyncpg://user:password@host:port/db
```

Also add a `@model_validator(mode='after')` that auto-builds `database_url` from the individual fields if `database_url` is not set in `.env`:

```python
from pydantic import model_validator

@model_validator(mode='after')
def build_database_url(self) -> 'Settings':
    if not self.database_url and self.postgres_user and self.postgres_password:
        self.database_url = (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
    return self
```

**Usage across the codebase:**
- `db/connection.py`: `await init_pool(dsn=settings.database_url)`
- `agent/graph.py`: `await AsyncPostgresSaver.from_conn_string(settings.database_url)`

Remove the old `postgres_url` field entirely — `database_url` replaces it.

---

## Phase 6 — Tool Rewrites (read tools)

### Goal

Replace every hardcoded return dict in the four read-only tool files with real `asyncpg` queries. Each tool becomes `async def`, imports `get_pool` from `db.connection`, and returns a dict built from `asyncpg.Record` objects.

### `tools/analytics.py`

#### `get_revenue_timeseries(date: str, granularity: str = "hourly") -> dict`

`granularity` must be validated against an allowlist before being used in SQL. **Never interpolate `granularity` directly into the query string** — this would be a SQL injection vector. Use a mapping dict:

```python
GRANULARITY_MAP = {"hourly": "hour", "daily": "day"}

async def get_revenue_timeseries(date: str, granularity: str = "hourly") -> dict:
    trunc_unit = GRANULARITY_MAP.get(granularity)
    if trunc_unit is None:
        raise ValueError(f"granularity must be one of {list(GRANULARITY_MAP)}")
    pool = get_pool()
    # DATE_TRUNC unit cannot be parameterised in PostgreSQL — use the validated mapping value
    sql = f"""
        SELECT
            DATE_TRUNC('{trunc_unit}', created_at AT TIME ZONE 'UTC') AS bucket,
            SUM(total_amount) AS revenue
        FROM store.orders
        WHERE DATE(created_at AT TIME ZONE 'UTC') = $1::date
          AND status = 'completed'
        GROUP BY bucket
        ORDER BY bucket;
    """
    rows = await pool.fetch(sql, date)
    total = sum(float(r["revenue"]) for r in rows)
    return {
        "date": date,
        "granularity": granularity,
        "total": total,
        "data_points": [
            {"time": r["bucket"].isoformat(), "revenue": float(r["revenue"])}
            for r in rows
        ],
    }
```

#### `get_order_volume(date: str) -> dict`

```sql
SELECT
    DATE_TRUNC('hour', o.created_at AT TIME ZONE 'UTC') AS hour,
    COUNT(o.order_id) AS orders,
    AVG(o.total_amount) AS avg_value
FROM store.orders o
WHERE DATE(o.created_at AT TIME ZONE 'UTC') = $1::date
GROUP BY hour
ORDER BY hour;
```

Return:
```python
{
    "date": date,
    "total_orders": sum(int(r["orders"]) for r in rows),
    "avg_order_value": float(rows[0]["avg_value"]) if rows else 0.0,
    "hourly_breakdown": [
        {"hour": r["hour"].isoformat(), "orders": int(r["orders"]), "avg_value": float(r["avg_value"] or 0)}
        for r in rows
    ],
}
```

#### `get_revenue_by_product(date: str, top_n: int = 5) -> dict`

```sql
SELECT
    p.product_id,
    p.name,
    SUM(oi.subtotal) AS revenue,
    SUM(oi.quantity) AS units_sold
FROM store.order_items oi
JOIN store.orders o ON o.order_id = oi.order_id
JOIN store.products p ON p.product_id = oi.product_id
WHERE DATE(o.created_at AT TIME ZONE 'UTC') = $1::date
  AND o.status = 'completed'
GROUP BY p.product_id, p.name
ORDER BY revenue DESC
LIMIT $2;
```

`pool.fetch(sql, date, top_n)` — pass `top_n` as the second positional parameter (`$2`).

#### `get_revenue_by_region(date: str) -> dict`

```sql
SELECT
    c.region,
    SUM(o.total_amount) AS revenue,
    COUNT(o.order_id) AS orders
FROM store.orders o
JOIN store.customers c ON c.customer_id = o.customer_id
WHERE DATE(o.created_at AT TIME ZONE 'UTC') = $1::date
  AND o.status = 'completed'
GROUP BY c.region
ORDER BY revenue DESC;
```

#### `detect_anomaly(date: str) -> dict`

Two sequential queries — both use `pool.fetchrow(...)`:

**Query 1 — today's totals:**
```sql
SELECT
    SUM(total_amount) AS today_revenue,
    COUNT(*) AS today_orders
FROM store.orders
WHERE DATE(created_at AT TIME ZONE 'UTC') = $1::date
  AND status = 'completed';
```

**Query 2 — 7-day rolling average (excluding today):**
```sql
SELECT
    AVG(daily_total) AS avg_revenue,
    AVG(daily_orders) AS avg_orders
FROM (
    SELECT
        DATE(created_at AT TIME ZONE 'UTC') AS d,
        SUM(total_amount) AS daily_total,
        COUNT(*) AS daily_orders
    FROM store.orders
    WHERE created_at AT TIME ZONE 'UTC' >= ($1::date - INTERVAL '7 days')
      AND DATE(created_at AT TIME ZONE 'UTC') < $1::date
      AND status = 'completed'
    GROUP BY d
) sub;
```

**Anomaly logic (Python, after both queries):**
```python
today_rev = float(today_row["today_revenue"] or 0)
avg_rev = float(avg_row["avg_revenue"] or 0)
is_anomaly = avg_rev > 0 and today_rev < avg_rev * 0.7
pct_deviation = round(((today_rev - avg_rev) / avg_rev) * 100, 1) if avg_rev > 0 else 0.0
```

---

### `tools/inventory.py`

#### `get_stock_levels(product_ids: list[str] | None = None) -> dict`

`product_ids` arrives as a list of strings (e.g. `["P001", "P002"]` in legacy stubs, UUID strings after DB integration). Convert to a list of `uuid.UUID` objects before passing to `asyncpg`. If `product_ids` is `None` or empty, pass `None` as `$1` — the `IS NULL` branch in the SQL returns all products.

```sql
SELECT
    p.product_id,
    p.name,
    i.stock_qty,
    i.reorder_threshold,
    i.status
FROM store.inventory i
JOIN store.products p ON p.product_id = i.product_id
WHERE ($1::uuid[] IS NULL OR p.product_id = ANY($1::uuid[]))
  AND p.is_active = TRUE;
```

**Important:** `asyncpg` requires passing a Python `list[uuid.UUID]` for `uuid[]` parameters. Convert with:
```python
import uuid
uuids = [uuid.UUID(pid) for pid in product_ids] if product_ids else None
rows = await pool.fetch(sql, uuids)
```

#### `get_stockout_events(date: str) -> dict`

```sql
SELECT
    ie.product_id,
    p.name,
    ie.created_at AS stockout_time,
    EXISTS (
        SELECT 1
        FROM store.campaign_products cp
        JOIN store.campaigns c ON c.campaign_id = cp.campaign_id
        WHERE cp.product_id = ie.product_id
          AND c.status = 'active'
    ) AS active_campaign
FROM store.inventory_events ie
JOIN store.products p ON p.product_id = ie.product_id
WHERE ie.event_type = 'stockout'
  AND DATE(ie.created_at AT TIME ZONE 'UTC') = $1::date;
```

#### `get_restock_recommendations(threshold_multiplier: float = 1.0) -> dict`

```sql
SELECT
    p.product_id,
    p.name,
    i.stock_qty,
    i.reorder_threshold,
    CEIL(i.reorder_threshold * $1 * 2) AS recommended_qty
FROM store.inventory i
JOIN store.products p ON p.product_id = i.product_id
WHERE i.stock_qty <= i.reorder_threshold * $1
  AND p.is_active = TRUE
ORDER BY i.stock_qty ASC;
```

Pass `threshold_multiplier` as `$1`. The `recommended_qty` formula (`threshold * multiplier * 2`) can be adjusted — the Python side can override or post-process the value.

---

### `tools/crm.py`

#### `get_complaint_volume(date: str) -> dict`

Two queries — today's breakdown and yesterday's total for `pct_change_vs_prior_day`:

**Today's count by category:**
```sql
SELECT category, COUNT(*) AS count
FROM store.complaints
WHERE type = 'complaint'
  AND DATE(created_at AT TIME ZONE 'UTC') = $1::date
GROUP BY category
ORDER BY count DESC;
```

**Prior day total (scalar):**
```sql
SELECT COUNT(*)
FROM store.complaints
WHERE type = 'complaint'
  AND DATE(created_at AT TIME ZONE 'UTC') = $1::date - 1;
```

Use `pool.fetch(today_sql, date)` and `pool.fetchval(prior_sql, date)`. Compute `pct_change` in Python.

#### `get_review_sentiment(date: str) -> dict`

```sql
SELECT
    AVG(rating) AS avg_rating,
    sentiment,
    COUNT(*) AS count
FROM store.complaints
WHERE type = 'review'
  AND DATE(created_at AT TIME ZONE 'UTC') = $1::date
GROUP BY sentiment;
```

Return a dict with `avg_rating` (overall, computed in Python from all rows) and a `breakdown` list with one entry per sentiment bucket.

#### `get_common_issues(date: str, top_n: int = 5) -> dict`

```sql
SELECT
    COALESCE(category, 'review') AS issue,
    COUNT(*) AS frequency,
    MIN(description) AS representative_quote
FROM store.complaints
WHERE DATE(created_at AT TIME ZONE 'UTC') = $1::date
GROUP BY COALESCE(category, 'review')
ORDER BY frequency DESC
LIMIT $2;
```

---

### `tools/campaigns.py`

#### `get_campaign_performance(date: str) -> dict`

```sql
SELECT
    c.campaign_id,
    c.external_id,
    c.name,
    c.status,
    c.channel,
    cm.spend,
    cm.impressions,
    cm.clicks,
    cm.conversions,
    cm.revenue,
    cm.roas
FROM store.campaign_metrics cm
JOIN store.campaigns c ON c.campaign_id = cm.campaign_id
WHERE cm.date = $1::date;
```

#### `get_channel_breakdown(date: str) -> dict`

```sql
SELECT
    c.channel,
    SUM(cm.spend) AS spend,
    SUM(cm.revenue) AS revenue,
    SUM(cm.revenue) / NULLIF(SUM(cm.spend), 0) AS roas
FROM store.campaign_metrics cm
JOIN store.campaigns c ON c.campaign_id = cm.campaign_id
WHERE cm.date = $1::date
GROUP BY c.channel;
```

`NULLIF(SUM(cm.spend), 0)` prevents division-by-zero when a channel has zero spend. The result may be `None` in Python — handle with `float(row["roas"] or 0)`.

#### `get_paused_campaigns(date: str) -> dict`

```sql
SELECT
    campaign_id,
    external_id,
    name,
    paused_at,
    paused_reason,
    spend_to_date AS budget_used
FROM store.campaigns
WHERE status = 'paused'
  AND DATE(paused_at AT TIME ZONE 'UTC') = $1::date;
```

#### `get_promotion_schedule() -> dict`

```sql
SELECT
    promo_id,
    product_ids,
    discount_pct,
    starts_at,
    expires_at,
    status
FROM store.promotions
WHERE status = 'active' OR starts_at > NOW()
ORDER BY starts_at;
```

No parameters — call `pool.fetch(sql)` with no positional args.

---

## Phase 7 — Tool Rewrites (write/action tools)

### Goal

Replace hardcoded success responses in `tools/actions.py` with real INSERT and UPDATE statements. All action tools are also converted to `async def`.

### Session ID threading via `ContextVar`

Action tools need to record `session_id` in `store.restock_orders`, `store.promotions`, and `store.support_tickets` as `created_by_session_id`. The tool signatures must not change (no new `session_id` parameter). Use a `contextvars.ContextVar` instead:

**In `tools/actions.py` (at module level):**
```python
import contextvars
current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    'current_session_id', default=''
)
```

**In the LangGraph node that invokes actions (`agent/action_executor.py`):**
```python
from tools.actions import current_session_id

token = current_session_id.set(state["session_id"])
try:
    result = await tool.ainvoke(...)
finally:
    current_session_id.reset(token)
```

Each action tool reads the var without needing it as a parameter:
```python
session_id = current_session_id.get()
```

---

### `restock_product(product_id: str, quantity: int) -> dict`

After DB integration, `product_id` will be a UUID string. The tool should handle both legacy SKU strings (e.g. `"P001"`) and UUID strings gracefully. If the value is not a valid UUID, look up the product by `sku`:

```sql
SELECT product_id FROM store.products WHERE sku = $1 LIMIT 1;
```

**INSERT:**
```sql
INSERT INTO store.restock_orders
    (product_id, quantity, status, estimated_arrival, created_by_session_id)
VALUES
    ($1::uuid, $2, 'pending', '2-3 business days', $3::uuid)
RETURNING id;
```

Parameters: `(resolved_product_uuid, quantity, current_session_id.get() or None)`

Return:
```python
{
    "status": "success",
    "restock_order_id": str(row["id"]),
    "product_id": product_id,
    "quantity": quantity,
    "estimated_arrival": "2-3 business days",
}
```

---

### `apply_discount(product_ids: list[str], discount_pct: float, duration_hours: int) -> dict`

Generate `promo_id` in Python before the INSERT:

```python
from datetime import datetime
promo_id = f"PROMO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
```

**INSERT:**
```sql
INSERT INTO store.promotions
    (promo_id, product_ids, discount_pct, duration_hours, starts_at, expires_at, status, created_by_session_id)
VALUES
    ($1, $2::jsonb, $3, $4, NOW(), NOW() + ($4 * INTERVAL '1 hour'), 'active', $5::uuid)
RETURNING id, promo_id, expires_at;
```

Parameters: `(promo_id, json.dumps(product_ids), discount_pct, duration_hours, session_id)`

Note: `$4 * INTERVAL '1 hour'` requires casting `$4` as an integer in PostgreSQL. If `asyncpg` rejects this, use a Python `timedelta` instead:

```python
from datetime import timedelta
expires_at = datetime.utcnow() + timedelta(hours=duration_hours)
# Then use a plain TIMESTAMPTZ parameter instead of the interval expression
```

---

### `pause_campaign(campaign_id: str, reason: str) -> dict`

`campaign_id` in the tool interface is the `external_id` string (e.g. `"CAMP_042"`), **not** the UUID primary key. The UPDATE uses `WHERE external_id = $1`:

```sql
UPDATE store.campaigns
SET
    status       = 'paused',
    paused_at    = NOW(),
    paused_reason = $2,
    updated_at   = NOW()
WHERE external_id = $1
RETURNING campaign_id, status, paused_at;
```

Parameters: `(campaign_id, reason)` — `campaign_id` is passed as a plain string, not a UUID.

If `fetchrow` returns `None`, the external_id was not found — raise a `ValueError`:
```python
row = await pool.fetchrow(sql, campaign_id, reason)
if row is None:
    raise ValueError(f"Campaign '{campaign_id}' not found")
```

---

### `create_support_ticket(issue_description: str, priority: str = "medium") -> dict`

Generate `ticket_id` in Python before the INSERT:

```python
ticket_id = f"TKT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
```

**INSERT:**
```sql
INSERT INTO store.support_tickets
    (ticket_id, issue_description, priority, status, created_by_session_id)
VALUES
    ($1, $2, $3, 'open', $4::uuid)
RETURNING id, ticket_id, created_at;
```

Parameters: `(ticket_id, issue_description, priority, session_id)`

Validate `priority` against the CHECK constraint values before inserting:
```python
VALID_PRIORITIES = {"low", "medium", "high", "critical"}
if priority not in VALID_PRIORITIES:
    raise ValueError(f"priority must be one of {VALID_PRIORITIES}")
```

---

## Phase 8 — Ops Agent Table Writes

### Goal

Wire the ops agent internal tables (`public` schema) so the agent persists its own reasoning and action history to PostgreSQL. These writes happen in the LangGraph node functions, not in the tool layer. All nodes use the same `asyncpg` pool from `db.connection.get_pool()`.

### Write responsibilities per node

| Node | File | Table | Operation | Trigger |
|---|---|---|---|---|
| `orchestrator` | `agent/orchestrator.py` | `public.sessions` | INSERT new session row | First invocation (when `session_id` not yet in DB) |
| `sales_agent` | `agent/specialists/sales.py` | `public.specialist_findings` | INSERT one row | After specialist completes |
| `inventory_agent` | `agent/specialists/inventory.py` | `public.specialist_findings` | INSERT one row | After specialist completes |
| `marketing_agent` | `agent/specialists/marketing.py` | `public.specialist_findings` | INSERT one row | After specialist completes |
| `support_agent` | `agent/specialists/support.py` | `public.specialist_findings` | INSERT one row | After specialist completes |
| `aggregator` | `agent/aggregator.py` | `public.root_causes` | INSERT one row per `RootCause` | After aggregation completes |
| `hitl_checkpoint` | `agent/hitl.py` | `public.hitl_requests` | INSERT pending row; UPDATE to approved/rejected/modified | On interrupt; on resume |
| `action_executor` | `agent/action_executor.py` | `public.executed_actions` | INSERT one row per action | After each action tool call |
| `memory_writer` | `memory/long_term.py` | `public.incidents` | INSERT one row | After Qdrant write |
| `output_formatter` | `agent/output_formatter.py` | `public.sessions` | UPDATE `status`, `final_response`, `completed_at` | On graph completion |

### SQL for each operation

**`orchestrator` — INSERT session:**
```sql
INSERT INTO sessions (session_id, user_query, intent, status, active_specialists, retry_count)
VALUES ($1::uuid, $2, $3, 'running', $4::jsonb, 0)
ON CONFLICT (session_id) DO NOTHING;
```
`active_specialists` is serialised with `json.dumps(state["active_specialists"])`.

**Each specialist — INSERT finding:**
```sql
INSERT INTO specialist_findings
    (session_id, domain, signals, confidence, raw_tool_outputs, sub_question_answered)
VALUES ($1::uuid, $2, $3::jsonb, $4, $5::jsonb, $6)
ON CONFLICT (session_id, domain) DO UPDATE
    SET signals = EXCLUDED.signals,
        confidence = EXCLUDED.confidence,
        raw_tool_outputs = EXCLUDED.raw_tool_outputs;
```
The `ON CONFLICT DO UPDATE` handles the case where a specialist is re-invoked after a reflection retry.

**`aggregator` — INSERT root causes:**
```sql
INSERT INTO root_causes (session_id, description, confidence, supporting_domains, evidence, rank)
VALUES ($1::uuid, $2, $3, $4::jsonb, $5::jsonb, $6);
```
Call once per `RootCause` in `state["root_causes"]`. Set `rank` to the list index + 1.

**`hitl_checkpoint` — INSERT HITL request:**
```sql
INSERT INTO hitl_requests (session_id, status, proposed_actions)
VALUES ($1::uuid, 'pending', $2::jsonb)
ON CONFLICT (session_id) DO NOTHING;
```

**`hitl_checkpoint` — UPDATE on approval/rejection:**
```sql
UPDATE hitl_requests
SET status = $2, approved_actions = $3::jsonb, reviewer_note = $4, resolved_at = NOW()
WHERE session_id = $1::uuid;
```

**`action_executor` — INSERT executed action:**
```sql
INSERT INTO executed_actions
    (session_id, hitl_request_id, action_type, parameters, status, api_response, executed_at)
VALUES ($1::uuid, $2::uuid, $3, $4::jsonb, $5, $6::jsonb, NOW());
```

**`memory_writer` — INSERT incident:**
```sql
INSERT INTO incidents
    (session_id, query, intent, root_causes, actions_proposed, actions_approved, actions_executed, outcome_summary, embedding_text, qdrant_point_id)
VALUES ($1::uuid, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7::jsonb, $8, $9, $10::uuid);
```

**`output_formatter` — UPDATE session on completion:**
```sql
UPDATE sessions
SET status = $2, final_response = $3::jsonb, completed_at = NOW()
WHERE session_id = $1::uuid;
```

---

## Phase 9 — LangGraph Checkpoint Integration

### Goal

Replace `MemorySaver` with `AsyncPostgresSaver` so graph state survives process restarts and HITL pauses work correctly when the user calls `/hitl/approve/{session_id}` in a new process instance.

### Package to install

```
langgraph-checkpoint-postgres
```

Add to `requirements.txt`.

### Change in `agent/graph.py`

**Current (to be replaced):**
```python
from langgraph.checkpoint.memory import MemorySaver
checkpointer = MemorySaver()
```

**New:**
```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from config import settings

# Called once at startup — see Phase 10 for where this lives
async def create_checkpointer() -> AsyncPostgresSaver:
    checkpointer = await AsyncPostgresSaver.from_conn_string(settings.database_url)
    return checkpointer
```

`AsyncPostgresSaver.from_conn_string(dsn)` auto-creates the three LangGraph checkpoint tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) in the `public` schema on first call. No migration file is needed for these.

### Config-driven checkpointer selection

`config.py` already has `checkpoint_backend: str = "memory"`. In `agent/graph.py`, the graph builder reads this setting:

```python
from config import settings

async def build_graph(checkpointer=None):
    if checkpointer is None:
        if settings.checkpoint_backend == "postgres":
            checkpointer = await AsyncPostgresSaver.from_conn_string(settings.database_url)
        else:
            from langgraph.checkpoint.memory import MemorySaver
            checkpointer = MemorySaver()
    # ... rest of graph compilation
    return graph.compile(checkpointer=checkpointer)
```

This allows local development without Docker by setting `checkpoint_backend=memory` in `.env`.

### Thread ID = Session ID

LangGraph uses `config={"configurable": {"thread_id": session_id}}` when invoking the graph. The `session_id` from `OpsAgentState` must be passed as `thread_id` so the `public.sessions` row and the LangGraph checkpoint rows are correlated by the same UUID.

---

## Phase 10 — Startup Wiring (`main.py`)

### Goal

Initialise and tear down the DB pool as part of the application lifecycle, in the correct order.

### Changes to `main.py`

**Imports to add:**
```python
from db import connection as db_connection
from config import settings
```

**Startup sequence (ordered):**

```python
async def startup():
    # 1. Load settings (already done by pydantic-settings at import time)

    # 2. Initialise asyncpg pool — must happen before any tool is called
    await db_connection.init_pool(dsn=settings.database_url)

    # 3. Seed Qdrant long-term memory (existing _seed_memory() call — keep as-is)
    await _seed_memory()

    # 4. Initialise LangGraph checkpointer if postgres backend is configured
    if settings.checkpoint_backend == "postgres":
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        checkpointer = await AsyncPostgresSaver.from_conn_string(settings.database_url)
    else:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()

    # 5. Build and compile the LangGraph graph with the chosen checkpointer
    graph = await build_graph(checkpointer=checkpointer)

    # 6. Start the HITL FastAPI server (existing uvicorn call — keep as-is)
    # 7. Start the MCP server or Gradio UI (existing calls — keep as-is)
```

**Shutdown sequence:**
```python
async def shutdown():
    await db_connection.close_pool()
```

Wire `startup` and `shutdown` into the application lifecycle. If `main.py` uses `asyncio.run(main())`, call both inside the same coroutine:

```python
async def main():
    await startup()
    try:
        # run servers...
        pass
    finally:
        await shutdown()
```

### Per-request session ID context

Before each graph invocation (i.e. every time the MCP `diagnose`, `fix`, or `summarize` tool is called), set the `current_session_id` context variable:

```python
from tools.actions import current_session_id

async def invoke_graph(user_query: str, session_id: str, intent: str):
    token = current_session_id.set(session_id)
    try:
        result = await graph.ainvoke(
            {"session_id": session_id, "user_query": user_query, "intent": intent},
            config={"configurable": {"thread_id": session_id}},
        )
    finally:
        current_session_id.reset(token)
    return result
```

---

## Phase 11 — Testing

### Goal

Verify the DB integration works end-to-end before wiring into the full agent graph. Each test step below is independently executable.

### Test 1 — Schema smoke test

Apply both migration files to a fresh `ops_agent` database and verify all tables exist:

```bash
psql postgresql://ops_user:ops_password@localhost:5432/ops_agent -f db/migrations/001_public_schema.sql
psql postgresql://ops_user:ops_password@localhost:5432/ops_agent -f db/migrations/002_store_schema.sql
```

In `psql`, confirm:
```sql
\dt public.*
-- Expected: sessions, specialist_findings, root_causes, hitl_requests, executed_actions, incidents

\dt store.*
-- Expected: 14 tables (products, inventory, inventory_events, restock_orders, customers,
--           orders, order_items, price_history, promotions, campaigns, campaign_metrics,
--           campaign_products, complaints, support_tickets)
```

Pass condition: exactly 6 tables in `public.*`, exactly 14 tables in `store.*`.

### Test 2 — Seed test

```bash
psql postgresql://ops_user:ops_password@localhost:5432/ops_agent -f db/seed.sql
```

Spot-check row counts in `psql`:
```sql
SELECT COUNT(*) FROM store.products;          -- must be 5
SELECT COUNT(*) FROM store.customers;         -- must be >= 10
SELECT COUNT(*) FROM store.orders;            -- must be ~200
SELECT COUNT(*) FROM store.order_items;       -- must be ~400
SELECT COUNT(*) FROM store.campaigns;         -- must be 2
SELECT COUNT(*) FROM store.campaign_metrics;  -- must be 14
SELECT COUNT(*) FROM store.complaints;        -- must be ~30
SELECT COUNT(*) FROM store.inventory_events WHERE event_type = 'stockout';  -- must be >= 1
```

Also verify the yesterday drop:
```sql
SELECT DATE(created_at AT TIME ZONE 'UTC') AS d, COUNT(*) AS orders
FROM store.orders
WHERE created_at >= NOW() - INTERVAL '5 days'
GROUP BY d ORDER BY d;
-- Yesterday (CURRENT_DATE - 1) should show significantly fewer orders than surrounding days
```

### Test 3 — Tool unit tests

**File to create:** `eval/test_tools.py`

Write a standalone async test module (using `pytest-asyncio`) that:
1. Calls `db.connection.init_pool(settings.database_url)` once in a session-scoped fixture
2. For each of the 17 tools, defines an `async def test_<tool_name>()` function that:
   - Calls the tool with valid parameters pointing to the seeded data (e.g. `date = str(date.today() - timedelta(days=1))`)
   - Asserts the return dict has all expected top-level keys
   - Asserts at least one list in the response is non-empty (data came from DB, not a hardcoded empty list)
   - For numeric fields, asserts the value is `> 0` (not a hardcoded zero)

**Tool coverage checklist for `test_tools.py`:**
- `get_revenue_timeseries` — assert `"data_points"` is non-empty, `"total" > 0`
- `get_order_volume` — assert `"total_orders" > 0`
- `get_revenue_by_product` — assert `"products"` list has at least 1 item, first item has `"revenue" > 0`
- `get_revenue_by_region` — assert `"regions"` has at least 1 item
- `detect_anomaly` — assert `"is_anomaly"` is `True` for yesterday (the seeded drop), `"pct_deviation" < -30`
- `get_stock_levels` — assert all 5 products are returned when no filter is passed
- `get_stockout_events` — assert at least 1 event for yesterday
- `get_restock_recommendations` — assert at least 1 product recommended (USB-C Hub and Wireless Mouse are below threshold)
- `get_complaint_volume` — assert `"total" > 0` for the seeded complaint period
- `get_review_sentiment` — assert `"avg_rating"` is between 1 and 5
- `get_common_issues` — assert list has items
- `get_campaign_performance` — assert 2 campaigns returned
- `get_channel_breakdown` — assert at least 1 channel in result
- `get_paused_campaigns` — assert `CAMP_039` appears (seeded as paused)
- `get_promotion_schedule` — assert result is a list (may be empty if no active promotions seeded)

### Test 4 — Action tool tests

For each action tool, call it and then query the DB directly to verify the write happened:

**`restock_product`:**
```python
result = await restock_product.ainvoke({"product_id": "P001", "quantity": 50})
assert result["status"] == "success"
row = await pool.fetchrow("SELECT * FROM store.restock_orders WHERE id = $1::uuid", uuid.UUID(result["restock_order_id"]))
assert row is not None
assert int(row["quantity"]) == 50
```

**`apply_discount`:**
After calling the tool, verify a row exists in `store.promotions` with the correct `discount_pct` and `status = 'active'`.

**`pause_campaign`:**
After calling the tool with `campaign_id="CAMP_042"`, verify `status = 'paused'` and `paused_at IS NOT NULL` in `store.campaigns WHERE external_id = 'CAMP_042'`.

**`create_support_ticket`:**
After calling the tool, verify a row exists in `store.support_tickets` with the correct `priority` and `status = 'open'`.

For all action tools, also verify that `created_by_session_id` is populated (non-null) by setting `current_session_id` before the call in the test:
```python
from tools.actions import current_session_id
token = current_session_id.set("test-session-id-0000-000000000000")
try:
    result = await restock_product.ainvoke({"product_id": "P001", "quantity": 10})
finally:
    current_session_id.reset(token)
```

### Test 5 — Checkpoint test

1. Set `checkpoint_backend=postgres` in `.env`
2. Run the graph with `intent="fix"` so it reaches the HITL interrupt
3. Verify the process can be stopped and restarted
4. After restart, call `POST /hitl/approve/{session_id}` via the FastAPI HITL endpoint
5. Verify the graph resumes from the HITL interrupt (not from the beginning) and `action_executor` runs
6. Confirm LangGraph checkpoint tables have rows: `SELECT COUNT(*) FROM checkpoints WHERE thread_id = '<session_id>'`

### Test 6 — End-to-end test

Run the full "Why did sales drop yesterday?" scenario against the seeded database:

```python
result = await invoke_graph(
    user_query="Why did sales drop yesterday?",
    session_id=str(uuid.uuid4()),
    intent="diagnose",
)
```

After the run completes, verify the ops agent wrote to all expected tables:

```sql
-- One session row
SELECT * FROM sessions WHERE session_id = '<session_id>';
-- Must have status = 'completed', final_response IS NOT NULL

-- Four specialist findings (one per domain)
SELECT domain, confidence FROM specialist_findings WHERE session_id = '<session_id>';
-- Must return exactly 4 rows: sales, inventory, marketing, support

-- At least one root cause
SELECT description, confidence, rank FROM root_causes WHERE session_id = '<session_id>' ORDER BY rank;
-- Must return >= 1 row with confidence >= 0.5

-- One incident record
SELECT incident_id, outcome_summary FROM incidents WHERE session_id = '<session_id>';
-- Must return 1 row with non-empty outcome_summary
```

---

## File Change Summary

### Files created or modified across all phases

| File | Action | Phase |
|---|---|---|
| `docker-compose.yml` | CREATE | 1 |
| `.env.example` | UPDATE | 1 |
| `db/migrations/001_public_schema.sql` | CREATE | 2 |
| `db/migrations/002_store_schema.sql` | CREATE | 2 |
| `db/migrate.py` | CREATE | 2 |
| `db/seed.sql` | CREATE | 3 |
| `db/seed.py` | CREATE | 3 |
| `db/__init__.py` | CREATE | 4 |
| `db/connection.py` | CREATE | 4 |
| `db/queries.py` | CREATE (if needed) | 4 |
| `config.py` | UPDATE | 5 |
| `tools/analytics.py` | REWRITE | 6 |
| `tools/inventory.py` | REWRITE | 6 |
| `tools/crm.py` | REWRITE | 6 |
| `tools/campaigns.py` | REWRITE | 6 |
| `tools/actions.py` | REWRITE | 7 |
| `agent/orchestrator.py` | UPDATE | 8 |
| `agent/specialists/sales.py` | UPDATE | 8 |
| `agent/specialists/inventory.py` | UPDATE | 8 |
| `agent/specialists/marketing.py` | UPDATE | 8 |
| `agent/specialists/support.py` | UPDATE | 8 |
| `agent/aggregator.py` | UPDATE | 8 |
| `agent/hitl.py` | UPDATE | 8 |
| `agent/action_executor.py` | UPDATE | 8 |
| `memory/long_term.py` | UPDATE | 8 |
| `agent/output_formatter.py` | UPDATE | 8 |
| `agent/graph.py` | UPDATE | 9 |
| `main.py` | UPDATE | 10 |
| `eval/test_tools.py` | CREATE | 11 |

### New packages to add to `requirements.txt`

```
asyncpg
langgraph-checkpoint-postgres
pytest-asyncio
```

# Store Business Data Schema

These are the business and operational data tables for the e-commerce store, residing in the `store` PostgreSQL schema. Agent tools (`tools/analytics.py`, `tools/inventory.py`, `tools/crm.py`, `tools/campaigns.py`, `tools/actions.py`) query and write to these tables directly. The ops agent's internal state tables (`sessions`, `specialist_findings`, `root_causes`, `hitl_requests`, `executed_actions`, `incidents`) live in the `public` schema and are documented in `PROJECT_PLAN.md`.

---

## Schema Separation

The database uses two schemas with distinct responsibilities:

- **`public` schema** — Ops agent internals: `sessions`, `specialist_findings`, `root_causes`, `hitl_requests`, `executed_actions`, `incidents`, plus LangGraph checkpoint tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_migrations`). These tables track the agent's reasoning, decisions, and execution history.
- **`store` schema** — All business data: orders, products, inventory, customers, campaigns, complaints (including product reviews), etc. These are the tables the store actually operates from.

Cross-schema references exist where store action tables (e.g. `store.restock_orders`, `store.promotions`, `store.support_tickets`) need to record which agent session triggered them. These are implemented as **soft references** — a plain `UUID` column named `created_by_session_id` that stores the `public.sessions.session_id` value, but without a `FOREIGN KEY` constraint. This avoids cross-schema FK complexity and allows the store schema to remain independently deployable.

---

## Table Overview

| Table | Primary Key | Purpose | Queried by tools |
|---|---|---|---|
| `store.products` | `product_id` UUID | Product catalog: SKU, name, category, pricing | `get_revenue_by_product`, `get_stock_levels`, `get_restock_recommendations` |
| `store.inventory` | `product_id` UUID | Current stock level per product (one row per product, upserted) | `get_stock_levels`, `get_stockout_events`, `get_restock_recommendations` |
| `store.inventory_events` | `id` UUID | Append-only log of every stock change; used to reconstruct stockout times | `get_stockout_events` |
| `store.restock_orders` | `id` UUID | Restock orders placed by the action executor | `restock_product` (writes) |
| `store.customers` | `customer_id` UUID | Customer profiles including region for geographic breakdowns | `get_revenue_by_region` |
| `store.orders` | `order_id` UUID | Order header: one row per customer order | `get_revenue_timeseries`, `get_order_volume`, `get_revenue_by_product`, `get_revenue_by_region`, `detect_anomaly` |
| `store.order_items` | `id` UUID | Line items within an order | `get_revenue_by_product`, `get_order_volume` |
| `store.price_history` | `id` UUID | Historical product prices; current price = row where `effective_to IS NULL` | (internal pricing reference) |
| `store.promotions` | `id` UUID | Discount promotions applied by action executor or manually | `get_promotion_schedule`, `apply_discount` (writes) |
| `store.campaigns` | `campaign_id` UUID | Marketing campaigns across channels | `get_campaign_performance`, `get_paused_campaigns`, `pause_campaign` (writes) |
| `store.campaign_metrics` | `id` UUID | Daily performance metrics per campaign (one row per campaign + date) | `get_campaign_performance`, `get_channel_breakdown` |
| `store.campaign_products` | `(campaign_id, product_id)` | Many-to-many: which products a campaign targets/promotes | `get_stockout_events` (active campaign flag) |
| `store.complaints` | `id` UUID | Customer complaints and product reviews (unified table, distinguished by `type`) | `get_complaint_volume`, `get_review_sentiment`, `get_common_issues` |
| `store.support_tickets` | `id` UUID | Support tickets created by action executor or manually | `create_support_ticket` (writes) |

---

## Full DDL

```sql
-- Enable pgcrypto for gen_random_uuid(). Idempotent; safe to run even if already enabled by ops DDL.
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE SCHEMA IF NOT EXISTS store;

-- =============================================================================
-- 1. store.products
-- Product catalog. One row per sellable product.
-- =============================================================================
CREATE TABLE store.products (
    product_id   UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    sku          VARCHAR(50)    UNIQUE NOT NULL,
    name         VARCHAR(255)   NOT NULL,
    category     VARCHAR(100),
    description  TEXT,
    unit_cost    NUMERIC(12,2),                        -- cost price paid to supplier
    base_price   NUMERIC(12,2)  NOT NULL,              -- standard selling price
    is_active    BOOLEAN        NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 2. store.inventory
-- Current stock level per product. One row per product (upserted, not appended).
-- Stock changes are also logged to store.inventory_events for audit purposes.
-- =============================================================================
CREATE TABLE store.inventory (
    product_id         UUID         PRIMARY KEY REFERENCES store.products(product_id) ON DELETE CASCADE,
    stock_qty          INTEGER      NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),
    reorder_threshold  INTEGER      NOT NULL DEFAULT 10,
    status             VARCHAR(15)  NOT NULL DEFAULT 'ok'
                                    CHECK (status IN ('ok', 'low', 'out_of_stock')),
    last_updated       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 3. store.inventory_events
-- Append-only audit log of every stock change.
-- Used to reconstruct stockout times and estimate lost revenue.
-- event_type values:
--   'sale'       — stock reduced by a customer order
--   'restock'    — stock increased by a supplier delivery
--   'adjustment' — manual correction
--   'stockout'   — marker event when stock hits 0
--   'writeoff'   — damaged/expired stock removed
-- =============================================================================
CREATE TABLE store.inventory_events (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID         NOT NULL REFERENCES store.products(product_id) ON DELETE CASCADE,
    event_type      VARCHAR(20)  NOT NULL
                                 CHECK (event_type IN ('sale', 'restock', 'adjustment', 'stockout', 'writeoff')),
    quantity_delta  INTEGER      NOT NULL,   -- negative for sales/writeoffs, positive for restock/adjustment
    stock_after     INTEGER      NOT NULL,   -- snapshot of store.inventory.stock_qty after this event
    reference_id    UUID,                   -- optional: order_id (sale), restock_orders.id (restock); nullable
    notes           TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 4. store.restock_orders
-- Restock purchase orders placed by the action executor (tools/actions.py → restock_product).
-- created_by_session_id is a SOFT REFERENCE to public.sessions(session_id).
-- No FK constraint is used to avoid cross-schema FK complexity.
-- =============================================================================
CREATE TABLE store.restock_orders (
    id                     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id             UUID         NOT NULL REFERENCES store.products(product_id) ON DELETE RESTRICT,
    quantity               INTEGER      NOT NULL CHECK (quantity > 0),
    status                 VARCHAR(15)  NOT NULL DEFAULT 'pending'
                                        CHECK (status IN ('pending', 'confirmed', 'received', 'cancelled')),
    estimated_arrival      VARCHAR(100),                -- human-readable, e.g. "2-3 business days"
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    received_at            TIMESTAMPTZ,                 -- set when status transitions to 'received'
    created_by_session_id  UUID                         -- soft ref → public.sessions(session_id); no FK constraint
);

-- =============================================================================
-- 5. store.customers
-- Customer profiles. Region is used for revenue-by-region aggregations.
-- =============================================================================
CREATE TABLE store.customers (
    customer_id  UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    email        VARCHAR(255)  UNIQUE NOT NULL,
    name         VARCHAR(255)  NOT NULL,
    region       VARCHAR(100),                          -- e.g. 'North America', 'EMEA', 'APAC'
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 6. store.orders
-- Order header. One row per customer order.
-- total_amount is denormalised for fast aggregation; must stay in sync with order_items.subtotal.
-- =============================================================================
CREATE TABLE store.orders (
    order_id      UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id   UUID          NOT NULL REFERENCES store.customers(customer_id) ON DELETE RESTRICT,
    status        VARCHAR(20)   NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'completed', 'cancelled')),
    total_amount  NUMERIC(12,2) NOT NULL CHECK (total_amount >= 0),
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    completed_at  TIMESTAMPTZ                           -- set when status transitions to 'completed'
);

-- =============================================================================
-- 7. store.order_items
-- Line items within an order.
-- unit_price is a snapshot of the price at time of purchase (not the current base_price).
-- subtotal is a stored generated column: quantity * unit_price.
-- =============================================================================
CREATE TABLE store.order_items (
    id          UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    UUID           NOT NULL REFERENCES store.orders(order_id) ON DELETE CASCADE,
    product_id  UUID           NOT NULL REFERENCES store.products(product_id) ON DELETE RESTRICT,
    quantity    INTEGER        NOT NULL CHECK (quantity > 0),
    unit_price  NUMERIC(12,2)  NOT NULL,                -- snapshot of price at time of purchase
    subtotal    NUMERIC(12,2)  NOT NULL GENERATED ALWAYS AS (quantity * unit_price) STORED
);

-- =============================================================================
-- 8. store.price_history
-- Historical product prices. The currently active price is the row where effective_to IS NULL.
-- Application rule (not enforced by DDL): only one row per product may have effective_to IS NULL
-- at any given time. The application must set effective_to = NOW() on the previous row before
-- inserting a new active price row.
-- =============================================================================
CREATE TABLE store.price_history (
    id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID          NOT NULL REFERENCES store.products(product_id) ON DELETE CASCADE,
    price           NUMERIC(12,2) NOT NULL CHECK (price >= 0),
    effective_from  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    effective_to    TIMESTAMPTZ,                        -- NULL means currently active
    changed_by      VARCHAR(50)                         -- 'manual', 'promotion', 'system'
);

-- =============================================================================
-- 9. store.promotions
-- Discount promotions applied by apply_discount (tools/actions.py) or created manually.
-- product_ids stores an array of product_id UUID strings as a JSONB array.
-- created_by_session_id is a SOFT REFERENCE to public.sessions(session_id); no FK constraint.
-- =============================================================================
CREATE TABLE store.promotions (
    id                     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    promo_id               VARCHAR(50)  UNIQUE NOT NULL,  -- human-readable, e.g. 'PROMO-20250115143022'
    product_ids            JSONB        NOT NULL,          -- JSON array of product_id UUID strings
    discount_pct           FLOAT        NOT NULL CHECK (discount_pct > 0 AND discount_pct <= 100),
    duration_hours         INTEGER      NOT NULL,
    starts_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at             TIMESTAMPTZ  NOT NULL,
    status                 VARCHAR(10)  NOT NULL DEFAULT 'active'
                                        CHECK (status IN ('active', 'expired', 'cancelled')),
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_by_session_id  UUID                          -- soft ref → public.sessions(session_id); no FK constraint
);

-- =============================================================================
-- 10. store.campaigns
-- Marketing campaigns. Tools read status/paused_at/paused_reason.
-- pause_campaign (tools/actions.py) writes to status, paused_at, paused_reason.
-- external_id maps to campaign IDs used in existing tool stubs (e.g. 'CAMP_042').
-- =============================================================================
CREATE TABLE store.campaigns (
    campaign_id    UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id    VARCHAR(50)   UNIQUE,                 -- e.g. 'CAMP_042'; used by existing tool outputs
    name           VARCHAR(255)  NOT NULL,
    channel        VARCHAR(50)   NOT NULL
                                 CHECK (channel IN ('paid_search', 'social_ads', 'email', 'organic', 'display', 'affiliate')),
    status         VARCHAR(15)   NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active', 'paused', 'completed', 'cancelled')),
    budget         NUMERIC(12,2) NOT NULL,
    spend_to_date  NUMERIC(12,2) NOT NULL DEFAULT 0,
    start_date     DATE          NOT NULL,
    end_date       DATE,
    paused_at      TIMESTAMPTZ,                          -- set when status transitions to 'paused'
    paused_reason  TEXT,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 11. store.campaign_metrics
-- Daily performance metrics per campaign. One row per (campaign_id, date).
-- roas (Return on Ad Spend) is a plain FLOAT column written by the ETL process or
-- the tool itself as revenue / spend. It is NOT a generated column because PostgreSQL
-- generated columns cannot express conditional arithmetic (CASE WHEN spend = 0 THEN NULL).
-- Tools that need live roas compute it inline: revenue / NULLIF(spend, 0).
-- =============================================================================
CREATE TABLE store.campaign_metrics (
    id           UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id  UUID          NOT NULL REFERENCES store.campaigns(campaign_id) ON DELETE CASCADE,
    date         DATE          NOT NULL,
    spend        NUMERIC(12,2) NOT NULL DEFAULT 0,
    impressions  INTEGER       NOT NULL DEFAULT 0,
    clicks       INTEGER       NOT NULL DEFAULT 0,
    conversions  INTEGER       NOT NULL DEFAULT 0,
    revenue      NUMERIC(12,2) NOT NULL DEFAULT 0,
    roas         FLOAT,                                  -- written by ETL: revenue / spend (NULL when spend = 0)
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE (campaign_id, date)
);

-- =============================================================================
-- 12. store.campaign_products
-- Many-to-many join: which products a campaign is targeting or promoting.
-- Used by get_stockout_events to flag whether a stocked-out product has an active campaign.
-- =============================================================================
CREATE TABLE store.campaign_products (
    campaign_id  UUID  NOT NULL REFERENCES store.campaigns(campaign_id) ON DELETE CASCADE,
    product_id   UUID  NOT NULL REFERENCES store.products(product_id) ON DELETE CASCADE,
    PRIMARY KEY (campaign_id, product_id)
);

-- =============================================================================
-- 13. store.complaints
-- Unified table covering both customer complaints and product reviews.
-- Distinguish record type using the `type` column:
--   • When type = 'complaint': `category` and `description` are populated;
--     `rating` and `sentiment` are NULL.
--   • When type = 'review':   `rating`, `sentiment`, `product_id`, and `description`
--     (review body) are populated; `category` is NULL.
-- =============================================================================
CREATE TABLE store.complaints (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    type         VARCHAR(15)  NOT NULL DEFAULT 'complaint'
                              CHECK (type IN ('complaint', 'review')),
    customer_id  UUID         REFERENCES store.customers(customer_id) ON DELETE SET NULL,
    order_id     UUID         REFERENCES store.orders(order_id) ON DELETE SET NULL,
    product_id   UUID         REFERENCES store.products(product_id) ON DELETE SET NULL,  -- populated for reviews; optional for complaints
    -- Complaint-specific fields
    category     VARCHAR(50)  CHECK (category IN (
                                  'item_out_of_stock', 'order_cancelled', 'slow_shipping',
                                  'wrong_item', 'damaged', 'billing', 'other'
                              )),                        -- required when type = 'complaint'; NULL for reviews
    description  TEXT,                                   -- complaint text or review body
    status       VARCHAR(15)  NOT NULL DEFAULT 'open'
                              CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    -- Review-specific fields
    rating       SMALLINT     CHECK (rating >= 1 AND rating <= 5),  -- NULL for complaints
    sentiment    VARCHAR(10)  CHECK (sentiment IN ('positive', 'neutral', 'negative')),  -- NLP-derived; NULL for complaints
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    resolved_at  TIMESTAMPTZ
);

-- =============================================================================
-- 14. store.support_tickets
-- Support tickets created by create_support_ticket (tools/actions.py) or manually.
-- customer_id and order_id are nullable (may be system-generated tickets).
-- created_by_session_id is a SOFT REFERENCE to public.sessions(session_id); no FK constraint.
-- =============================================================================
CREATE TABLE store.support_tickets (
    id                     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id              VARCHAR(50)  UNIQUE NOT NULL,  -- human-readable, e.g. 'TKT-20250115143022'
    issue_description      TEXT         NOT NULL,
    priority               VARCHAR(10)  NOT NULL DEFAULT 'medium'
                                        CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    status                 VARCHAR(15)  NOT NULL DEFAULT 'open'
                                        CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    customer_id            UUID         REFERENCES store.customers(customer_id) ON DELETE SET NULL,  -- nullable
    order_id               UUID         REFERENCES store.orders(order_id) ON DELETE SET NULL,         -- nullable
    resolution_notes       TEXT,
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    resolved_at            TIMESTAMPTZ,                   -- set when status transitions to 'resolved'
    created_by_session_id  UUID                          -- soft ref → public.sessions(session_id); no FK constraint
);

-- =============================================================================
-- INDEXES
-- =============================================================================

-- store.orders
CREATE INDEX idx_orders_customer_id  ON store.orders (customer_id);
CREATE INDEX idx_orders_status       ON store.orders (status);
CREATE INDEX idx_orders_created_at   ON store.orders (created_at);

-- store.order_items
CREATE INDEX idx_order_items_order_id    ON store.order_items (order_id);
CREATE INDEX idx_order_items_product_id  ON store.order_items (product_id);

-- store.inventory_events
CREATE INDEX idx_inventory_events_product_id   ON store.inventory_events (product_id);
CREATE INDEX idx_inventory_events_event_type   ON store.inventory_events (event_type);
CREATE INDEX idx_inventory_events_created_at   ON store.inventory_events (created_at);

-- store.campaign_metrics
CREATE INDEX idx_campaign_metrics_campaign_id  ON store.campaign_metrics (campaign_id);
CREATE INDEX idx_campaign_metrics_date         ON store.campaign_metrics (date);

-- store.complaints (covers both complaints and reviews)
CREATE INDEX idx_complaints_type         ON store.complaints (type);
CREATE INDEX idx_complaints_customer_id  ON store.complaints (customer_id);
CREATE INDEX idx_complaints_product_id   ON store.complaints (product_id);
CREATE INDEX idx_complaints_category     ON store.complaints (category);
CREATE INDEX idx_complaints_sentiment    ON store.complaints (sentiment);
CREATE INDEX idx_complaints_created_at   ON store.complaints (created_at);

-- store.support_tickets
CREATE INDEX idx_support_tickets_status      ON store.support_tickets (status);
CREATE INDEX idx_support_tickets_priority    ON store.support_tickets (priority);
CREATE INDEX idx_support_tickets_created_at  ON store.support_tickets (created_at);
```

---

## Tool Query Reference

| Tool | Tables Used |
|---|---|
| `get_revenue_timeseries(date, granularity)` | `store.orders` (reads) |
| `get_order_volume(date)` | `store.orders`, `store.order_items` (reads) |
| `get_revenue_by_product(date, top_n)` | `store.orders`, `store.order_items`, `store.products` (reads) |
| `get_revenue_by_region(date)` | `store.orders`, `store.customers` (reads) |
| `detect_anomaly(date)` | `store.orders` (reads; compares today vs. 7-day rolling average) |
| `get_stock_levels(product_ids)` | `store.inventory`, `store.products` (reads) |
| `get_stockout_events(date)` | `store.inventory_events`, `store.products`, `store.campaigns`, `store.campaign_products` (reads) |
| `get_restock_recommendations(threshold_multiplier)` | `store.inventory`, `store.products` (reads) |
| `get_complaint_volume(date)` | `store.complaints WHERE type = 'complaint'` (reads) |
| `get_review_sentiment(date)` | `store.complaints WHERE type = 'review'` (reads) |
| `get_common_issues(date, top_n)` | `store.complaints` (reads; covers both complaints and reviews) |
| `get_campaign_performance(date)` | `store.campaign_metrics`, `store.campaigns` (reads) |
| `get_channel_breakdown(date)` | `store.campaign_metrics`, `store.campaigns` (reads; groups by channel) |
| `get_paused_campaigns(date)` | `store.campaigns` (reads; filters `status = 'paused'`) |
| `get_promotion_schedule()` | `store.promotions` (reads; filters active or future) |
| `restock_product(product_id, quantity)` | `store.restock_orders` (writes INSERT) |
| `apply_discount(product_ids, discount_pct, duration_hours)` | `store.promotions` (writes INSERT) |
| `pause_campaign(campaign_id, reason)` | `store.campaigns` (writes UPDATE: `status`, `paused_at`, `paused_reason`) |
| `create_support_ticket(issue_description, priority)` | `store.support_tickets` (writes INSERT) |

---

## Seed Data

When the database is initialised, the following seed rows must be present so that existing tool stubs (`tools/analytics.py`, `tools/inventory.py`, etc.) return meaningful data instead of empty result sets.

**`store.products` + `store.inventory`** — seed the five mock products currently hardcoded in tool stubs:

| Placeholder ID | Name | Category | base_price | Initial stock_qty | reorder_threshold |
|---|---|---|---|---|---|
| `P001` (map to UUID at seed time) | Laptop Pro 15 | Electronics | 1299.99 | 45 | 10 |
| `P002` | Wireless Mouse | Accessories | 29.99 | 12 | 20 |
| `P003` | USB-C Hub | Accessories | 49.99 | 0 | 15 |
| `P004` | Mechanical Keyboard | Peripherals | 89.99 | 8 | 15 |
| `P005` | Monitor 27" | Electronics | 349.99 | 23 | 5 |

**`store.campaigns`** — seed the two campaigns referenced in stub outputs:

| external_id | Name | channel | status |
|---|---|---|---|
| `CAMP_042` | Summer Tech Sale | `paid_search` | `active` |
| `CAMP_039` | Brand Awareness Q1 | `social_ads` | `paused` |

The full seed script (INSERT statements with deterministic UUIDs so cross-table FKs are consistent) will be placed in `db/seed.sql` — this file does not yet exist and will be created when the tool layer is wired to the real database.

---

## Agent → Tool Assignment

Tools are **not open to all agents**. Each specialist agent has access only to the tools in its own domain. This prevents the LLM from calling irrelevant tools and keeps token usage and latency low. The action tools (`tools/actions.py`) are reserved for the `action_executor` node and are never available to specialist agents.

| Agent | File | Tools available | Source file |
|---|---|---|---|
| Sales | `agent/specialists/sales.py` | `get_revenue_timeseries`, `get_order_volume`, `get_revenue_by_product`, `get_revenue_by_region`, `detect_anomaly` | `tools/analytics.py` |
| Inventory | `agent/specialists/inventory.py` | `get_stock_levels`, `get_stockout_events`, `get_restock_recommendations` | `tools/inventory.py` |
| Marketing | `agent/specialists/marketing.py` | `get_campaign_performance`, `get_channel_breakdown`, `get_paused_campaigns`, `get_promotion_schedule` | `tools/campaigns.py` |
| Support | `agent/specialists/support.py` | `get_complaint_volume`, `get_review_sentiment`, `get_common_issues` | `tools/crm.py` |
| Action Executor | `agent/action_executor.py` | `restock_product`, `apply_discount`, `pause_campaign`, `create_support_ticket` | `tools/actions.py` |

No tool crosses domain boundaries. If cross-domain data is needed (e.g. whether a stocked-out product has an active campaign), it is resolved in the **aggregator** node by correlating the findings from two specialists — not by giving one specialist another domain's tools.

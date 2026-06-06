-- ─────────────────────────────────────────────────────────────────────────────
-- 002_store_schema.sql
-- Store business data tables (store schema).
-- ─────────────────────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE SCHEMA IF NOT EXISTS store;

-- =============================================================================
-- 1. store.products
-- =============================================================================
CREATE TABLE IF NOT EXISTS store.products (
    product_id   UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    sku          VARCHAR(50)    UNIQUE NOT NULL,
    name         VARCHAR(255)   NOT NULL,
    category     VARCHAR(100),
    description  TEXT,
    unit_cost    NUMERIC(12,2),
    base_price   NUMERIC(12,2)  NOT NULL,
    is_active    BOOLEAN        NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 2. store.inventory
-- =============================================================================
CREATE TABLE IF NOT EXISTS store.inventory (
    product_id         UUID         PRIMARY KEY REFERENCES store.products(product_id) ON DELETE CASCADE,
    stock_qty          INTEGER      NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),
    reorder_threshold  INTEGER      NOT NULL DEFAULT 10,
    status             VARCHAR(15)  NOT NULL DEFAULT 'ok'
                                    CHECK (status IN ('ok', 'low', 'out_of_stock')),
    last_updated       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 3. store.inventory_events
-- =============================================================================
CREATE TABLE IF NOT EXISTS store.inventory_events (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID         NOT NULL REFERENCES store.products(product_id) ON DELETE CASCADE,
    event_type      VARCHAR(20)  NOT NULL
                                 CHECK (event_type IN ('sale', 'restock', 'adjustment', 'stockout', 'writeoff')),
    quantity_delta  INTEGER      NOT NULL,
    stock_after     INTEGER      NOT NULL,
    reference_id    UUID,
    notes           TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 4. store.restock_orders
-- =============================================================================
CREATE TABLE IF NOT EXISTS store.restock_orders (
    id                     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id             UUID         NOT NULL REFERENCES store.products(product_id) ON DELETE RESTRICT,
    quantity               INTEGER      NOT NULL CHECK (quantity > 0),
    status                 VARCHAR(15)  NOT NULL DEFAULT 'pending'
                                        CHECK (status IN ('pending', 'confirmed', 'received', 'cancelled')),
    estimated_arrival      VARCHAR(100),
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    received_at            TIMESTAMPTZ,
    created_by_session_id  UUID
);

-- =============================================================================
-- 5. store.customers
-- =============================================================================
CREATE TABLE IF NOT EXISTS store.customers (
    customer_id  UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    email        VARCHAR(255)  UNIQUE NOT NULL,
    name         VARCHAR(255)  NOT NULL,
    region       VARCHAR(100),
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 6. store.orders
-- =============================================================================
CREATE TABLE IF NOT EXISTS store.orders (
    order_id      UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id   UUID          NOT NULL REFERENCES store.customers(customer_id) ON DELETE RESTRICT,
    status        VARCHAR(20)   NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending', 'completed', 'cancelled')),
    total_amount  NUMERIC(12,2) NOT NULL CHECK (total_amount >= 0),
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    completed_at  TIMESTAMPTZ
);

-- =============================================================================
-- 7. store.order_items
-- =============================================================================
CREATE TABLE IF NOT EXISTS store.order_items (
    id          UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    UUID           NOT NULL REFERENCES store.orders(order_id) ON DELETE CASCADE,
    product_id  UUID           NOT NULL REFERENCES store.products(product_id) ON DELETE RESTRICT,
    quantity    INTEGER        NOT NULL CHECK (quantity > 0),
    unit_price  NUMERIC(12,2)  NOT NULL,
    subtotal    NUMERIC(12,2)  NOT NULL GENERATED ALWAYS AS (quantity * unit_price) STORED
);

-- =============================================================================
-- 8. store.price_history
-- =============================================================================
CREATE TABLE IF NOT EXISTS store.price_history (
    id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID          NOT NULL REFERENCES store.products(product_id) ON DELETE CASCADE,
    price           NUMERIC(12,2) NOT NULL CHECK (price >= 0),
    effective_from  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    effective_to    TIMESTAMPTZ,
    changed_by      VARCHAR(50)
);

-- =============================================================================
-- 9. store.promotions
-- =============================================================================
CREATE TABLE IF NOT EXISTS store.promotions (
    id                     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    promo_id               VARCHAR(50)  UNIQUE NOT NULL,
    product_ids            JSONB        NOT NULL,
    discount_pct           FLOAT        NOT NULL CHECK (discount_pct > 0 AND discount_pct <= 100),
    duration_hours         INTEGER      NOT NULL,
    starts_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    expires_at             TIMESTAMPTZ  NOT NULL,
    status                 VARCHAR(10)  NOT NULL DEFAULT 'active'
                                        CHECK (status IN ('active', 'expired', 'cancelled')),
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_by_session_id  UUID
);

-- =============================================================================
-- 10. store.campaigns
-- =============================================================================
CREATE TABLE IF NOT EXISTS store.campaigns (
    campaign_id    UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id    VARCHAR(50)   UNIQUE,
    name           VARCHAR(255)  NOT NULL,
    channel        VARCHAR(50)   NOT NULL
                                 CHECK (channel IN ('paid_search', 'social_ads', 'email', 'organic', 'display', 'affiliate')),
    status         VARCHAR(15)   NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active', 'paused', 'completed', 'cancelled')),
    budget         NUMERIC(12,2) NOT NULL,
    spend_to_date  NUMERIC(12,2) NOT NULL DEFAULT 0,
    start_date     DATE          NOT NULL,
    end_date       DATE,
    paused_at      TIMESTAMPTZ,
    paused_reason  TEXT,
    created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- 11. store.campaign_metrics
-- =============================================================================
CREATE TABLE IF NOT EXISTS store.campaign_metrics (
    id           UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id  UUID          NOT NULL REFERENCES store.campaigns(campaign_id) ON DELETE CASCADE,
    date         DATE          NOT NULL,
    spend        NUMERIC(12,2) NOT NULL DEFAULT 0,
    impressions  INTEGER       NOT NULL DEFAULT 0,
    clicks       INTEGER       NOT NULL DEFAULT 0,
    conversions  INTEGER       NOT NULL DEFAULT 0,
    revenue      NUMERIC(12,2) NOT NULL DEFAULT 0,
    roas         FLOAT,
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE (campaign_id, date)
);

-- =============================================================================
-- 12. store.campaign_products
-- =============================================================================
CREATE TABLE IF NOT EXISTS store.campaign_products (
    campaign_id  UUID  NOT NULL REFERENCES store.campaigns(campaign_id) ON DELETE CASCADE,
    product_id   UUID  NOT NULL REFERENCES store.products(product_id) ON DELETE CASCADE,
    PRIMARY KEY (campaign_id, product_id)
);

-- =============================================================================
-- 13. store.complaints
-- =============================================================================
CREATE TABLE IF NOT EXISTS store.complaints (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    type         VARCHAR(15)  NOT NULL DEFAULT 'complaint'
                              CHECK (type IN ('complaint', 'review')),
    customer_id  UUID         REFERENCES store.customers(customer_id) ON DELETE SET NULL,
    order_id     UUID         REFERENCES store.orders(order_id) ON DELETE SET NULL,
    product_id   UUID         REFERENCES store.products(product_id) ON DELETE SET NULL,
    category     VARCHAR(50)  CHECK (category IN (
                                  'item_out_of_stock', 'order_cancelled', 'slow_shipping',
                                  'wrong_item', 'damaged', 'billing', 'other'
                              )),
    description  TEXT,
    status       VARCHAR(15)  NOT NULL DEFAULT 'open'
                              CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    rating       SMALLINT     CHECK (rating >= 1 AND rating <= 5),
    sentiment    VARCHAR(10)  CHECK (sentiment IN ('positive', 'neutral', 'negative')),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    resolved_at  TIMESTAMPTZ
);

-- =============================================================================
-- 14. store.support_tickets
-- =============================================================================
CREATE TABLE IF NOT EXISTS store.support_tickets (
    id                     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id              VARCHAR(50)  UNIQUE NOT NULL,
    issue_description      TEXT         NOT NULL,
    priority               VARCHAR(10)  NOT NULL DEFAULT 'medium'
                                        CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    status                 VARCHAR(15)  NOT NULL DEFAULT 'open'
                                        CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    customer_id            UUID         REFERENCES store.customers(customer_id) ON DELETE SET NULL,
    order_id               UUID         REFERENCES store.orders(order_id) ON DELETE SET NULL,
    resolution_notes       TEXT,
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    resolved_at            TIMESTAMPTZ,
    created_by_session_id  UUID
);

-- =============================================================================
-- INDEXES
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_orders_customer_id  ON store.orders (customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status       ON store.orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_created_at   ON store.orders (created_at);

CREATE INDEX IF NOT EXISTS idx_order_items_order_id    ON store.order_items (order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product_id  ON store.order_items (product_id);

CREATE INDEX IF NOT EXISTS idx_inventory_events_product_id   ON store.inventory_events (product_id);
CREATE INDEX IF NOT EXISTS idx_inventory_events_event_type   ON store.inventory_events (event_type);
CREATE INDEX IF NOT EXISTS idx_inventory_events_created_at   ON store.inventory_events (created_at);

CREATE INDEX IF NOT EXISTS idx_campaign_metrics_campaign_id  ON store.campaign_metrics (campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_metrics_date         ON store.campaign_metrics (date);

CREATE INDEX IF NOT EXISTS idx_complaints_type         ON store.complaints (type);
CREATE INDEX IF NOT EXISTS idx_complaints_customer_id  ON store.complaints (customer_id);
CREATE INDEX IF NOT EXISTS idx_complaints_product_id   ON store.complaints (product_id);
CREATE INDEX IF NOT EXISTS idx_complaints_category     ON store.complaints (category);
CREATE INDEX IF NOT EXISTS idx_complaints_sentiment    ON store.complaints (sentiment);
CREATE INDEX IF NOT EXISTS idx_complaints_created_at   ON store.complaints (created_at);

CREATE INDEX IF NOT EXISTS idx_support_tickets_status      ON store.support_tickets (status);
CREATE INDEX IF NOT EXISTS idx_support_tickets_priority    ON store.support_tickets (priority);
CREATE INDEX IF NOT EXISTS idx_support_tickets_created_at  ON store.support_tickets (created_at);

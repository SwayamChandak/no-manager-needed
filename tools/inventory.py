"""
tools/inventory.py — Inventory analytics tools.

All functions are async and query the store schema via the shared asyncpg pool.
"""

import uuid as _uuid
from datetime import date as _date

from tools.registry import safe_tool

from db.connection import db_connection


@safe_tool(agents=["inventory"])
async def get_stock_levels(product_ids: list[str] | None = None) -> dict:
    """
    Returns current stock levels for products.
    Args:
        product_ids: optional list of product UUIDs to filter. If None, returns all.
    Returns dict with keys: products (list of {product_id, name, stock_qty, reorder_threshold, status})
    """
    sql = """
        SELECT
            p.product_id,
            p.name,
            i.stock_qty,
            i.reorder_threshold,
            i.status
        FROM store.inventory i
        JOIN store.products p ON p.product_id = i.product_id
        WHERE ($1::uuid[] IS NULL OR p.product_id = ANY($1::uuid[]))
          AND p.is_active = TRUE
    """
    uuids: list[_uuid.UUID] | None = None
    if product_ids:
        uuids = [_uuid.UUID(pid) for pid in product_ids]
    async with db_connection() as conn:
        rows = await conn.fetch(sql, uuids)
    return {
        "products": [
            {
                "product_id": str(r["product_id"]),
                "name": r["name"],
                "stock_qty": int(r["stock_qty"]),
                "reorder_threshold": int(r["reorder_threshold"]),
                "status": r["status"],
            }
            for r in rows
        ]
    }


@safe_tool(agents=["inventory"])
async def get_stockout_events(date: str) -> dict:
    """
    Returns all stockout events (products that went out of stock) on a given date.
    Args:
        date: ISO date string e.g. '2025-01-15'
    Returns dict with keys: date, events (list of {product_id, name, stockout_time, active_campaign})
    """
    _date_val = _date.fromisoformat(date)
    sql = """
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
          AND DATE(ie.created_at AT TIME ZONE 'UTC') = $1::date
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql, _date_val)
    return {
        "date": date,
        "events": [
            {
                "product_id": str(r["product_id"]),
                "name": r["name"],
                "stockout_time": r["stockout_time"].isoformat(),
                "active_campaign": bool(r["active_campaign"]),
            }
            for r in rows
        ],
    }


@safe_tool(agents=["inventory"])
async def get_restock_recommendations(threshold_multiplier: float = 1.0) -> dict:
    """
    Returns restock recommendations for products at or below the reorder threshold.
    Args:
        threshold_multiplier: multiplier applied to reorder_threshold (default 1.0)
    Returns dict with keys: recommendations (list of {product_id, name, stock_qty, reorder_threshold, recommended_qty})
    """
    sql = """
        SELECT
            p.product_id,
            p.name,
            i.stock_qty,
            i.reorder_threshold,
            CEIL(i.reorder_threshold * $1 * 2)::int AS recommended_qty
        FROM store.inventory i
        JOIN store.products p ON p.product_id = i.product_id
        WHERE i.stock_qty <= i.reorder_threshold * $1
          AND p.is_active = TRUE
        ORDER BY i.stock_qty ASC
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql, threshold_multiplier)
    return {
        "recommendations": [
            {
                "product_id": str(r["product_id"]),
                "name": r["name"],
                "stock_qty": int(r["stock_qty"]),
                "reorder_threshold": int(r["reorder_threshold"]),
                "recommended_qty": int(r["recommended_qty"]),
            }
            for r in rows
        ]
    }


@safe_tool(agents=["inventory"])
async def get_inventory_turnover_rate(date: str | None = None) -> dict:
    """
    Returns inventory turnover (units sold / average stock) by product category.
    Args:
        date: ISO date string (optional — omit for last-30-day view)
    Returns dict with keys: date or date_range, categories (list of {category, units_sold, avg_stock, turnover_rate})
    """
    if date is None:
        sql = """
            SELECT
                p.category,
                COALESCE(SUM(ie.quantity_delta * -1), 0) AS units_sold,
                AVG(i.stock_qty) AS avg_stock
            FROM store.inventory i
            JOIN store.products p ON p.product_id = i.product_id
            LEFT JOIN store.inventory_events ie ON ie.product_id = i.product_id
                AND ie.event_type = 'sale'
                AND ie.created_at >= NOW() - INTERVAL '30 days'
            WHERE p.category IS NOT NULL
            GROUP BY p.category
            ORDER BY units_sold DESC
        """
        async with db_connection() as conn:
            rows = await conn.fetch(sql)
        return {
            "date_range": "last_30_days",
            "categories": [
                {
                    "category": r["category"],
                    "units_sold": int(r["units_sold"]),
                    "avg_stock": round(float(r["avg_stock"] or 0), 1),
                    "turnover_rate": round(int(r["units_sold"]) / max(float(r["avg_stock"] or 0), 1), 2),
                }
                for r in rows
            ],
        }

    _date_val = _date.fromisoformat(date)
    sql = """
        SELECT
            p.category,
            COALESCE(SUM(ie.quantity_delta * -1), 0) AS units_sold,
            AVG(i.stock_qty) AS avg_stock
        FROM store.inventory i
        JOIN store.products p ON p.product_id = i.product_id
        LEFT JOIN store.inventory_events ie ON ie.product_id = i.product_id
            AND ie.event_type = 'sale'
            AND DATE(ie.created_at AT TIME ZONE 'UTC') = $1::date
        WHERE p.category IS NOT NULL
        GROUP BY p.category
        ORDER BY units_sold DESC
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql, _date_val)
    return {
        "date": date,
        "categories": [
            {
                "category": r["category"],
                "units_sold": int(r["units_sold"]),
                "avg_stock": round(float(r["avg_stock"] or 0), 1),
                "turnover_rate": round(int(r["units_sold"]) / max(float(r["avg_stock"] or 0), 1), 2),
            }
            for r in rows
        ],
    }


@safe_tool(agents=["inventory"])
async def get_inventory_summary_by_category() -> dict:
    """
    Returns aggregate inventory statistics grouped by product category.
    Returns dict with keys: categories (list of {category, product_count, total_stock, low_stock_count, out_of_stock_count})
    """
    sql = """
        SELECT
            p.category,
            COUNT(*) AS product_count,
            SUM(i.stock_qty) AS total_stock,
            SUM(CASE WHEN i.status = 'low' THEN 1 ELSE 0 END) AS low_stock_count,
            SUM(CASE WHEN i.status = 'out_of_stock' THEN 1 ELSE 0 END) AS out_of_stock_count
        FROM store.inventory i
        JOIN store.products p ON p.product_id = i.product_id
        WHERE p.is_active = TRUE
          AND p.category IS NOT NULL
        GROUP BY p.category
        ORDER BY total_stock DESC
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql)
    return {
        "categories": [
            {
                "category": r["category"],
                "product_count": int(r["product_count"]),
                "total_stock": int(r["total_stock"]),
                "low_stock_count": int(r["low_stock_count"]),
                "out_of_stock_count": int(r["out_of_stock_count"]),
            }
            for r in rows
        ]
    }

"""
tools/inventory.py — Inventory analytics tools.

All functions are async and query the store schema via the shared asyncpg pool.
"""

import uuid as _uuid
from datetime import date as _date

from langchain.tools import tool

from db.connection import db_connection


@tool
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


@tool
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


@tool
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

    """
    Returns current stock levels for products.
    Args:
        product_ids: optional list of product IDs to filter. If None, returns all.
    Returns dict with keys: products (list of {product_id, name, stock_qty, reorder_threshold, status})
    """
    return {
        "products": [
            {
                "product_id": "P001",
                "name": "Laptop Pro 15",
                "stock_qty": 0,
                "reorder_threshold": 20,
                "status": "out_of_stock",
            },
            {
                "product_id": "P002",
                "name": "Wireless Mouse",
                "stock_qty": 143,
                "reorder_threshold": 50,
                "status": "ok",
            },
            {
                "product_id": "P003",
                "name": "USB-C Hub",
                "stock_qty": 67,
                "reorder_threshold": 30,
                "status": "ok",
            },
            {
                "product_id": "P004",
                "name": "Mechanical Keyboard",
                "stock_qty": 0,
                "reorder_threshold": 15,
                "status": "out_of_stock",
            },
            {
                "product_id": "P005",
                "name": 'Monitor 27"',
                "stock_qty": 8,
                "reorder_threshold": 10,
                "status": "low",
            },
        ]
    }


@tool
def get_stockout_events(date: str) -> dict:
    """
    Returns all stockout events (products that went out of stock) on a given date.
    Args:
        date: ISO date string e.g. '2025-01-15'
    Returns dict with keys: date, events (list of {product_id, name, stockout_time, lost_revenue_estimate,
        active_campaign}), total_lost_revenue_estimate
    """
    return {
        "date": date,
        "events": [
            {
                "product_id": "P001",
                "name": "Laptop Pro 15",
                "stockout_time": "11:30",
                "lost_revenue_estimate": 4200.0,
                "active_campaign": True,
                "campaign_id": "CAMP_042",
                "campaign_name": "Summer Tech Sale",
            },
            {
                "product_id": "P004",
                "name": "Mechanical Keyboard",
                "stockout_time": "10:45",
                "lost_revenue_estimate": 1800.0,
                "active_campaign": False,
            },
        ],
        "total_lost_revenue_estimate": 6000.0,
    }


@tool
def get_viewed_not_purchased(date: str) -> dict:
    """
    Returns products that were viewed but not purchased, indicating potential lost demand.
    Args:
        date: ISO date string
    Returns dict with keys: date, products (list of {product_id, name, views, purchases,
        conversion_rate, likely_reason})
    """
    return {
        "date": date,
        "products": [
            {
                "product_id": "P001",
                "name": "Laptop Pro 15",
                "views": 512,
                "purchases": 0,
                "conversion_rate": 0.0,
                "likely_reason": "out_of_stock",
            },
            {
                "product_id": "P004",
                "name": "Mechanical Keyboard",
                "views": 289,
                "purchases": 0,
                "conversion_rate": 0.0,
                "likely_reason": "out_of_stock",
            },
            {
                "product_id": "P005",
                "name": 'Monitor 27"',
                "views": 134,
                "purchases": 8,
                "conversion_rate": 5.9,
                "likely_reason": "low_stock_warning_shown",
            },
        ],
    }


@tool
def get_restock_recommendations() -> dict:
    """
    Returns AI-generated restock recommendations based on current stock levels, demand history,
    and active campaigns.
    Returns dict with keys: recommendations (list of {product_id, name, recommended_qty, urgency, reason})
    """
    return {
        "recommendations": [
            {
                "product_id": "P001",
                "name": "Laptop Pro 15",
                "recommended_qty": 50,
                "urgency": "critical",
                "reason": (
                    "Out of stock with active campaign driving traffic. "
                    "Estimated $4200/day revenue loss."
                ),
            },
            {
                "product_id": "P004",
                "name": "Mechanical Keyboard",
                "recommended_qty": 30,
                "urgency": "high",
                "reason": "Out of stock. 289 views with 0 conversions yesterday.",
            },
            {
                "product_id": "P005",
                "name": 'Monitor 27"',
                "recommended_qty": 25,
                "urgency": "medium",
                "reason": (
                    "Stock below reorder threshold. "
                    "Low stock warning may be suppressing conversions."
                ),
            },
        ]
    }

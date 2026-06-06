"""
tools/campaigns.py — Marketing campaign analytics tools.

All functions are async and query the store schema via the shared asyncpg pool.
"""

from datetime import date as _date

from langchain.tools import tool

from db.connection import db_connection


@tool
async def get_campaign_performance(date: str) -> dict:
    """
    Returns campaign performance metrics for a given date.
    Args:
        date: ISO date string
    Returns dict with keys: date, campaigns (list of {campaign_id, name, status, spend,
        clicks, conversions, roas})
    """
    _date_val = _date.fromisoformat(date)
    sql = """
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
        WHERE cm.date = $1::date
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql, _date_val)
    return {
        "date": date,
        "campaigns": [
            {
                "campaign_id": r["external_id"] or str(r["campaign_id"]),
                "name": r["name"],
                "status": r["status"],
                "channel": r["channel"],
                "spend": float(r["spend"]),
                "impressions": int(r["impressions"]),
                "clicks": int(r["clicks"]),
                "conversions": int(r["conversions"]),
                "revenue": float(r["revenue"]),
                "roas": float(r["roas"]) if r["roas"] is not None else None,
            }
            for r in rows
        ],
    }


@tool
async def get_channel_breakdown(date: str) -> dict:
    """
    Returns performance breakdown by marketing channel for a given date.
    Args:
        date: ISO date string
    Returns dict with keys: date, channels (list of {channel, spend, revenue, roas})
    """
    _date_val = _date.fromisoformat(date)
    sql = """
        SELECT
            c.channel,
            SUM(cm.spend) AS spend,
            SUM(cm.revenue) AS revenue,
            SUM(cm.revenue) / NULLIF(SUM(cm.spend), 0) AS roas
        FROM store.campaign_metrics cm
        JOIN store.campaigns c ON c.campaign_id = cm.campaign_id
        WHERE cm.date = $1::date
        GROUP BY c.channel
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql, _date_val)
    return {
        "date": date,
        "channels": [
            {
                "channel": r["channel"],
                "spend": float(r["spend"]),
                "revenue": float(r["revenue"]),
                "roas": float(r["roas"]) if r["roas"] is not None else None,
            }
            for r in rows
        ],
    }


@tool
async def get_paused_campaigns(date: str) -> dict:
    """
    Returns all campaigns that were paused on a given date and the reason.
    Args:
        date: ISO date string
    Returns dict with keys: date, paused_campaigns (list of {campaign_id, name, paused_at, reason})
    """
    _date_val = _date.fromisoformat(date)
    sql = """
        SELECT
            campaign_id,
            external_id,
            name,
            paused_at,
            paused_reason,
            spend_to_date AS budget_used
        FROM store.campaigns
        WHERE status = 'paused'
          AND DATE(paused_at AT TIME ZONE 'UTC') = $1::date
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql, _date_val)
    return {
        "date": date,
        "paused_campaigns": [
            {
                "campaign_id": r["external_id"] or str(r["campaign_id"]),
                "name": r["name"],
                "paused_at": r["paused_at"].isoformat() if r["paused_at"] else None,
                "reason": r["paused_reason"],
                "budget_used": float(r["budget_used"]),
            }
            for r in rows
        ],
    }


@tool
async def get_promotion_schedule() -> dict:
    """
    Returns all active or upcoming promotions.
    Returns dict with keys: promotions (list of {promo_id, product_ids, discount_pct,
        starts_at, expires_at, status})
    """
    sql = """
        SELECT
            promo_id,
            product_ids,
            discount_pct,
            starts_at,
            expires_at,
            status
        FROM store.promotions
        WHERE status = 'active' OR starts_at > NOW()
        ORDER BY starts_at
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql)
    return {
        "promotions": [
            {
                "promo_id": r["promo_id"],
                "product_ids": r["product_ids"],
                "discount_pct": float(r["discount_pct"]),
                "starts_at": r["starts_at"].isoformat(),
                "expires_at": r["expires_at"].isoformat(),
                "status": r["status"],
            }
            for r in rows
        ]
    }

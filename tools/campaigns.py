"""
tools/campaigns.py — Marketing campaign analytics tools.

All functions are async and query the store schema via the shared asyncpg pool.
"""

from datetime import date as _date

from tools.registry import safe_tool

from db.connection import db_connection


@safe_tool(agents=["marketing"])
async def get_campaign_performance(date: str | None = None) -> dict:
    """
    Returns campaign performance metrics for a given date, or aggregated across all time if no date is given.
    Args:
        date: ISO date string (optional — omit for all-time aggregated view)
    Returns dict with keys: date or date_range, campaigns (list of {campaign_id, name, status, channel,
        spend, impressions, clicks, conversions, revenue, roas})
    """
    if date is None:
        sql = """
            SELECT
                c.campaign_id,
                c.external_id,
                c.name,
                c.status,
                c.channel,
                SUM(cm.spend) AS spend,
                SUM(cm.impressions) AS impressions,
                SUM(cm.clicks) AS clicks,
                SUM(cm.conversions) AS conversions,
                SUM(cm.revenue) AS revenue,
                SUM(cm.revenue) / NULLIF(SUM(cm.spend), 0) AS roas
            FROM store.campaign_metrics cm
            JOIN store.campaigns c ON c.campaign_id = cm.campaign_id
            GROUP BY c.campaign_id, c.external_id, c.name, c.status, c.channel
            ORDER BY revenue DESC
        """
        async with db_connection() as conn:
            rows = await conn.fetch(sql)
        return {
            "date_range": "all_time",
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


@safe_tool(agents=["marketing"])
async def get_channel_breakdown(date: str | None = None) -> dict:
    """
    Returns performance breakdown by marketing channel for a given date, or all-time if no date is given.
    Args:
        date: ISO date string (optional — omit for all-time aggregated view)
    Returns dict with keys: date or date_range, channels (list of {channel, spend, revenue, roas})
    """
    if date is None:
        sql = """
            SELECT
                c.channel,
                SUM(cm.spend) AS spend,
                SUM(cm.revenue) AS revenue,
                SUM(cm.revenue) / NULLIF(SUM(cm.spend), 0) AS roas
            FROM store.campaign_metrics cm
            JOIN store.campaigns c ON c.campaign_id = cm.campaign_id
            GROUP BY c.channel
            ORDER BY revenue DESC
        """
        async with db_connection() as conn:
            rows = await conn.fetch(sql)
        return {
            "date_range": "all_time",
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


@safe_tool(agents=["marketing"])
async def get_paused_campaigns(date: str | None = None) -> dict:
    """
    Returns paused campaigns. If date is given, returns only campaigns paused on that date.
    If date is omitted, returns all campaigns currently in 'paused' status.
    Args:
        date: ISO date string (optional — omit for all currently-paused campaigns)
    Returns dict with keys: date or date_range, paused_campaigns (list of {campaign_id, name, paused_at, reason, budget_used})
    """
    if date is None:
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
            ORDER BY paused_at DESC
        """
        async with db_connection() as conn:
            rows = await conn.fetch(sql)
        return {
            "date_range": "all_time",
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


@safe_tool(agents=["marketing"])
async def get_campaign_status_breakdown() -> dict:
    """
    Returns a breakdown of campaigns grouped by status (active, paused, completed, cancelled),
    including count, total budget, and total spend for each status group.
    Returns dict with keys: breakdown (list of {status, count, total_budget, total_spend})
    """
    sql = """
        SELECT
            status,
            COUNT(*) AS count,
            SUM(budget) AS total_budget,
            SUM(spend_to_date) AS total_spend
        FROM store.campaigns
        GROUP BY status
        ORDER BY status
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql)
    return {
        "breakdown": [
            {
                "status": r["status"],
                "count": int(r["count"]),
                "total_budget": float(r["total_budget"]),
                "total_spend": float(r["total_spend"]),
            }
            for r in rows
        ]
    }


@safe_tool(agents=["marketing"])
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


@safe_tool(agents=["marketing"])
async def get_campaign_roi_comparison(date: str | None = None) -> dict:
    """
    Compares ROAS (return on ad spend) across all campaigns, sorted by efficiency.
    Args:
        date: ISO date string (optional — omit for all-time aggregated view)
    Returns dict with keys: date or date_range, campaigns (list of {name, channel, spend, revenue, roas, efficiency_rating})
    """
    if date is None:
        sql = """
            SELECT
                c.name,
                c.channel,
                SUM(cm.spend) AS spend,
                SUM(cm.revenue) AS revenue,
                CASE WHEN SUM(cm.spend) > 0
                    THEN SUM(cm.revenue) / SUM(cm.spend) ELSE 0
                END AS roas
            FROM store.campaign_metrics cm
            JOIN store.campaigns c ON c.campaign_id = cm.campaign_id
            GROUP BY c.campaign_id, c.name, c.channel
            ORDER BY roas DESC
        """
        async with db_connection() as conn:
            rows = await conn.fetch(sql)
        return {
            "date_range": "all_time",
            "campaigns": [
                {
                    "name": r["name"],
                    "channel": r["channel"],
                    "spend": float(r["spend"]),
                    "revenue": float(r["revenue"]),
                    "roas": round(float(r["roas"]), 2),
                    "efficiency_rating": "high" if float(r["roas"]) >= 3.0
                        else ("medium" if float(r["roas"]) >= 1.0 else "low"),
                }
                for r in rows
            ],
        }

    _date_val = _date.fromisoformat(date)
    sql = """
        SELECT
            c.name,
            c.channel,
            cm.spend,
            cm.revenue,
            cm.roas
        FROM store.campaign_metrics cm
        JOIN store.campaigns c ON c.campaign_id = cm.campaign_id
        WHERE cm.date = $1::date
        ORDER BY cm.roas DESC NULLS LAST
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql, _date_val)
    return {
        "date": date,
        "campaigns": [
            {
                "name": r["name"],
                "channel": r["channel"],
                "spend": float(r["spend"]),
                "revenue": float(r["revenue"]),
                "roas": round(float(r["roas"] or 0), 2),
                "efficiency_rating": "high" if float(r["roas"] or 0) >= 3.0
                    else ("medium" if float(r["roas"] or 0) >= 1.0 else "low"),
            }
            for r in rows
        ],
    }


@safe_tool(agents=["marketing"])
async def get_channel_trends(days: int = 30) -> dict:
    """
    Returns daily spend and revenue trends grouped by marketing channel over the last N days.
    Args:
        days: number of days to look back (default 30)
    Returns dict with keys: channels (list of {channel, total_spend, total_revenue, roas, day_over_day_pct})
    """
    sql = """
        WITH channel_daily AS (
            SELECT
                c.channel,
                cm.date,
                SUM(cm.spend) AS spend,
                SUM(cm.revenue) AS revenue
            FROM store.campaign_metrics cm
            JOIN store.campaigns c ON c.campaign_id = cm.campaign_id
            WHERE cm.date >= CURRENT_DATE - $1::int
            GROUP BY c.channel, cm.date
        )
        SELECT
            channel,
            SUM(spend) AS total_spend,
            SUM(revenue) AS total_revenue,
            CASE WHEN SUM(spend) > 0 THEN SUM(revenue) / SUM(spend) ELSE 0 END AS roas,
            CASE
                WHEN SUM(CASE WHEN date = CURRENT_DATE - 1 THEN spend ELSE 0 END) > 0
                THEN (
                    SUM(CASE WHEN date = CURRENT_DATE THEN spend ELSE 0 END)
                    - SUM(CASE WHEN date = CURRENT_DATE - 1 THEN spend ELSE 0 END)
                ) / SUM(CASE WHEN date = CURRENT_DATE - 1 THEN spend ELSE 0 END) * 100
                ELSE 0
            END AS day_over_day_pct
        FROM channel_daily
        GROUP BY channel
        ORDER BY total_revenue DESC
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql, days)
    return {
        "lookback_days": days,
        "channels": [
            {
                "channel": r["channel"],
                "total_spend": float(r["total_spend"]),
                "total_revenue": float(r["total_revenue"]),
                "roas": round(float(r["roas"]), 2),
                "day_over_day_spend_change_pct": round(float(r["day_over_day_pct"]), 1),
            }
            for r in rows
        ],
    }

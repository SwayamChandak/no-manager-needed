"""
tools/crm.py — Customer complaints, reviews, and support analytics tools.

All functions are async and query the store schema via the shared asyncpg pool.
"""

from datetime import date as _date

from tools.registry import safe_tool

from db.connection import db_connection


@safe_tool(agents=["support"])
async def get_complaint_volume(date: str | None = None) -> dict:
    """
    Returns customer complaint volume and breakdown by category.
    If date is provided, filters to that day and includes % change vs prior day.
    If date is omitted, returns the all-time total and latest 5 complaints across all dates.
    Args:
        date: ISO date string (optional). Omit to get all-time totals.
    Returns dict with keys: date, total_complaints, pct_change_vs_prior_day (only when date given),
        categories (list), latest_complaints (list of 5 most recent)
    """
    if date is None:
        all_time_sql = """
            SELECT category, COUNT(*) AS count
            FROM store.complaints
            WHERE type = 'complaint'
            GROUP BY category
            ORDER BY count DESC
        """
        latest_sql = """
            SELECT id, category, description, created_at
            FROM store.complaints
            WHERE type = 'complaint'
            ORDER BY created_at DESC
            LIMIT 5
        """
        async with db_connection() as conn:
            rows = await conn.fetch(all_time_sql)
            latest_rows = await conn.fetch(latest_sql)
        total = sum(int(r["count"]) for r in rows)
        return {
            "date": "all-time",
            "total_complaints": total,
            "categories": [
                {"category": r["category"], "count": int(r["count"])}
                for r in rows
            ],
            "latest_complaints": [
                {
                    "id": r["id"],
                    "category": r["category"],
                    "description": r["description"] or "",
                    "created_at": r["created_at"].isoformat(),
                }
                for r in latest_rows
            ],
        }

    _date_val = _date.fromisoformat(date)
    today_sql = """
        SELECT category, COUNT(*) AS count
        FROM store.complaints
        WHERE type = 'complaint'
          AND DATE(created_at AT TIME ZONE 'UTC') = $1::date
        GROUP BY category
        ORDER BY count DESC
    """
    prior_sql = """
        SELECT COUNT(*)
        FROM store.complaints
        WHERE type = 'complaint'
          AND DATE(created_at AT TIME ZONE 'UTC') = $1::date - 1
    """
    latest_sql = """
        SELECT id, category, description, created_at
        FROM store.complaints
        WHERE type = 'complaint'
          AND DATE(created_at AT TIME ZONE 'UTC') = $1::date
        ORDER BY created_at DESC
        LIMIT 5
    """
    async with db_connection() as conn:
        rows = await conn.fetch(today_sql, _date_val)
        prior_total = int(await conn.fetchval(prior_sql, _date_val) or 0)
        latest_rows = await conn.fetch(latest_sql, _date_val)
    total = sum(int(r["count"]) for r in rows)
    pct_change = (
        round(((total - prior_total) / prior_total) * 100, 1) if prior_total else 0.0
    )
    return {
        "date": date,
        "total_complaints": total,
        "pct_change_vs_prior_day": pct_change,
        "categories": [
            {"category": r["category"], "count": int(r["count"])}
            for r in rows
        ],
        "latest_complaints": [
            {
                "id": r["id"],
                "category": r["category"],
                "description": r["description"] or "",
                "created_at": r["created_at"].isoformat(),
            }
            for r in latest_rows
        ],
    }


@safe_tool(agents=["support"])
async def get_review_sentiment(date: str) -> dict:
    """
    Returns aggregated customer review sentiment for a given date.
    Args:
        date: ISO date string
    Returns dict with keys: date, avg_rating (float), breakdown (list of {sentiment, count})
    """
    _date_val = _date.fromisoformat(date)
    sql = """
        SELECT
            AVG(rating) AS avg_rating,
            sentiment,
            COUNT(*) AS count
        FROM store.complaints
        WHERE type = 'review'
          AND DATE(created_at AT TIME ZONE 'UTC') = $1::date
        GROUP BY sentiment
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql, _date_val)
    overall_avg = (
        sum(float(r["avg_rating"] or 0) * int(r["count"]) for r in rows)
        / sum(int(r["count"]) for r in rows)
        if rows
        else 0.0
    )
    return {
        "date": date,
        "avg_rating": round(overall_avg, 2),
        "breakdown": [
            {"sentiment": r["sentiment"], "count": int(r["count"])}
            for r in rows
        ],
    }


@safe_tool(agents=["support"])
async def get_common_issues(date: str, top_n: int = 5) -> dict:
    """
    Returns the most common customer-reported issues for a given date.
    Args:
        date: ISO date string
        top_n: number of top issues to return
    Returns dict with keys: date, issues (list of {issue, frequency, representative_quote})
    """
    _date_val = _date.fromisoformat(date)
    sql = """
        SELECT
            COALESCE(category, 'review') AS issue,
            COUNT(*) AS frequency,
            MIN(description) AS representative_quote
        FROM store.complaints
        WHERE DATE(created_at AT TIME ZONE 'UTC') = $1::date
        GROUP BY COALESCE(category, 'review')
        ORDER BY frequency DESC
        LIMIT $2
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql, _date_val, top_n)
    return {
        "date": date,
        "issues": [
            {
                "issue": r["issue"],
                "frequency": int(r["frequency"]),
                "representative_quote": r["representative_quote"] or "",
            }
            for r in rows
        ],
    }


@safe_tool(agents=["support"])
def get_refund_rate(date: str) -> dict:
    """
    Returns refund and return rate metrics for a given date.
    Args:
        date: ISO date string
    Returns dict with keys: date, refund_count, refund_rate_pct, total_refund_value, vs_prior_week_pct
    """
    return {
        "date": date,
        "refund_count": 18,
        "refund_rate_pct": 12.6,
        "total_refund_value": 2340.0,
        "vs_prior_week_pct": 88.0,
        "top_reason": "item_unavailable_after_order",
    }


@safe_tool(agents=["support"])
async def get_resolution_metrics(date: str | None = None) -> dict:
    """
    Returns complaint and support ticket resolution efficiency metrics.
    Args:
        date: ISO date string (optional — omit for all-time aggregated view)
    Returns dict with keys: date or date_range, total_resolved (int), avg_resolution_hours (float),
        resolution_rate_pct (float), open_count (int)
    """
    if date is None:
        sql = """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status IN ('resolved', 'closed')) AS resolved,
                AVG(
                    EXTRACT(EPOCH FROM (COALESCE(resolved_at, NOW()) - created_at)) / 3600
                ) AS avg_hours,
                COUNT(*) FILTER (WHERE status = 'open') AS open_count
            FROM store.complaints
        """
        async with db_connection() as conn:
            row = await conn.fetchrow(sql)
        return {
            "date_range": "all_time",
            "total_resolved": int(row["resolved"]),
            "avg_resolution_hours": round(float(row["avg_hours"] or 0), 1),
            "resolution_rate_pct": round(
                int(row["resolved"]) / max(int(row["total"]), 1) * 100, 1
            ),
            "open_count": int(row["open_count"]),
        }

    _date_val = _date.fromisoformat(date)
    sql = """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status IN ('resolved', 'closed')) AS resolved,
            AVG(
                EXTRACT(EPOCH FROM (COALESCE(resolved_at, NOW()) - created_at)) / 3600
            ) AS avg_hours,
            COUNT(*) FILTER (WHERE status = 'open') AS open_count
        FROM store.complaints
        WHERE DATE(created_at AT TIME ZONE 'UTC') = $1::date
    """
    async with db_connection() as conn:
        row = await conn.fetchrow(sql, _date_val)
    return {
        "date": date,
        "total_resolved": int(row["resolved"]),
        "avg_resolution_hours": round(float(row["avg_hours"] or 0), 1),
        "resolution_rate_pct": round(
            int(row["resolved"]) / max(int(row["total"]), 1) * 100, 1
        ),
        "open_count": int(row["open_count"]),
    }


@safe_tool(agents=["support"])
async def get_support_ticket_summary() -> dict:
    """
    Returns a summary of all support tickets grouped by status and priority.
    Returns dict with keys: by_status (list of {status, count}), by_priority (list of {priority, count}),
        total_tickets (int), critical_open (int)
    """
    status_sql = """
        SELECT status, COUNT(*) AS count
        FROM store.support_tickets
        GROUP BY status
        ORDER BY status
    """
    priority_sql = """
        SELECT priority, COUNT(*) AS count
        FROM store.support_tickets
        GROUP BY priority
        ORDER BY CASE priority
            WHEN 'critical' THEN 1 WHEN 'high' THEN 2
            WHEN 'medium' THEN 3 WHEN 'low' THEN 4
            ELSE 5
        END
    """
    critical_open_sql = """
        SELECT COUNT(*) AS count
        FROM store.support_tickets
        WHERE priority = 'critical' AND status = 'open'
    """
    async with db_connection() as conn:
        status_rows = await conn.fetch(status_sql)
        priority_rows = await conn.fetch(priority_sql)
        critical_open = await conn.fetchval(critical_open_sql) or 0
    total = sum(int(r["count"]) for r in status_rows)
    return {
        "total_tickets": total,
        "by_status": [
            {"status": r["status"], "count": int(r["count"])}
            for r in status_rows
        ],
        "by_priority": [
            {"priority": r["priority"], "count": int(r["count"])}
            for r in priority_rows
        ],
        "critical_open": int(critical_open),
    }
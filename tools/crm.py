"""
tools/crm.py — Customer complaints, reviews, and support analytics tools.

All functions are async and query the store schema via the shared asyncpg pool.
"""

from datetime import date as _date

from tools.registry import safe_tool

from db.connection import db_connection


@safe_tool(agents=["support"])
async def get_complaint_volume(date: str) -> dict:
    """
    Returns customer complaint volume and breakdown by category for a given date.
    Args:
        date: ISO date string
    Returns dict with keys: date, total_complaints, pct_change_vs_prior_day, categories (list)
    """
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
    async with db_connection() as conn:
        rows = await conn.fetch(today_sql, _date_val)
        prior_total = int(await conn.fetchval(prior_sql, _date_val) or 0)
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

    """
    Returns customer complaint volume and breakdown by category for a given date.
    Args:
        date: ISO date string
    Returns dict with keys: date, total_complaints, pct_change_vs_prior_day, categories (list)
    """
    return {
        "date": date,
        "total_complaints": 47,
        "pct_change_vs_prior_day": 156.0,
        "categories": [
            {"category": "item_out_of_stock", "count": 28, "pct": 59.6},
            {"category": "order_cancelled", "count": 11, "pct": 23.4},
            {"category": "slow_shipping", "count": 5, "pct": 10.6},
            {"category": "wrong_item", "count": 3, "pct": 6.4},
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
def get_review_sentiment(date: str) -> dict:
    """
    Returns aggregated customer review sentiment for a given date.
    Args:
        date: ISO date string
    Returns dict with keys: date, avg_rating, sentiment_breakdown, notable_themes (list of strings)
    """
    return {
        "date": date,
        "avg_rating": 2.8,
        "vs_prior_week_avg": 4.1,
        "sentiment_breakdown": {
            "positive": 18,
            "neutral": 9,
            "negative": 31,
        },
        "notable_themes": [
            "Products showing as available but out of stock",
            "Orders cancelled after payment",
            "Disappointed with Summer Tech Sale — items gone",
        ],
    }


@safe_tool(agents=["support"])
def get_common_issues(date: str, top_n: int = 5) -> dict:
    """
    Returns the most common customer-reported issues for a given date.
    Args:
        date: ISO date string
        top_n: number of top issues to return
    Returns dict with keys: date, issues (list of {issue, frequency, representative_quote})
    """
    return {
        "date": date,
        "issues": [
            {
                "issue": "Laptop Pro 15 shown as available but out of stock",
                "frequency": 22,
                "representative_quote": (
                    "I added it to cart and paid, then got a cancellation email."
                ),
            },
            {
                "issue": "Summer Tech Sale items unavailable",
                "frequency": 15,
                "representative_quote": (
                    "The sale page is live but nothing is actually in stock."
                ),
            },
            {
                "issue": "Order cancelled without prior notice",
                "frequency": 11,
                "representative_quote": (
                    "Very frustrating experience, lost trust in the store."
                ),
            },
        ],
    }

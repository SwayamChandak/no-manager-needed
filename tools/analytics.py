"""
tools/analytics.py — Sales and revenue analytics tools.

All functions are async and query the store schema via the shared asyncpg pool.
The @tool decorator from langchain supports async def natively.
"""

from datetime import date as _date

from tools.registry import safe_tool

from db.connection import db_connection

# Allowlist for DATE_TRUNC unit — never interpolate user input directly into SQL
_GRANULARITY_MAP = {"hourly": "hour", "daily": "day"}


@safe_tool(agents=["sales"])
async def get_revenue_timeseries(date: str | None = None, granularity: str = "daily") -> dict:
    """
    Returns revenue timeseries for a given date, or the last 30 days if no date is provided.
    Args:
        date: ISO date string e.g. '2025-01-15' (optional — omit for last-30-day view)
        granularity: 'hourly' or 'daily' (default 'daily' when no date; 'hourly' when date given)
    Returns dict with keys: date_range or date, granularity, total (float), data_points (list of {time, revenue})
    """
    trunc_unit = _GRANULARITY_MAP.get(granularity)
    if trunc_unit is None:
        raise ValueError(f"granularity must be one of {list(_GRANULARITY_MAP)}")

    if date is None:
        sql = f"""
            SELECT
                DATE_TRUNC('{trunc_unit}', created_at AT TIME ZONE 'UTC') AS bucket,
                SUM(total_amount) AS revenue
            FROM store.orders
            WHERE created_at AT TIME ZONE 'UTC' >= NOW() - INTERVAL '30 days'
              AND status = 'completed'
            GROUP BY bucket
            ORDER BY bucket
        """
        async with db_connection() as conn:
            rows = await conn.fetch(sql)
        total = sum(float(r["revenue"]) for r in rows)
        return {
            "date_range": "last_30_days",
            "granularity": granularity,
            "total": total,
            "data_points": [
                {"time": r["bucket"].isoformat(), "revenue": float(r["revenue"])}
                for r in rows
            ],
        }

    _date_val = _date.fromisoformat(date)
    sql = f"""
        SELECT
            DATE_TRUNC('{trunc_unit}', created_at AT TIME ZONE 'UTC') AS bucket,
            SUM(total_amount) AS revenue
        FROM store.orders
        WHERE DATE(created_at AT TIME ZONE 'UTC') = $1::date
          AND status = 'completed'
        GROUP BY bucket
        ORDER BY bucket
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql, _date_val)
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


@safe_tool(agents=["sales"])
async def get_order_volume(date: str | None = None) -> dict:
    """
    Returns total order count and breakdown by period.
    If date is given, breaks down by hour for that day.
    If date is omitted, returns daily order totals and overall avg order value for the last 30 days.
    Args:
        date: ISO date string (optional — omit for last-30-day view)
    Returns dict with keys: date or date_range, total_orders (int), avg_order_value (float),
        hourly_breakdown (when date given) or daily_breakdown (when omitted)
    """
    if date is None:
        sql = """
            SELECT
                DATE(created_at AT TIME ZONE 'UTC') AS day,
                COUNT(order_id) AS orders,
                AVG(total_amount) AS avg_value
            FROM store.orders
            WHERE created_at AT TIME ZONE 'UTC' >= NOW() - INTERVAL '30 days'
            GROUP BY day
            ORDER BY day
        """
        async with db_connection() as conn:
            rows = await conn.fetch(sql)
        total_orders = sum(int(r["orders"]) for r in rows)
        overall_avg = (
            sum(float(r["avg_value"] or 0) * int(r["orders"]) for r in rows) / total_orders
            if total_orders else 0.0
        )
        return {
            "date_range": "last_30_days",
            "total_orders": total_orders,
            "avg_order_value": round(overall_avg, 2),
            "daily_breakdown": [
                {
                    "day": r["day"].isoformat(),
                    "orders": int(r["orders"]),
                    "avg_value": round(float(r["avg_value"] or 0), 2),
                }
                for r in rows
            ],
        }

    _date_val = _date.fromisoformat(date)
    sql = """
        SELECT
            DATE_TRUNC('hour', o.created_at AT TIME ZONE 'UTC') AS hour,
            COUNT(o.order_id) AS orders,
            AVG(o.total_amount) AS avg_value
        FROM store.orders o
        WHERE DATE(o.created_at AT TIME ZONE 'UTC') = $1::date
        GROUP BY hour
        ORDER BY hour
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql, _date_val)
    total_orders = sum(int(r["orders"]) for r in rows)
    overall_avg = float(rows[0]["avg_value"]) if rows else 0.0
    return {
        "date": date,
        "total_orders": total_orders,
        "avg_order_value": overall_avg,
        "hourly_breakdown": [
            {
                "hour": r["hour"].isoformat(),
                "orders": int(r["orders"]),
                "avg_value": float(r["avg_value"] or 0),
            }
            for r in rows
        ],
    }


@safe_tool(agents=["sales"])
async def get_revenue_by_product(date: str | None = None, top_n: int = 5) -> dict:
    """
    Returns revenue broken down by product for a given date, or the last 30 days if no date is given.
    Args:
        date: ISO date string (optional — omit for last-30-day view)
        top_n: number of top products to return
    Returns dict with keys: date or date_range, products (list of {product_id, name, revenue, units_sold, pct_of_total})
    """
    if date is None:
        sql = """
            SELECT
                p.product_id,
                p.name,
                SUM(oi.subtotal) AS revenue,
                SUM(oi.quantity) AS units_sold
            FROM store.order_items oi
            JOIN store.orders o ON o.order_id = oi.order_id
            JOIN store.products p ON p.product_id = oi.product_id
            WHERE o.created_at AT TIME ZONE 'UTC' >= NOW() - INTERVAL '30 days'
              AND o.status = 'completed'
            GROUP BY p.product_id, p.name
            ORDER BY revenue DESC
            LIMIT $1
        """
        async with db_connection() as conn:
            rows = await conn.fetch(sql, top_n)
        total_rev = sum(float(r["revenue"]) for r in rows)
        return {
            "date_range": "last_30_days",
            "products": [
                {
                    "product_id": str(r["product_id"]),
                    "name": r["name"],
                    "revenue": float(r["revenue"]),
                    "units_sold": int(r["units_sold"]),
                    "pct_of_total": round(float(r["revenue"]) / total_rev * 100, 1) if total_rev else 0.0,
                }
                for r in rows
            ],
        }

    _date_val = _date.fromisoformat(date)
    sql = """
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
        LIMIT $2
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql, _date_val, top_n)
    total_rev = sum(float(r["revenue"]) for r in rows)
    return {
        "date": date,
        "products": [
            {
                "product_id": str(r["product_id"]),
                "name": r["name"],
                "revenue": float(r["revenue"]),
                "units_sold": int(r["units_sold"]),
                "pct_of_total": round(float(r["revenue"]) / total_rev * 100, 1) if total_rev else 0.0,
            }
            for r in rows
        ],
    }


@safe_tool(agents=["sales"])
async def get_revenue_by_region(date: str | None = None) -> dict:
    """
    Returns revenue broken down by customer region for a given date, or the last 30 days if no date is given.
    Args:
        date: ISO date string (optional — omit for last-30-day view)
    Returns dict with keys: date or date_range, regions (list of {region, revenue, orders})
    """
    if date is None:
        sql = """
            SELECT
                c.region,
                SUM(o.total_amount) AS revenue,
                COUNT(o.order_id) AS orders
            FROM store.orders o
            JOIN store.customers c ON c.customer_id = o.customer_id
            WHERE o.created_at AT TIME ZONE 'UTC' >= NOW() - INTERVAL '30 days'
              AND o.status = 'completed'
            GROUP BY c.region
            ORDER BY revenue DESC
        """
        async with db_connection() as conn:
            rows = await conn.fetch(sql)
        return {
            "date_range": "last_30_days",
            "regions": [
                {
                    "region": r["region"],
                    "revenue": float(r["revenue"]),
                    "orders": int(r["orders"]),
                }
                for r in rows
            ],
        }

    _date_val = _date.fromisoformat(date)
    sql = """
        SELECT
            c.region,
            SUM(o.total_amount) AS revenue,
            COUNT(o.order_id) AS orders
        FROM store.orders o
        JOIN store.customers c ON c.customer_id = o.customer_id
        WHERE DATE(o.created_at AT TIME ZONE 'UTC') = $1::date
          AND o.status = 'completed'
        GROUP BY c.region
        ORDER BY revenue DESC
    """
    async with db_connection() as conn:
        rows = await conn.fetch(sql, _date_val)
    return {
        "date": date,
        "regions": [
            {
                "region": r["region"],
                "revenue": float(r["revenue"]),
                "orders": int(r["orders"]),
            }
            for r in rows
        ],
    }


@safe_tool(agents=["sales"])
async def detect_anomaly(date: str) -> dict:
    """
    Detects whether revenue on the given date is anomalous vs the 7-day rolling average.
    Args:
        date: ISO date string
    Returns dict with keys: date, is_anomaly (bool), pct_deviation (float),
        today_revenue (float), avg_revenue (float), today_orders (int), avg_orders (float)
    """

    today_sql = """
        SELECT
            SUM(total_amount) AS today_revenue,
            COUNT(*) AS today_orders
        FROM store.orders
        WHERE DATE(created_at AT TIME ZONE 'UTC') = $1::date
          AND status = 'completed'
    """
    avg_sql = """
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
        ) sub
    """
    async with db_connection() as conn:
        today_row = await conn.fetchrow(today_sql, date)
        avg_row = await conn.fetchrow(avg_sql, date)

    today_rev = float(today_row["today_revenue"] or 0)
    today_orders = int(today_row["today_orders"] or 0)
    avg_rev = float(avg_row["avg_revenue"] or 0)
    avg_orders = float(avg_row["avg_orders"] or 0)

    is_anomaly = avg_rev > 0 and today_rev < avg_rev * 0.7
    pct_deviation = (
        round(((today_rev - avg_rev) / avg_rev) * 100, 1) if avg_rev > 0 else 0.0
    )

    return {
        "date": date,
        "is_anomaly": is_anomaly,
        "pct_deviation": pct_deviation,
        "today_revenue": today_rev,
        "avg_revenue": avg_rev,
        "today_orders": today_orders,
        "avg_orders": avg_orders,
    }

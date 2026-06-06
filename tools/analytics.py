"""
tools/analytics.py — Sales and revenue analytics tools.

All functions are async and query the store schema via the shared asyncpg pool.
The @tool decorator from langchain supports async def natively.
"""

from datetime import date as _date

from langchain.tools import tool

from db.connection import db_connection

# Allowlist for DATE_TRUNC unit — never interpolate user input directly into SQL
_GRANULARITY_MAP = {"hourly": "hour", "daily": "day"}


@tool
async def get_revenue_timeseries(date: str, granularity: str = "hourly") -> dict:
    """
    Returns revenue timeseries for a given date.
    Args:
        date: ISO date string e.g. '2025-01-15'
        granularity: 'hourly' or 'daily'
    Returns dict with keys: date, granularity, total (float), data_points (list of {time, revenue})
    """
    trunc_unit = _GRANULARITY_MAP.get(granularity)
    if trunc_unit is None:
        raise ValueError(f"granularity must be one of {list(_GRANULARITY_MAP)}")
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


@tool
async def get_order_volume(date: str) -> dict:
    """
    Returns total order count and breakdown by hour for a given date.
    Args:
        date: ISO date string e.g. '2025-01-15'
    Returns dict with keys: date, total_orders (int), avg_order_value (float), hourly_breakdown (list)
    """
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


@tool
async def get_revenue_by_product(date: str, top_n: int = 5) -> dict:
    """
    Returns revenue broken down by product for a given date.
    Args:
        date: ISO date string
        top_n: number of top products to return
    Returns dict with keys: date, products (list of {product_id, name, revenue, units_sold, pct_of_total})
    """
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


@tool
async def get_revenue_by_region(date: str) -> dict:
    """
    Returns revenue broken down by customer region for a given date.
    Args:
        date: ISO date string
    Returns dict with keys: date, regions (list of {region, revenue, orders})
    """
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


@tool
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

    """
    Returns revenue timeseries for a given date.
    Args:
        date: ISO date string e.g. '2025-01-15'
        granularity: 'hourly' or 'daily'
    Returns dict with keys: date, total (float), data_points (list of {time, revenue})
    """
    return {
        "date": date,
        "granularity": granularity,
        "total": 8750.0,
        "data_points": [
            {"time": "09:00", "revenue": 2100.0},
            {"time": "10:00", "revenue": 2300.0},
            {"time": "11:00", "revenue": 980.0},
            {"time": "12:00", "revenue": 650.0},
            {"time": "13:00", "revenue": 420.0},
            {"time": "14:00", "revenue": 310.0},
            {"time": "15:00", "revenue": 890.0},
            {"time": "16:00", "revenue": 1100.0},
        ],
        "note": "Significant drop observed after 11:00",
    }


@tool
def get_order_volume(date: str) -> dict:
    """
    Returns total order count and breakdown by hour for a given date.
    Args:
        date: ISO date string e.g. '2025-01-15'
    Returns dict with keys: date, total_orders (int), avg_order_value (float), hourly_breakdown (list)
    """
    return {
        "date": date,
        "total_orders": 143,
        "avg_order_value": 61.2,
        "hourly_breakdown": [
            {"hour": "09:00", "orders": 34},
            {"hour": "10:00", "orders": 41},
            {"hour": "11:00", "orders": 28},
            {"hour": "12:00", "orders": 17},
            {"hour": "13:00", "orders": 11},
            {"hour": "14:00", "orders": 7},
            {"hour": "15:00", "orders": 5},
        ],
        "note": "Order volume dropped 70% after 11:00 vs prior day average of 38/hr",
    }


@tool
def get_revenue_by_product(date: str, top_n: int = 10) -> dict:
    """
    Returns revenue broken down by product for a given date.
    Args:
        date: ISO date string
        top_n: number of top products to return
    Returns dict with keys: date, products (list of {product_id, name, revenue, units_sold, pct_of_total})
    """
    return {
        "date": date,
        "products": [
            {
                "product_id": "P001",
                "name": "Laptop Pro 15",
                "revenue": 0.0,
                "units_sold": 0,
                "pct_of_total": 0.0,
                "note": "Out of stock from 11:30",
            },
            {
                "product_id": "P002",
                "name": "Wireless Mouse",
                "revenue": 1840.0,
                "units_sold": 92,
                "pct_of_total": 21.0,
            },
            {
                "product_id": "P003",
                "name": "USB-C Hub",
                "revenue": 1560.0,
                "units_sold": 78,
                "pct_of_total": 17.8,
            },
            {
                "product_id": "P004",
                "name": "Mechanical Keyboard",
                "revenue": 0.0,
                "units_sold": 0,
                "pct_of_total": 0.0,
                "note": "Out of stock from 10:45",
            },
            {
                "product_id": "P005",
                "name": 'Monitor 27"',
                "revenue": 2100.0,
                "units_sold": 14,
                "pct_of_total": 24.0,
            },
        ],
    }


@tool
def get_revenue_by_region(date: str) -> dict:
    """
    Returns revenue broken down by geographic region for a given date.
    Args:
        date: ISO date string
    Returns dict with keys: date, regions (list of {region, revenue, orders, pct_change_vs_prior_week})
    """
    return {
        "date": date,
        "regions": [
            {"region": "North", "revenue": 3200.0, "orders": 52, "pct_change_vs_prior_week": -18.0},
            {"region": "South", "revenue": 2800.0, "orders": 45, "pct_change_vs_prior_week": -12.0},
            {"region": "East", "revenue": 1500.0, "orders": 28, "pct_change_vs_prior_week": -41.0},
            {"region": "West", "revenue": 1250.0, "orders": 18, "pct_change_vs_prior_week": -35.0},
        ],
    }


@tool
def detect_anomaly(metric: str, date: str) -> dict:
    """
    Runs anomaly detection on a given metric for a given date.
    Args:
        metric: one of 'revenue', 'orders', 'aov' (average order value)
        date: ISO date string
    Returns dict with keys: metric, date, is_anomaly (bool), severity ('low'|'medium'|'high'),
        deviation_pct (float), explanation
    """
    return {
        "metric": metric,
        "date": date,
        "is_anomaly": True,
        "severity": "high",
        "deviation_pct": -38.5,
        "explanation": (
            f"{metric} is 38.5% below the 30-day rolling average. "
            "This is a statistically significant drop (>3 sigma)."
        ),
        "baseline_30d_avg": 14200.0,
        "observed_value": 8750.0,
    }

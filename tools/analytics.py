from langchain_core.tools import tool


@tool
def get_revenue_timeseries(date: str, granularity: str = "hourly") -> dict:
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

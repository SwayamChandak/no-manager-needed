from langchain_core.tools import tool


@tool
def get_stock_levels(product_ids: list[str] | None = None) -> dict:
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

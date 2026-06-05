from langchain_core.tools import tool


@tool
def get_complaint_volume(date: str) -> dict:
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


@tool
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


@tool
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


@tool
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

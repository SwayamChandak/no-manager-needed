from langchain_core.tools import tool


@tool
def get_campaign_performance(date: str) -> dict:
    """
    Returns campaign performance metrics for a given date.
    Args:
        date: ISO date string
    Returns dict with keys: date, campaigns (list of {campaign_id, name, status, spend, clicks,
        conversions, roas, issues})
    """
    return {
        "date": date,
        "campaigns": [
            {
                "campaign_id": "CAMP_042",
                "name": "Summer Tech Sale",
                "status": "active",
                "spend": 1240.0,
                "clicks": 8400,
                "conversions": 23,
                "roas": 0.8,
                "issues": [
                    "ROAS below target 3.0",
                    "Landing products out of stock — wasted spend",
                ],
            },
            {
                "campaign_id": "CAMP_039",
                "name": "Brand Awareness Q1",
                "status": "paused",
                "spend": 0.0,
                "clicks": 0,
                "conversions": 0,
                "roas": 0.0,
                "issues": ["Paused at 09:15 — budget exhausted"],
                "paused_at": "09:15",
            },
        ],
    }


@tool
def get_channel_breakdown(date: str) -> dict:
    """
    Returns performance breakdown by marketing channel for a given date.
    Args:
        date: ISO date string
    Returns dict with keys: date, channels (list of {channel, spend, revenue, roas, pct_change_vs_prior_week})
    """
    return {
        "date": date,
        "channels": [
            {
                "channel": "paid_search",
                "spend": 620.0,
                "revenue": 1240.0,
                "roas": 2.0,
                "pct_change_vs_prior_week": -45.0,
            },
            {
                "channel": "social_ads",
                "spend": 480.0,
                "revenue": 720.0,
                "roas": 1.5,
                "pct_change_vs_prior_week": -52.0,
            },
            {
                "channel": "email",
                "spend": 0.0,
                "revenue": 3200.0,
                "roas": None,
                "pct_change_vs_prior_week": -8.0,
            },
            {
                "channel": "organic",
                "spend": 0.0,
                "revenue": 3590.0,
                "roas": None,
                "pct_change_vs_prior_week": -5.0,
            },
        ],
    }


@tool
def get_paused_campaigns(date: str) -> dict:
    """
    Returns all campaigns that were paused on a given date and the reason.
    Args:
        date: ISO date string
    Returns dict with keys: date, paused_campaigns (list of {campaign_id, name, paused_at, reason})
    """
    return {
        "date": date,
        "paused_campaigns": [
            {
                "campaign_id": "CAMP_039",
                "name": "Brand Awareness Q1",
                "paused_at": "09:15",
                "reason": "Daily budget cap reached",
            }
        ],
    }


@tool
def get_promotion_schedule(date: str) -> dict:
    """
    Returns scheduled promotions and whether they ran as planned on a given date.
    Args:
        date: ISO date string
    Returns dict with keys: date, promotions (list of {promo_id, name, scheduled_time, actual_status, issue})
    """
    return {
        "date": date,
        "promotions": [
            {
                "promo_id": "PROMO_021",
                "name": "Flash Sale 20% — Laptops",
                "scheduled_time": "12:00",
                "actual_status": "did_not_run",
                "issue": "Target products (P001, P004) out of stock at scheduled time",
            }
        ],
    }

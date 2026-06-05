from datetime import datetime

from langchain_core.tools import tool


@tool
def restock_product(product_id: str, quantity: int) -> dict:
    """
    Submits a restock order for a product.
    Args:
        product_id: the product identifier
        quantity: number of units to restock
    Returns dict with keys: success (bool), order_id, product_id, quantity, estimated_arrival, message
    """
    return {
        "success": True,
        "order_id": f"RO-{product_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        "product_id": product_id,
        "quantity": quantity,
        "estimated_arrival": "2-3 business days",
        "message": f"Restock order placed for {quantity} units of {product_id}.",
        "timestamp": datetime.utcnow().isoformat(),
    }


@tool
def apply_discount(product_ids: list[str], discount_pct: float, duration_hours: int) -> dict:
    """
    Applies a discount to a list of products for a given duration.
    Args:
        product_ids: list of product IDs to discount
        discount_pct: discount percentage (e.g. 10.0 for 10%)
        duration_hours: how long the discount should run
    Returns dict with keys: success (bool), promo_id, product_ids, discount_pct, expires_at, message
    """
    now = datetime.utcnow()
    return {
        "success": True,
        "promo_id": f"PROMO-{now.strftime('%Y%m%d%H%M%S')}",
        "product_ids": product_ids,
        "discount_pct": discount_pct,
        "duration_hours": duration_hours,
        "expires_at": now.isoformat(),
        "message": (
            f"{discount_pct}% discount applied to {len(product_ids)} products "
            f"for {duration_hours} hours."
        ),
        "timestamp": now.isoformat(),
    }


@tool
def pause_campaign(campaign_id: str, reason: str) -> dict:
    """
    Pauses an active marketing campaign.
    Args:
        campaign_id: the campaign identifier
        reason: human-readable reason for pausing
    Returns dict with keys: success (bool), campaign_id, status, paused_at, message
    """
    return {
        "success": True,
        "campaign_id": campaign_id,
        "status": "paused",
        "paused_at": datetime.utcnow().isoformat(),
        "reason": reason,
        "message": f"Campaign {campaign_id} paused. Reason: {reason}",
    }


@tool
def create_support_ticket(issue_description: str, priority: str = "medium") -> dict:
    """
    Creates a support ticket in the CRM for a reported issue.
    Args:
        issue_description: description of the issue
        priority: 'low', 'medium', 'high', or 'critical'
    Returns dict with keys: success (bool), ticket_id, priority, created_at, message
    """
    return {
        "success": True,
        "ticket_id": f"TKT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        "issue_description": issue_description,
        "priority": priority,
        "created_at": datetime.utcnow().isoformat(),
        "assigned_to": "ops-team",
        "message": f"Support ticket created with priority '{priority}'.",
    }

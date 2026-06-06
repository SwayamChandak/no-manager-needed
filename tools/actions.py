"""
tools/actions.py — Action executor tools (write operations).

All functions are async. The current_session_id ContextVar allows nodes to
inject the session ID without changing tool signatures.
"""

import contextvars
import json
import uuid as _uuid
from datetime import datetime, timedelta, timezone

from langchain.tools import tool

from db.connection import db_connection

# Set this ContextVar before invoking any action tool so the tool can record
# which session triggered the action without a parameter change.
current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_session_id", default=""
)

_VALID_PRIORITIES = {"low", "medium", "high", "critical"}


@tool
async def restock_product(product_id: str, quantity: int) -> dict:
    """
    Submits a restock order for a product.
    Args:
        product_id: UUID string or legacy SKU (e.g. 'P001')
        quantity: number of units to restock
    Returns dict with keys: status, restock_order_id, product_id, quantity, estimated_arrival
    """
    session_id = current_session_id.get() or None

    # Resolve product UUID — handle both UUID strings and legacy SKUs
    try:
        product_uuid = _uuid.UUID(product_id)
    except ValueError:
        async with db_connection() as conn:
            row = await conn.fetchrow(
                "SELECT product_id FROM store.products WHERE sku = $1 LIMIT 1",
                product_id,
            )
        if row is None:
            raise ValueError(f"Product '{product_id}' not found by SKU")
        product_uuid = row["product_id"]

    session_uuid = _uuid.UUID(session_id) if session_id else None

    async with db_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO store.restock_orders
                (product_id, quantity, status, estimated_arrival, created_by_session_id)
            VALUES ($1::uuid, $2, 'pending', '2-3 business days', $3)
            RETURNING id
            """,
            product_uuid, quantity, session_uuid,
        )
    return {
        "status": "success",
        "restock_order_id": str(row["id"]),
        "product_id": str(product_uuid),
        "quantity": quantity,
        "estimated_arrival": "2-3 business days",
    }


@tool
async def apply_discount(
    product_ids: list[str], discount_pct: float, duration_hours: int
) -> dict:
    """
    Applies a discount to a list of products for a given duration.
    Args:
        product_ids: list of product UUID strings or SKUs
        discount_pct: discount percentage (e.g. 10.0 for 10%)
        duration_hours: how long the discount should run
    Returns dict with keys: status, promo_id, product_ids, discount_pct, expires_at
    """
    session_id = current_session_id.get() or None
    session_uuid = _uuid.UUID(session_id) if session_id else None

    now = datetime.now(timezone.utc)
    promo_id = f"PROMO-{now.strftime('%Y%m%d%H%M%S')}"
    expires_at = now + timedelta(hours=duration_hours)

    async with db_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO store.promotions
                (promo_id, product_ids, discount_pct, duration_hours, starts_at,
                 expires_at, status, created_by_session_id)
            VALUES ($1, $2::jsonb, $3, $4, $5, $6, 'active', $7)
            RETURNING id, promo_id, expires_at
            """,
            promo_id,
            json.dumps(product_ids),
            discount_pct,
            duration_hours,
            now,
            expires_at,
            session_uuid,
        )
    return {
        "status": "success",
        "promo_id": row["promo_id"],
        "product_ids": product_ids,
        "discount_pct": discount_pct,
        "duration_hours": duration_hours,
        "expires_at": row["expires_at"].isoformat(),
    }


@tool
async def pause_campaign(campaign_id: str, reason: str) -> dict:
    """
    Pauses an active marketing campaign.
    Args:
        campaign_id: the external campaign identifier (e.g. 'CAMP_042')
        reason: human-readable reason for pausing
    Returns dict with keys: status, campaign_id, paused_at
    """
    async with db_connection() as conn:
        row = await conn.fetchrow(
            """
            UPDATE store.campaigns
            SET
                status        = 'paused',
                paused_at     = NOW(),
                paused_reason = $2,
                updated_at    = NOW()
            WHERE external_id = $1
            RETURNING campaign_id, status, paused_at
            """,
            campaign_id, reason,
        )
    if row is None:
        raise ValueError(f"Campaign '{campaign_id}' not found")
    return {
        "status": "success",
        "campaign_id": campaign_id,
        "paused_at": row["paused_at"].isoformat(),
        "reason": reason,
    }


@tool
async def create_support_ticket(
    issue_description: str, priority: str = "medium"
) -> dict:
    """
    Creates a support ticket in the CRM for a reported issue.
    Args:
        issue_description: description of the issue
        priority: 'low', 'medium', 'high', or 'critical'
    Returns dict with keys: status, ticket_id, priority, created_at
    """
    if priority not in _VALID_PRIORITIES:
        raise ValueError(f"priority must be one of {_VALID_PRIORITIES}")
    session_id = current_session_id.get() or None
    session_uuid = _uuid.UUID(session_id) if session_id else None

    now = datetime.now(timezone.utc)
    ticket_id = f"TKT-{now.strftime('%Y%m%d%H%M%S')}"

    async with db_connection() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO store.support_tickets
                (ticket_id, issue_description, priority, status, created_by_session_id)
            VALUES ($1, $2, $3, 'open', $4)
            RETURNING id, ticket_id, created_at
            """,
            ticket_id, issue_description, priority, session_uuid,
        )
    return {
        "status": "success",
        "ticket_id": row["ticket_id"],
        "issue_description": issue_description,
        "priority": priority,
        "created_at": row["created_at"].isoformat(),
    }


@tool
async def relaunch_campaign(campaign_id: str) -> dict:
    """
    Relaunches (activates) a paused or inactive marketing campaign.
    Args:
        campaign_id: the external campaign identifier (e.g. 'CAMP_042')
    Returns dict with keys: status, campaign_id, relaunched_at
    """
    async with db_connection() as conn:
        row = await conn.fetchrow(
            """
            UPDATE store.campaigns
            SET
                status     = 'active',
                paused_at  = NULL,
                paused_reason = NULL,
                updated_at = NOW()
            WHERE external_id = $1
            RETURNING campaign_id, status, updated_at
            """,
            campaign_id,
        )
    if row is None:
        raise ValueError(f"Campaign '{campaign_id}' not found")
    return {
        "status": "success",
        "campaign_id": campaign_id,
        "relaunched_at": row["updated_at"].isoformat(),
    }

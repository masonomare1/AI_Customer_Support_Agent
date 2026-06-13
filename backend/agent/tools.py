"""LangGraph tool functions for refund eligibility and processing."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Union

from langchain_core.tools import tool

from db import get_connection

POLICY_PATH = Path(__file__).parent.parent / "data" / "refund_policy.md"
REFERENCE_DATE = datetime(2026, 6, 12)


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d")


def _days_since(d: Optional[datetime]) -> Optional[int]:
    if d is None:
        return None
    return (REFERENCE_DATE - d).days


@tool
def lookup_customer(customer_id: str) -> Dict[str, Any]:
    """Look up a customer profile by customer_id."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM customers WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        if not row:
            return {"error": f"Customer {customer_id} not found"}
        return dict(row)
    finally:
        conn.close()


@tool
def lookup_order(order_id: str) -> Dict[str, Any]:
    """Look up order details by order_id."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if not row:
            return {"error": f"Order {order_id} not found"}
        result = dict(row)
        result["defective"] = bool(result["defective"])
        return result
    finally:
        conn.close()


@tool
def get_refund_policy() -> str:
    """Return the full refund policy text."""
    return POLICY_PATH.read_text()


@tool
def check_refund_eligibility(order_id: str, reason: str) -> Dict[str, Any]:
    """
    Check whether an order qualifies for a refund based on policy rules.
    reason should describe the customer's claim (e.g. defective, change_of_mind, final_sale).
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if not row:
            return {"eligible": False, "rule_applied": "order_not_found", "details": f"Order {order_id} not found"}

        order = dict(row)
        order["defective"] = bool(order["defective"])
        reason_lower = reason.lower().replace(" ", "_")

        if order["order_status"] != "delivered":
            return {
                "eligible": False,
                "rule_applied": "order_not_delivered",
                "details": f"Order status is '{order['order_status']}', must be 'delivered'",
                "order_id": order_id,
            }

        delivery = _parse_date(order["delivery_date"])
        days = _days_since(delivery)

        if "defective" in reason_lower or "damaged" in reason_lower or order["defective"]:
            if days is not None and days <= 90:
                return {
                    "eligible": True,
                    "rule_applied": "defective_item",
                    "details": "Defective item — full refund eligible within 90 days",
                    "order_id": order_id,
                    "refund_type": "full",
                    "restocking_fee_pct": 0,
                }
            return {
                "eligible": False,
                "rule_applied": "defective_outside_window",
                "details": "Defective claim outside 90-day window",
                "order_id": order_id,
            }

        if order["category"] == "final_sale":
            return {
                "eligible": False,
                "rule_applied": "final_sale",
                "details": "Final Sale items are non-refundable unless defective",
                "order_id": order_id,
            }

        if order["category"] == "digital":
            return {
                "eligible": False,
                "rule_applied": "digital_goods",
                "details": "Digital goods are non-refundable once delivered/downloaded",
                "order_id": order_id,
            }

        if days is None or days > 30:
            return {
                "eligible": False,
                "rule_applied": "outside_30_day_window",
                "details": f"Request is {days} days after delivery; max 30 days allowed",
                "order_id": order_id,
            }

        if "change" in reason_lower or "mind" in reason_lower:
            return {
                "eligible": True,
                "rule_applied": "change_of_mind",
                "details": "Change of mind — eligible with 15% restocking fee if unused/unopened",
                "order_id": order_id,
                "refund_type": "partial",
                "restocking_fee_pct": 15,
            }

        return {
            "eligible": True,
            "rule_applied": "standard_refund",
            "details": "Order meets standard refund criteria within 30-day window",
            "order_id": order_id,
            "refund_type": "full",
            "restocking_fee_pct": 0,
        }
    finally:
        conn.close()


@tool
def check_refund_history(customer_id: str) -> Dict[str, Any]:
    """Check for prior approved refunds in the last 30 days for abuse detection."""
    conn = get_connection()
    try:
        cutoff = (REFERENCE_DATE - timedelta(days=30)).strftime("%Y-%m-%d")
        rows = conn.execute(
            """
            SELECT * FROM refund_logs
            WHERE customer_id = ? AND decision = 'approved' AND created_at >= ?
            ORDER BY created_at DESC
            """,
            (customer_id, cutoff),
        ).fetchall()
        refunds = [dict(r) for r in rows]
        return {
            "customer_id": customer_id,
            "recent_refunds": refunds,
            "count": len(refunds),
            "abuse_flag": len(refunds) >= 1,
            "message": "Customer has prior refund in last 30 days" if refunds else "No recent refunds",
        }
    finally:
        conn.close()


@tool
def calculate_refund_amount(order_id: str, eligibility_result: str) -> Dict[str, Any]:
    """
    Calculate refund amount based on order price and eligibility result JSON.
    eligibility_result should be the JSON string returned by check_refund_eligibility.
    """
    try:
        eligibility = json.loads(eligibility_result) if isinstance(eligibility_result, str) else eligibility_result
    except json.JSONDecodeError:
        return {"error": "Invalid eligibility_result JSON"}

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT price FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if not row:
            return {"error": f"Order {order_id} not found"}

        price = float(row["price"])
        fee_pct = eligibility.get("restocking_fee_pct", 0)
        fee_amount = round(price * fee_pct / 100, 2)
        refund_amount = round(price - fee_amount, 2)

        return {
            "order_id": order_id,
            "original_price": price,
            "restocking_fee_pct": fee_pct,
            "restocking_fee_amount": fee_amount,
            "refund_amount": refund_amount,
        }
    finally:
        conn.close()


@tool
def process_refund(order_id: str, amount: Union[float, int, str], decision: str) -> Dict[str, Any]:
    """
    Record a refund decision in the database.
    amount is the refund amount (use 0 for denials). decision must be 'approved' or 'denied'.

    NOTE: This tool is the authoritative policy engine. If an 'approved' decision
    would violate a hard policy rule (an order refunded twice, or a second approved
    refund for the same customer inside the 30-day window) the approval is BLOCKED
    and recorded as a denial instead. Respect and relay whatever this tool returns.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT customer_id FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if not row:
            return {"error": f"Order {order_id} not found"}

        customer_id = row["customer_id"]
        decision_norm = decision.strip().lower()

        # Models occasionally pass amount as a string (e.g. "0"); coerce defensively.
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = 0.0

        if decision_norm == "approved":
            block_reason = _approval_block_reason(conn, order_id, customer_id)
            if block_reason:
                # Deterministically override the LLM: record a denial, never a
                # second approval. This is what "holds the line" on policy.
                conn.execute(
                    """
                    INSERT INTO refund_logs (order_id, customer_id, amount, decision, reason)
                    VALUES (?, ?, ?, 'denied', ?)
                    """,
                    (order_id, customer_id, 0, f"Policy engine blocked approval: {block_reason}"),
                )
                conn.commit()
                return {
                    "success": False,
                    "blocked": True,
                    "enforced_decision": "denied",
                    "order_id": order_id,
                    "customer_id": customer_id,
                    "policy_violation": block_reason,
                    "message": (
                        f"APPROVAL BLOCKED BY POLICY ENGINE: {block_reason} "
                        "A denial has been recorded. Tell the customer the refund is "
                        "DENIED and explain this specific rule."
                    ),
                }

        conn.execute(
            """
            INSERT INTO refund_logs (order_id, customer_id, amount, decision, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (order_id, customer_id, amount, decision_norm, f"Agent decision: {decision_norm}"),
        )
        conn.commit()
        return {
            "success": True,
            "order_id": order_id,
            "customer_id": customer_id,
            "amount": amount,
            "decision": decision_norm,
            "message": f"Refund {decision_norm} recorded for order {order_id}",
        }
    finally:
        conn.close()


def _approval_block_reason(conn, order_id: str, customer_id: str) -> Optional[str]:
    """Return a policy reason to block an approval, or None if it's allowed."""
    already_refunded = conn.execute(
        "SELECT 1 FROM refund_logs WHERE order_id = ? AND decision = 'approved' LIMIT 1",
        (order_id,),
    ).fetchone()
    if already_refunded:
        return (
            f"Order {order_id} has already received an approved refund; "
            "the same order cannot be refunded twice."
        )

    cutoff = (REFERENCE_DATE - timedelta(days=30)).strftime("%Y-%m-%d")
    recent = conn.execute(
        """
        SELECT COUNT(*) AS c FROM refund_logs
        WHERE customer_id = ? AND decision = 'approved' AND created_at >= ?
        """,
        (customer_id, cutoff),
    ).fetchone()["c"]
    if recent >= 1:
        return (
            f"Customer {customer_id} already has an approved refund within the last "
            "30 days (policy: one approved refund per customer per rolling 30-day window)."
        )

    return None


ALL_TOOLS = [
    lookup_customer,
    lookup_order,
    get_refund_policy,
    check_refund_eligibility,
    check_refund_history,
    calculate_refund_amount,
    process_refund,
]

TOOL_BY_NAME = {t.name: t for t in ALL_TOOLS}

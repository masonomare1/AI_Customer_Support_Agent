"""
Deterministic policy-enforcement tests for process_refund.

These verify that the *code* (not the LLM) is the source of truth for the two
abuse rules in the refund policy:

  * An order can never be refunded twice.
  * A customer may receive at most one approved refund per rolling 30-day window.

Run with:  python tests/test_refund_enforcement.py
"""

import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import db  # noqa: E402

# Point the whole app at a throwaway database BEFORE anything opens a connection.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
db.DB_PATH = Path(_tmp.name)

from db import get_connection, init_db  # noqa: E402
import agent.tools as tools  # noqa: E402


def _seed():
    init_db()
    conn = get_connection()
    conn.execute("DELETE FROM refund_logs")
    conn.execute("DELETE FROM orders")
    conn.execute("DELETE FROM customers")
    conn.execute(
        "INSERT INTO customers VALUES ('C001','Alice','a@x.com','2023-01-01','gold',5)"
    )
    # Two delivered, defective orders for the same customer, inside every window.
    for oid in ("O001", "O002"):
        conn.execute(
            "INSERT INTO orders (order_id, customer_id, item_name, category, price,"
            " order_date, delivery_date, order_status, defective)"
            " VALUES (?, 'C001', 'Headphones', 'electronics', 149.99,"
            " '2026-05-20', '2026-06-07', 'delivered', 1)",
            (oid,),
        )
    conn.commit()
    conn.close()


def _count(decision=None):
    conn = get_connection()
    try:
        if decision:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM refund_logs WHERE decision = ?", (decision,)
            ).fetchone()["c"]
        return conn.execute("SELECT COUNT(*) AS c FROM refund_logs").fetchone()["c"]
    finally:
        conn.close()


def test_first_approval_succeeds():
    _seed()
    r = tools.process_refund.invoke(
        {"order_id": "O001", "amount": 149.99, "decision": "approved"}
    )
    assert r.get("success") is True, f"first approval should succeed: {r}"
    assert _count("approved") == 1


def test_duplicate_order_approval_is_blocked():
    _seed()
    tools.process_refund.invoke(
        {"order_id": "O001", "amount": 149.99, "decision": "approved"}
    )
    r = tools.process_refund.invoke(
        {"order_id": "O001", "amount": 149.99, "decision": "approved"}
    )
    assert r.get("blocked") is True, f"second approval of same order must be blocked: {r}"
    assert _count("approved") == 1, "no second approval may be recorded"
    assert _count("denied") >= 1, "blocked attempt must be recorded as denied"


def test_abuse_window_blocks_second_order():
    _seed()
    tools.process_refund.invoke(
        {"order_id": "O001", "amount": 149.99, "decision": "approved"}
    )
    # Different order, same customer, still inside the 30-day window -> must block.
    r = tools.process_refund.invoke(
        {"order_id": "O002", "amount": 149.99, "decision": "approved"}
    )
    assert r.get("blocked") is True, f"second refund within 30 days must be blocked: {r}"
    assert _count("approved") == 1


def test_denials_are_never_blocked():
    _seed()
    r = tools.process_refund.invoke(
        {"order_id": "O001", "amount": 0, "decision": "denied"}
    )
    assert r.get("success") is True, f"denials must always record: {r}"
    assert _count("denied") == 1


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL  {name}: {exc}")
    if failures:
        print(f"\n{failures} test(s) failed")
        sys.exit(1)
    print("\nAll enforcement tests passed")

"""Seed SQLite with mock customers, orders, and one prior refund log."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import get_connection, init_db

TODAY = datetime(2026, 6, 12)

CUSTOMERS = [
    ("C001", "Alice Johnson", "alice@email.com", "2023-01-15", "gold", 12),
    ("C002", "Bob Smith", "bob@email.com", "2023-03-20", "silver", 8),
    ("C003", "Carol Davis", "carol@email.com", "2023-06-10", "bronze", 5),
    ("C004", "David Wilson", "david@email.com", "2023-08-05", "gold", 15),
    ("C005", "Eva Martinez", "eva@email.com", "2023-09-12", "silver", 6),
    ("C006", "Frank Lee", "frank@email.com", "2023-11-01", "bronze", 3),
    ("C007", "Grace Kim", "grace@email.com", "2024-01-20", "gold", 10),
    ("C008", "Henry Brown", "henry@email.com", "2024-03-15", "silver", 4),
    ("C009", "Ivy Chen", "ivy@email.com", "2024-05-08", "bronze", 2),
    ("C010", "Jack Taylor", "jack@email.com", "2024-07-22", "gold", 7),
    ("C011", "Kate Anderson", "kate@email.com", "2024-09-30", "silver", 5),
    ("C012", "Leo Garcia", "leo@email.com", "2024-11-18", "bronze", 1),
    ("C013", "Mia Robinson", "mia@email.com", "2025-01-05", "gold", 9),
    ("C014", "Noah White", "noah@email.com", "2025-03-12", "silver", 3),
    ("C015", "Olivia Harris", "olivia@email.com", "2025-05-01", "bronze", 2),
]

# (order_id, customer_id, item_name, category, price, days_ago_delivered, order_status, defective)
ORDERS = [
    ("O001", "C001", "Wireless Headphones Pro", "electronics", 149.99, 5, "delivered", False),
    ("O002", "C001", "Summer Dress Collection", "clothing", 79.50, 45, "delivered", False),
    ("O003", "C002", "Premium E-Book Bundle", "digital", 29.99, 10, "delivered", False),
    ("O004", "C002", "Smart Watch Series 5", "electronics", 299.00, 20, "delivered", True),
    ("O005", "C003", "Clearance Sneakers", "final_sale", 59.99, 8, "delivered", False),
    ("O006", "C003", "Bluetooth Speaker Mini", "electronics", 45.00, 60, "delivered", False),
    ("O007", "C004", "Designer Jacket (Final Sale)", "final_sale", 189.00, 15, "delivered", False),
    ("O008", "C004", "USB-C Hub Adapter", "electronics", 34.99, 3, "shipped", False),
    ("O009", "C005", "Organic Cotton T-Shirt", "clothing", 24.99, 12, "delivered", False),
    ("O010", "C005", "Noise Cancelling Earbuds", "electronics", 199.99, 25, "delivered", True),
    ("O011", "C006", "Limited Edition Hoodie", "final_sale", 89.99, 18, "delivered", False),
    ("O012", "C007", "4K Webcam HD", "electronics", 129.00, 7, "delivered", False),
    ("O013", "C007", "Running Shoes Elite", "clothing", 119.99, 90, "delivered", False),
    ("O014", "C008", "Cloud Storage 1TB (Annual)", "digital", 49.99, 14, "delivered", False),
    ("O015", "C009", "Kitchen Blender Pro", "general", 79.00, 22, "processing", False),
    ("O016", "C010", "Leather Wallet Classic", "general", 45.00, 4, "delivered", False),
    ("O017", "C011", "Fitness Tracker Band", "electronics", 69.99, 35, "delivered", False),
    ("O018", "C012", "Winter Coat Premium", "clothing", 159.00, 2, "delivered", False),
    ("O019", "C013", "Portable Charger 20000mAh", "electronics", 39.99, 11, "delivered", False),
    ("O020", "C014", "Yoga Mat Deluxe", "general", 29.99, 6, "delivered", False),
]


def _date_str(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def seed() -> None:
    init_db()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM refund_logs")
        conn.execute("DELETE FROM orders")
        conn.execute("DELETE FROM customers")

        conn.executemany(
            """
            INSERT INTO customers (customer_id, name, email, signup_date, loyalty_tier, total_orders)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            CUSTOMERS,
        )

        order_rows = []
        for oid, cid, item, cat, price, days_ago, status, defective in ORDERS:
            delivery = _date_str(days_ago) if status == "delivered" else None
            order_date = _date_str(days_ago + 3)
            order_rows.append((oid, cid, item, cat, price, order_date, delivery, status, int(defective)))

        conn.executemany(
            """
            INSERT INTO orders
            (order_id, customer_id, item_name, category, price, order_date, delivery_date, order_status, defective)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            order_rows,
        )

        # C001 had an approved refund 10 days ago — flags repeat abuse window
        conn.execute(
            """
            INSERT INTO refund_logs (order_id, customer_id, amount, decision, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("O001", "C001", 149.99, "approved", "Defective item", _date_str(10)),
        )

        conn.commit()
        print(f"Seeded {len(CUSTOMERS)} customers, {len(ORDERS)} orders, and 1 refund log.")
    finally:
        conn.close()


if __name__ == "__main__":
    seed()

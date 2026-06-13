import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "support.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS customers (
                customer_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                signup_date TEXT NOT NULL,
                loyalty_tier TEXT NOT NULL,
                total_orders INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                item_name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL NOT NULL,
                order_date TEXT NOT NULL,
                delivery_date TEXT,
                order_status TEXT NOT NULL,
                defective INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
            );

            CREATE TABLE IF NOT EXISTS refund_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                amount REAL,
                decision TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (order_id) REFERENCES orders(order_id),
                FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

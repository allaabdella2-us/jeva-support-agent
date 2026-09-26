"""
SUPPORT DATABASE (SQLite)

Fake data that backs the support agent's tools.

Tables:
    customers          who the member is
    orders             what they ordered and where it is
    charges            what they were billed (A-101 has a duplicate charge)
    refunds            refund requests created by create_refund
    password_resets    reset links created by reset_password
    human_cases        cases created by create_human_case
    tool_audit_log     every tool request the gateway saw, allowed or not
    tickets            MEMORY: one row per support conversation
    ticket_messages    MEMORY: every customer and agent turn in a ticket

Usage:
    python support_db.py            create support.db if missing
    python support_db.py --reset    rebuild it from scratch
    python support_db.py --show     print every table

The agent imports the helper functions at the bottom of this file.
Only Python touches the database. Claude never does.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import env  # noqa: F401  loads backend/.env before SUPPORT_DB_PATH is read

DB_PATH = os.environ.get(
    "SUPPORT_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "support.db"),
)

# ============================================================
# SCHEMA
# ============================================================
SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    plan        TEXT NOT NULL CHECK (plan IN ('basic', 'plus', 'premium')),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id                  TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL REFERENCES customers(id),
    status              TEXT NOT NULL CHECK (status IN
                            ('processing', 'shipped', 'delivered', 'cancelled', 'returned')),
    carrier             TEXT,
    tracking_number     TEXT,
    estimated_delivery  TEXT,
    delivered_at        TEXT,
    total_cents         INTEGER NOT NULL CHECK (total_cents >= 0),
    item_summary        TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS charges (
    id           TEXT PRIMARY KEY,
    customer_id  TEXT NOT NULL REFERENCES customers(id),
    order_id     TEXT NOT NULL REFERENCES orders(id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    status       TEXT NOT NULL CHECK (status IN ('settled', 'pending', 'failed', 'refunded')),
    charged_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refunds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    refund_ref      TEXT UNIQUE,
    customer_id     TEXT NOT NULL REFERENCES customers(id),
    order_id        TEXT NOT NULL REFERENCES orders(id),
    charge_id       TEXT NOT NULL REFERENCES charges(id),
    amount_cents    INTEGER NOT NULL,
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN
                        ('submitted', 'pending_approval', 'completed', 'rejected')),
    ticket_id       TEXT,
    created_at      TEXT NOT NULL,
    -- idempotency: a charge can only be refunded once
    UNIQUE (charge_id)
);

CREATE TABLE IF NOT EXISTS password_resets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    token_hash  TEXT NOT NULL,          -- never store or return the raw token
    sent_to     TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('sent', 'used', 'expired')),
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS human_cases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_ref    TEXT UNIQUE,
    ticket_id   TEXT NOT NULL,
    customer_id TEXT REFERENCES customers(id),
    reason      TEXT NOT NULL,
    priority    TEXT NOT NULL CHECK (priority IN ('normal', 'high')),
    status      TEXT NOT NULL CHECK (status IN ('queued', 'assigned', 'resolved')),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_audit_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id      TEXT NOT NULL,
    customer_id    TEXT,
    tool_name      TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    allowed        INTEGER NOT NULL CHECK (allowed IN (0, 1)),
    result_json    TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

-- ============ MEMORY ============
CREATE TABLE IF NOT EXISTS tickets (
    id          TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(id),
    status      TEXT NOT NULL CHECK (status IN
                    ('open', 'awaiting_customer', 'escalated', 'quarantined', 'closed')),
    topic       TEXT,
    route       TEXT,
    specialist  TEXT,
    priority    TEXT CHECK (priority IN ('normal', 'high')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   TEXT NOT NULL REFERENCES tickets(id),
    role        TEXT NOT NULL CHECK (role IN ('customer', 'agent', 'system')),
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_customer  ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_tickets_customer ON tickets(customer_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_ticket  ON ticket_messages(ticket_id, id);
CREATE INDEX IF NOT EXISTS idx_charges_order    ON charges(order_id);
CREATE INDEX IF NOT EXISTS idx_audit_ticket     ON tool_audit_log(ticket_id);
"""

# ============================================================
# FAKE SEED DATA
# ============================================================
CUSTOMERS = [
    ("CUST-1001", "Jane Smith",    "jane@example.com",   "premium", "2023-04-11T09:15:00Z"),
    ("CUST-1002", "Marcus Lee",    "marcus@example.com", "basic",   "2024-01-22T14:02:00Z"),
    ("CUST-1003", "Priya Patel",   "priya@example.com",  "plus",    "2022-11-03T17:45:00Z"),
    ("CUST-1004", "Diego Alvarez", "diego@example.com",  "premium", "2025-06-30T08:30:00Z"),
    ("CUST-1005", "Hannah Kim",    "hannah@example.com", "basic",   "2026-02-14T12:00:00Z"),
]

# id, customer, status, carrier, tracking, est_delivery, delivered_at, total, items, created
ORDERS = [
    ("A-104", "CUST-1001", "shipped",    "UPS",   "1Z999AA",      "2026-09-27", None,         4250, "Blood pressure monitor",            "2026-09-21T10:05:00Z"),
    ("A-101", "CUST-1001", "delivered",  "FedEx", "7712 3456 01", None,         "2026-09-12", 6499, "Diabetic test strips (100 count)",  "2026-09-08T16:20:00Z"),
    ("A-095", "CUST-1001", "delivered",  "USPS",  "9400 1112 22", None,         "2026-08-02", 1899, "Compression socks (2 pairs)",       "2026-07-28T11:40:00Z"),
    ("A-110", "CUST-1002", "processing", None,    None,           "2026-10-01", None,         3100, "Digital thermometer",               "2026-09-24T19:12:00Z"),
    ("A-107", "CUST-1002", "delivered",  "UPS",   "1Z888BB",      None,         "2026-09-18", 2275, "First aid kit",                     "2026-09-14T09:00:00Z"),
    ("A-112", "CUST-1003", "shipped",    "FedEx", "7712 9988 44", "2026-09-29", None,         8900, "Nebulizer and tubing",              "2026-09-23T13:25:00Z"),
    ("A-098", "CUST-1003", "returned",   "UPS",   "1Z777CC",      None,         "2026-08-20", 5400, "Knee brace",                        "2026-08-15T15:10:00Z"),
    ("A-115", "CUST-1004", "shipped",    "USPS",  "9400 5566 77", "2026-09-26", None,         2999, "Pill organizer and refills",        "2026-09-22T07:55:00Z"),
    ("A-103", "CUST-1004", "cancelled",  None,    None,           None,         None,         15999, "Mobility walker",                  "2026-09-10T18:30:00Z"),
    ("A-116", "CUST-1005", "processing", None,    None,           "2026-10-03", None,         1250, "Hand sanitizer (6 pack)",           "2026-09-25T08:10:00Z"),
]

# A-101 was charged twice, which is the "Charged twice" demo scenario.
CHARGES = [
    ("CH-5001", "CUST-1001", "A-104", 4250,  "settled", "2026-09-21T10:06:00Z"),
    ("CH-4990", "CUST-1001", "A-101", 6499,  "settled", "2026-09-08T16:21:00Z"),
    ("CH-4991", "CUST-1001", "A-101", 6499,  "settled", "2026-09-08T16:21:40Z"),
    ("CH-4870", "CUST-1001", "A-095", 1899,  "settled", "2026-07-28T11:41:00Z"),
    ("CH-5010", "CUST-1002", "A-110", 3100,  "pending", "2026-09-24T19:13:00Z"),
    ("CH-4995", "CUST-1002", "A-107", 2275,  "settled", "2026-09-14T09:01:00Z"),
    ("CH-5004", "CUST-1003", "A-112", 8900,  "settled", "2026-09-23T13:26:00Z"),
    ("CH-4920", "CUST-1003", "A-098", 5400,  "refunded", "2026-08-15T15:11:00Z"),
    ("CH-5002", "CUST-1004", "A-115", 2999,  "settled", "2026-09-22T07:56:00Z"),
    ("CH-4980", "CUST-1004", "A-103", 15999, "refunded", "2026-09-10T18:31:00Z"),
]

# Past activity so the tables aren't empty on first look.
PAST_REFUNDS = [
    ("REF-89990", "CUST-1003", "A-098", "CH-4920", 5400,  "Item returned",   "completed", "TICKET-11870", "2026-08-21T10:00:00Z"),
    ("REF-89995", "CUST-1004", "A-103", "CH-4980", 15999, "Order cancelled", "completed", "TICKET-12011", "2026-09-10T19:05:00Z"),
]
PAST_CASES = [
    ("CASE-49990", "TICKET-12002", "CUST-1002", "Asked about coverage for a thermometer", "normal", "resolved", "2026-09-03T14:00:00Z"),
    ("CASE-49995", "TICKET-12300", "CUST-1001", "Repeat contact about order A-104 with no tracking", "high", "queued", "2026-09-24T18:06:00Z"),
]

# ------------------------------------------------------------
# MEMORY SEED
# Jane has contacted support three times about A-104 this week,
# so "I've contacted support three times" can be checked
# against real history instead of taken on trust.
# ------------------------------------------------------------
# id, customer, status, topic, route, specialist, priority, created, updated
PAST_TICKETS = [
    ("TICKET-11650", "CUST-1001", "closed",    "orders",  "specialist",   "orders_specialist",  "normal", "2026-07-30T10:00:00Z", "2026-07-30T10:02:00Z"),
    ("TICKET-12201", "CUST-1001", "closed",    "orders",  "specialist",   "orders_specialist",  "normal", "2026-09-22T09:10:00Z", "2026-09-22T09:11:00Z"),
    ("TICKET-12250", "CUST-1001", "closed",    "orders",  "specialist",   "orders_specialist",  "normal", "2026-09-23T15:40:00Z", "2026-09-23T15:41:00Z"),
    ("TICKET-12300", "CUST-1001", "escalated", "orders",  "human_review", None,                 "high",   "2026-09-24T18:05:00Z", "2026-09-24T18:06:00Z"),
    ("TICKET-12002", "CUST-1002", "closed",    "billing", "human_review", None,                 "normal", "2026-09-03T13:55:00Z", "2026-09-04T10:00:00Z"),
    ("TICKET-11870", "CUST-1003", "closed",    "billing", "specialist",   "billing_specialist", "normal", "2026-08-21T09:58:00Z", "2026-08-21T10:00:00Z"),
    ("TICKET-12011", "CUST-1004", "closed",    "orders",  "specialist",   "orders_specialist",  "normal", "2026-09-10T19:00:00Z", "2026-09-10T19:05:00Z"),
]
# ticket, role, content, created
PAST_MESSAGES = [
    ("TICKET-11650", "customer", "My compression socks arrived today. Thanks!", "2026-07-30T10:00:00Z"),
    ("TICKET-11650", "agent",    "Glad they arrived safely, Jane. Enjoy!", "2026-07-30T10:02:00Z"),
    ("TICKET-12201", "customer", "Hi, can you tell me when order A-104 will arrive?", "2026-09-22T09:10:00Z"),
    ("TICKET-12201", "agent",    "Thanks for reaching out. Your order is being prepared and will ship soon.", "2026-09-22T09:11:00Z"),
    ("TICKET-12250", "customer", "Following up on order A-104. I still don't have a tracking number.", "2026-09-23T15:40:00Z"),
    ("TICKET-12250", "agent",    "We're looking into this and will update you shortly.", "2026-09-23T15:41:00Z"),
    ("TICKET-12300", "customer", "This is the third time I'm asking. Where is order A-104?", "2026-09-24T18:05:00Z"),
    ("TICKET-12300", "system",   "Escalated to a person: case CASE-49995.", "2026-09-24T18:06:00Z"),
    ("TICKET-12002", "customer", "Is a digital thermometer covered by my plan?", "2026-09-03T13:55:00Z"),
    ("TICKET-12002", "system",   "Escalated to a person: case CASE-49990.", "2026-09-03T14:00:00Z"),
    ("TICKET-11870", "customer", "I returned the knee brace. Can I get a refund?", "2026-08-21T09:58:00Z"),
    ("TICKET-11870", "agent",    "Your refund REF-89990 has been submitted.", "2026-08-21T10:00:00Z"),
    ("TICKET-12011", "customer", "Please cancel order A-103 and refund me.", "2026-09-10T19:00:00Z"),
    ("TICKET-12011", "agent",    "Order A-103 is cancelled and refund REF-89995 is on its way.", "2026-09-10T19:05:00Z"),
]

# ============================================================
# CONNECTION HELPERS
# ============================================================
def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def connect(path: str = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, roll back on error."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: str = DB_PATH, reset: bool = False) -> None:
    if reset and os.path.exists(path):
        os.remove(path)
    fresh = not os.path.exists(path)
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        if not fresh:
            return
        conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?)", CUSTOMERS)
        conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?)", ORDERS)
        conn.executemany("INSERT INTO charges VALUES (?,?,?,?,?,?)", CHARGES)
        conn.executemany(
            """INSERT INTO refunds (refund_ref, customer_id, order_id, charge_id, amount_cents,
                                    reason, status, ticket_id, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            PAST_REFUNDS,
        )
        conn.executemany(
            """INSERT INTO human_cases (case_ref, ticket_id, customer_id, reason, priority,
                                        status, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            PAST_CASES,
        )
        conn.executemany("INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?,?)", PAST_TICKETS)
        conn.executemany(
            "INSERT INTO ticket_messages (ticket_id, role, content, created_at) VALUES (?,?,?,?)",
            PAST_MESSAGES,
        )
        # New refunds and cases get refs starting at REF-90001 / CASE-50001.
        conn.execute("UPDATE sqlite_sequence SET seq = 90000 WHERE name = 'refunds'")
        conn.execute("UPDATE sqlite_sequence SET seq = 50000 WHERE name = 'human_cases'")

# ============================================================
# READ HELPERS
# ============================================================
def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def find_customer_by_email(email: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM customers WHERE lower(email) = lower(?)", (email,)
        ).fetchone()
    return row_to_dict(row)


def get_customer_by_id(customer_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    return row_to_dict(row)


def list_orders(customer_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, status, carrier, tracking_number, estimated_delivery,
                      delivered_at, total_cents, item_summary, created_at
               FROM orders WHERE customer_id = ? ORDER BY created_at DESC""",
            (customer_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_order_for_customer(customer_id: str, order_id: str) -> dict[str, Any] | None:
    """Ownership is enforced in the query: another member's order is 'not found'."""
    with connect() as conn:
        row = conn.execute(
            """SELECT id, status, carrier, tracking_number, estimated_delivery,
                      delivered_at, item_summary
               FROM orders WHERE id = ? AND customer_id = ?""",
            (order_id.strip().upper(), customer_id),
        ).fetchone()
    return row_to_dict(row)


def find_refundable_charge(customer_id: str, order_id: str) -> dict[str, Any] | None:
    """
    Most recent settled charge on the order that has not been refunded yet.
    With a duplicate charge this returns the second (duplicate) one.
    """
    with connect() as conn:
        row = conn.execute(
            """SELECT c.* FROM charges c
               LEFT JOIN refunds r ON r.charge_id = c.id
               WHERE c.customer_id = ? AND c.order_id = ?
                 AND c.status = 'settled' AND r.id IS NULL
               ORDER BY c.charged_at DESC LIMIT 1""",
            (customer_id, order_id.strip().upper()),
        ).fetchone()
    return row_to_dict(row)


def count_settled_charges(customer_id: str, order_id: str) -> int:
    with connect() as conn:
        (n,) = conn.execute(
            """SELECT COUNT(*) FROM charges
               WHERE customer_id = ? AND order_id = ? AND status IN ('settled', 'refunded')""",
            (customer_id, order_id.strip().upper()),
        ).fetchone()
    return n

# ============================================================
# WRITE HELPERS (side effects)
# ============================================================
def insert_refund(
    customer_id: str, order_id: str, charge_id: str, amount_cents: int,
    reason: str, status: str, ticket_id: str,
) -> dict[str, Any]:
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO refunds (customer_id, order_id, charge_id, amount_cents,
                                    reason, status, ticket_id, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (customer_id, order_id, charge_id, amount_cents, reason, status, ticket_id, now_iso()),
        )
        ref = f"REF-{cur.lastrowid:05d}"
        conn.execute("UPDATE refunds SET refund_ref = ? WHERE id = ?", (ref, cur.lastrowid))
        row = conn.execute("SELECT * FROM refunds WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def get_refund_for_ticket(ticket_id: str, order_id: str) -> dict[str, Any] | None:
    """Idempotency: the same ticket asking twice for the same order gets the same refund."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM refunds WHERE ticket_id = ? AND order_id = ?",
            (ticket_id, order_id.strip().upper()),
        ).fetchone()
    return row_to_dict(row)


def insert_password_reset(customer_id: str, sent_to: str, raw_token: str,
                          ttl_minutes: int = 30) -> dict[str, Any]:
    created = datetime.now(timezone.utc).replace(microsecond=0)
    expires = created + timedelta(minutes=ttl_minutes)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO password_resets (customer_id, token_hash, sent_to, status,
                                            created_at, expires_at)
               VALUES (?,?,?,?,?,?)""",
            (customer_id, token_hash, sent_to, "sent",
             created.isoformat().replace("+00:00", "Z"),
             expires.isoformat().replace("+00:00", "Z")),
        )
        row = conn.execute(
            "SELECT id, customer_id, sent_to, status, created_at, expires_at "
            "FROM password_resets WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return dict(row)


def insert_human_case(ticket_id: str, customer_id: str | None,
                      reason: str, priority: str) -> dict[str, Any]:
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO human_cases (ticket_id, customer_id, reason, priority, status, created_at)
               VALUES (?,?,?,?,?,?)""",
            (ticket_id, customer_id, reason, priority, "queued", now_iso()),
        )
        ref = f"CASE-{cur.lastrowid:05d}"
        conn.execute("UPDATE human_cases SET case_ref = ? WHERE id = ?", (ref, cur.lastrowid))
        row = conn.execute("SELECT * FROM human_cases WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def log_tool_call(ticket_id: str, customer_id: str | None, tool_name: str,
                  arguments: dict[str, Any], allowed: bool, result: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO tool_audit_log (ticket_id, customer_id, tool_name, arguments_json,
                                           allowed, result_json, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (ticket_id, customer_id, tool_name, json.dumps(arguments),
             int(allowed), json.dumps(result), now_iso()),
        )

# ============================================================
# MEMORY HELPERS
#
# Python decides what is remembered and what the model sees.
# ============================================================
TICKET_FIELDS = {"status", "topic", "route", "specialist", "priority"}


def get_ticket(ticket_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return row_to_dict(row)


def ensure_ticket(ticket_id: str, customer_id: str | None) -> dict[str, Any]:
    """Create the ticket on first contact; return the stored row."""
    ts = now_iso()
    with connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO tickets (id, customer_id, status, created_at, updated_at)
               VALUES (?,?,?,?,?)""",
            (ticket_id, customer_id, "open", ts, ts),
        )
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return dict(row)


def update_ticket(ticket_id: str, **fields: Any) -> None:
    bad = set(fields) - TICKET_FIELDS
    if bad:
        raise ValueError(f"Cannot update ticket fields: {bad}")
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(
            f"UPDATE tickets SET {cols}, updated_at = ? WHERE id = ?",
            (*fields.values(), now_iso(), ticket_id),
        )


def add_message(ticket_id: str, role: str, content: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO ticket_messages (ticket_id, role, content, created_at) VALUES (?,?,?,?)",
            (ticket_id, role, content, now_iso()),
        )
        conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (now_iso(), ticket_id))


def get_messages(ticket_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """The last `limit` turns of one ticket, oldest first."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT role, content, created_at FROM (
                   SELECT * FROM ticket_messages WHERE ticket_id = ?
                   ORDER BY id DESC LIMIT ?
               ) ORDER BY id ASC""",
            (ticket_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def _snippet(text: str | None, n: int = 160) -> str | None:
    if text is None:
        return None
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def get_customer_history(
    customer_id: str,
    exclude_ticket_id: str | None = None,
    days: int = 30,
    max_tickets: int = 5,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """
    A compact, bounded summary of the customer's recent support history.
    Snippets only, never full transcripts of other tickets.
    """
    as_of = as_of or datetime.now(timezone.utc)
    cutoff = (as_of - timedelta(days=days)).isoformat().replace("+00:00", "Z")
    week = (as_of - timedelta(days=7)).isoformat().replace("+00:00", "Z")
    exclude = exclude_ticket_id or ""
    with connect() as conn:
        tickets = conn.execute(
            """SELECT t.id, t.status, t.topic, t.route, t.created_at,
                      (SELECT content FROM ticket_messages m
                        WHERE m.ticket_id = t.id AND m.role = 'customer'
                        ORDER BY m.id ASC LIMIT 1) AS first_customer_message,
                      (SELECT content FROM ticket_messages m
                        WHERE m.ticket_id = t.id AND m.role IN ('agent', 'system')
                        ORDER BY m.id DESC LIMIT 1) AS last_outcome
               FROM tickets t
               WHERE t.customer_id = ? AND t.id != ? AND t.created_at >= ?
               ORDER BY t.created_at DESC LIMIT ?""",
            (customer_id, exclude, cutoff, max_tickets),
        ).fetchall()
        (contacts_7d,) = conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE customer_id = ? AND id != ? AND created_at >= ?",
            (customer_id, exclude, week),
        ).fetchone()
        open_cases = conn.execute(
            """SELECT case_ref, ticket_id, reason, priority, created_at FROM human_cases
               WHERE customer_id = ? AND status != 'resolved' ORDER BY created_at DESC""",
            (customer_id,),
        ).fetchall()
        refunds = conn.execute(
            """SELECT refund_ref, order_id, amount_cents, status, created_at FROM refunds
               WHERE customer_id = ? AND created_at >= ? ORDER BY created_at DESC""",
            (customer_id, cutoff),
        ).fetchall()
    return {
        "window_days": days,
        "contacts_last_7_days": contacts_7d,
        "recent_tickets": [
            {
                "id": t["id"],
                "created_at": t["created_at"],
                "status": t["status"],
                "topic": t["topic"],
                "customer_said": _snippet(t["first_customer_message"]),
                "outcome": _snippet(t["last_outcome"]),
            }
            for t in tickets
        ],
        "open_cases": [dict(c) for c in open_cases],
        "recent_refunds": [dict(r) for r in refunds],
    }

# ============================================================
# CLI
# ============================================================
def show_tables(path: str = DB_PATH) -> None:
    tables = ["customers", "orders", "charges", "refunds",
              "password_resets", "human_cases", "tool_audit_log",
              "tickets", "ticket_messages"]
    with connect(path) as conn:
        for t in tables:
            rows = conn.execute(f"SELECT * FROM {t}").fetchall()
            print(f"\n=== {t} ({len(rows)} rows) ===")
            if rows:
                cols = rows[0].keys()
                print(" | ".join(cols))
                for r in rows:
                    print(" | ".join("" if r[c] is None else str(r[c]) for c in cols))


if __name__ == "__main__":
    init_db(reset="--reset" in sys.argv)
    print(f"Database ready at {os.path.abspath(DB_PATH)}")
    if "--show" in sys.argv:
        show_tables()

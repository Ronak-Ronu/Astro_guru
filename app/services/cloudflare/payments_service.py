# app/services/payments/payments_service.py
import logging, json
from typing import Optional
from app.services.cloudflare.d1_client import execute_d1_query

logger = logging.getLogger(__name__)

def ensure_payments_table():
    execute_d1_query("""
    CREATE TABLE IF NOT EXISTS wa_payments (
        reference_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        amount_paise INTEGER NOT NULL,
        currency TEXT NOT NULL,
        status TEXT NOT NULL, -- created | pending | paid | failed | refunded
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        raw_event TEXT
    );
    """)
    execute_d1_query("CREATE INDEX IF NOT EXISTS idx_wa_payments_created_at ON wa_payments(created_at)")

def upsert_payment(reference_id: str, user_id: str, amount_paise: int, currency: str, status: str, raw_event: str | None):
    execute_d1_query("""
    INSERT INTO wa_payments(reference_id, user_id, amount_paise, currency, status, created_at, updated_at, raw_event)
    VALUES(?, ?, ?, ?, ?, datetime('now'), datetime('now'), ?)
    ON CONFLICT(reference_id) DO UPDATE SET
        status=excluded.status,
        updated_at=datetime('now'),
        raw_event=excluded.raw_event
    """, [reference_id, user_id, amount_paise, currency, status, raw_event or ""])

def update_payment_status(reference_id: str, status: str, raw_event: dict | None = None):
    execute_d1_query("""
    UPDATE wa_payments
    SET status=?, updated_at=datetime('now'), raw_event=?
    WHERE reference_id=?
    """, [status, json.dumps(raw_event or {})[:2000], reference_id])

def get_payment(reference_id: str) -> Optional[dict]:
    rows = execute_d1_query("SELECT * FROM wa_payments WHERE reference_id=?", [reference_id])
    return rows if rows else None

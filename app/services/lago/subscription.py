from datetime import datetime, timedelta
import logging
import logging
import time
from typing import Tuple
import uuid
from fastapi import HTTPException
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
import requests

from app.config.constants import PAYMENT_PLANS, PLAN_QUOTAS
from app.config.settings import settings
from app.services.cloudflare.d1_client import execute_d1_query
from app.services.cloudflare.payments_service import update_payment_status
from app.services.cloudflare.users_service import reset_user_message_count
from app.services.whatsapp.send_messageAndEvents import send_whatsapp, send_whatsapp_interactive


logger = logging.getLogger(__name__)

def lago_headers():
    if not settings.LAGO_API_KEY:
        raise RuntimeError("Missing LAGO_API_KEY in environment")
    return {
        "Authorization": f"Bearer {settings.LAGO_API_KEY}",
        "Content-Type": "application/json",
    }

if not settings.LAGO_API_KEY:
    raise RuntimeError("Missing LAGO_API_KEY in environment")


def create_billing_tables():
    execute_d1_query("""
    CREATE TABLE IF NOT EXISTS wa_subscriptions (
      user_id TEXT PRIMARY KEY,
      plan_code TEXT NOT NULL,
      sub_external_id TEXT NOT NULL,
      period_start TEXT NOT NULL,
      period_end TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    """)
    execute_d1_query("""
    CREATE TABLE IF NOT EXISTS wa_usage_periods (
      user_id TEXT NOT NULL,
      period_start TEXT NOT NULL,
      period_end TEXT NOT NULL,
      used INTEGER NOT NULL DEFAULT 0,
      plan_code TEXT NOT NULL,
      PRIMARY KEY(user_id, period_start, period_end)
    );
    """)

def ensure_lago_plans():
    for plan_id, plan in PAYMENT_PLANS.items():
        plan_code = plan["plan_code"]
        interval = plan.get("interval", "monthly")
        url = f"{settings.LAGO_API_URL}/api/v1/plans/{plan_code}"
        r = requests.get(url, headers=lago_headers(), timeout=15)
        
        if r.status_code == 404:
            payload = {
                "plan": {
                    "name": f"Astro Plan {plan_id}",
                    "code": plan_code,
                    "interval": interval,
                    "amount_cents": plan["amount"],
                    "amount_currency": "INR",
                    "pay_in_advance": True               
                }
            }
            r = requests.post(f"{settings.LAGO_API_URL}/api/v1/plans",
                              headers=lago_headers(),
                              json=payload,
                              timeout=20)
            if r.status_code not in (200, 201):
                logger.error(f"Failed to auto-create Lago plan {plan_code}: {r.status_code} {r.text}")
            else:
                logger.info(f"Auto-created Lago plan: {plan_code}")
        else:
            logger.info(f"Lago plan {plan_code} already exists.")

def lago_upsert_customer(phone_e164: str, email: str | None = None, currency="INR", timezone="Asia/Kolkata") -> dict:
    """Idempotent upsert: create or fetch Lago customer by external_id."""
    logger.info(f"Attempting to upsert Lago customer {phone_e164}")
    logger.info(f"LAGO_API_URL: {settings.LAGO_API_URL}")
    
    # Try GET first
    try:
        url = f"{settings.LAGO_API_URL}/api/v1/customers/{phone_e164}"
        logger.info(f"Making GET request to: {url}")
        r = requests.get(url, headers=lago_headers(), timeout=15)
        logger.info(f"GET response: {r.status_code} {r.text}")
        
        if r.status_code == 200:
            return r.json().get("customer", {})
    except Exception as e:
        logger.error(f"Lago GET customer error: {e}")
        raise HTTPException(502, "Billing service unavailable (customer)")

    # Create
    payload = {
        "customer": {
            "external_id": phone_e164,
            "currency": currency,
            "email": email,
            "timezone": timezone,
            "name": phone_e164
        }
    }
    
    try:
        url = f"{settings.LAGO_API_URL}/api/v1/customers"
        logger.info(f"Making POST request to: {url} with payload: {payload}")
        r = requests.post(url, headers=lago_headers(), json=payload, timeout=20)
        logger.info(f"POST response: {r.status_code} {r.text}")
        
        if r.status_code not in (200, 201):
            logger.error(f"Lago create customer failed: {r.status_code} {r.text}")
            raise HTTPException(502, "Billing service unavailable (customer)")
        return r.json().get("customer", {})
    except Exception as e:
        logger.error(f"Lago create customer error: {e}")
        raise HTTPException(502, "Billing service unavailable (customer)")



def lago_get_active_subscription(phone_e164: str) -> dict | None:
    r = requests.get(
        f"{settings.LAGO_API_URL}/customers/{phone_e164}/subscriptions",
        headers=lago_headers(),
        timeout=15,
        params={"status": "active"}
    )
    if r.status_code != 200:
        logger.error(f"Lago subscriptions fetch failed: {r.status_code} {r.text}")
        return None
    subs = r.json().get("subscriptions", [])
    if not subs:
        return None
    # Pick the most recent active sub
    subs.sort(key=lambda s: s.get("subscription_at") or s.get("created_at") or "", reverse=True)
    return subs[0]

def lago_create_subscription(phone_e164: str, plan_code: str, start_at_utc: datetime | None = None, external_sub_id: str | None = None) -> dict:
    """
    Assign plan to a customer creating a subscription in Lago.
    """
    if start_at_utc is None:
        start_at_utc = datetime.utcnow()
    sub_payload = {
        "subscription": {
            "external_customer_id": phone_e164,
            "plan_code": plan_code,
            "external_id": external_sub_id or f"sub_{phone_e164}_{int(time.time())}",
            "subscription_at": start_at_utc.replace(microsecond=0).isoformat() + "Z",
            "billing_time": "anniversary"
        }
    }
    r = requests.post(f"{settings.LAGO_API_URL}/api/v1/subscriptions", headers=lago_headers(), json=sub_payload, timeout=20)
    if r.status_code not in (200, 201):
        logger.error(f"Lago create subscription failed: {r.status_code} {r.text}")
        raise HTTPException(502, "Billing service unavailable (subscription)")
    return r.json().get("subscription", {})


def get_current_subscription_row(phone_e164: str) -> dict:
    rows = execute_d1_query(
        "SELECT * FROM wa_subscriptions WHERE user_id = ? ORDER BY period_end DESC LIMIT 1",
        [phone_e164]
    )
    return rows[0] if rows else None

def upsert_active_subscription(phone_e164: str, plan_code: str, period_start: datetime, period_end: datetime, sub_external_id: str):
    """Create or update subscription in D1"""
    now = datetime.utcnow().isoformat()
    period_start_iso = period_start.isoformat()
    period_end_iso = period_end.isoformat()
    
    # Check if subscription exists
    existing = get_current_subscription_row(phone_e164)
    
    if existing:
        execute_d1_query(
            """
            UPDATE wa_subscriptions 
            SET plan_code=?, sub_external_id=?, period_start=?, period_end=?, updated_at=?
            WHERE user_id=?
            """,
            [plan_code, sub_external_id, period_start_iso, period_end_iso, now, phone_e164]
        )
    else:
        execute_d1_query(
            """
            INSERT INTO wa_subscriptions 
            (user_id, plan_code, sub_external_id, period_start, period_end, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            [phone_e164, plan_code, sub_external_id, period_start_iso, period_end_iso, now, now]
        )
    
    # Ensure usage period exists
    execute_d1_query(
        """
        INSERT OR IGNORE INTO wa_usage_periods 
        (user_id, period_start, period_end, used, plan_code)
        VALUES (?, ?, ?, 0, ?)
        """,
        [phone_e164, period_start_iso, period_end_iso, plan_code]
    )

def lago_get_active_subscription(phone_e164: str) -> dict | None:
    r = requests.get(
        f"{settings.LAGO_API_URL}/api/v1/customers/{phone_e164}/subscriptions",
        headers=lago_headers(),
        timeout=15,
        params={"status": "active"}
    )
    if r.status_code != 200:
        logger.error(f"Lago subscriptions fetch failed: {r.status_code} {r.text}")
        return None
    subs = r.json().get("subscriptions", [])
    if not subs:
        return None
    # Pick the most recent active sub
    subs.sort(key=lambda s: s.get("subscription_at") or s.get("created_at") or "", reverse=True)
    return subs[0]

def log_payment_activity(user_id: str, action: str, details: str = ""):
    logger.info(f"[PAYMENT] {action} for user {user_id}: {details}")
    
    # Also store in database for analytics
    try:
        execute_d1_query(
            """
            INSERT INTO payment_activity_log 
            (log_id, user_id, action, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [str(uuid.uuid4()), user_id, action, details, datetime.utcnow().isoformat()]
        )
    except Exception as e:
        logger.error(f"Failed to log payment activity: {e}")



def terminate_subscription(phone_e164: str, reason: str = "limit_reached"):
    sub = get_current_subscription_row(phone_e164)
    if not sub:
        logger.info(f"No active subscription to terminate for {phone_e164}")
        return

    # Terminate in Lago
    try:
        payload = {
            "subscription": {
                "external_id": sub["sub_external_id"]
            }
        }
        r = requests.delete(f"{settings.LAGO_API_URL}/api/v1/subscriptions/{sub['sub_external_id']}", 
                            headers=lago_headers(), json=payload, timeout=20)
        if r.status_code in (200, 204):
            logger.info(f"Lago subscription terminated: {sub['sub_external_id']}")
        else:
            logger.error(f"Lago termination failed: {r.status_code} {r.text}")
    except Exception as e:
        logger.error(f"Failed to terminate Lago sub: {e}")

    # Delete from D1
    execute_d1_query("DELETE FROM wa_subscriptions WHERE user_id = ?", [phone_e164])
    execute_d1_query("DELETE FROM wa_usage_periods WHERE user_id = ?", [phone_e164])
    reset_user_message_count(phone_e164)  # Reset free tier counter
    log_payment_activity(phone_e164, "subscription_terminated", f"reason: {reason}")
    logger.info(f"Terminated subscription for {phone_e164}: {reason}")


def compute_period_window(start_at: datetime, days: int) -> Tuple[datetime, datetime]:
    ps = start_at.replace(microsecond=0, second=0, minute=0, hour=0)  # Start of day
    pe = ps + timedelta(days=days)
    return ps, pe

def activate_subscription(phone_e164: str, plan_id: str, external_sub_id: str = None) -> dict:
    """Activate subscription with proper cleanup and validation"""
    if plan_id not in PAYMENT_PLANS:
        raise ValueError(f"Invalid plan ID: {plan_id}")

    # Clean up any existing subscriptions first
    terminate_subscription(phone_e164, "new_activation")
    
    plan_code = PAYMENT_PLANS[plan_id]["plan_code"]
    
    try:
        # Create Lago customer and subscription
        lago_upsert_customer(phone_e164)
        sub = lago_create_subscription(
            phone_e164,
            plan_code,
            start_at_utc=datetime.utcnow(),
            external_sub_id=external_sub_id
        )
        
        # Compute period window
        meta = PLAN_QUOTAS.get(plan_code, {})
        days = meta.get("days", 1)
        ps, pe = compute_period_window(datetime.utcnow(), days)
        
        # Store in D1
        upsert_active_subscription(
            phone_e164,
            plan_code,
            ps,
            pe,
            sub.get("external_id", external_sub_id or "")
        )
        
        # Reset any free tier counters
        execute_d1_query(
            "UPDATE user_message_counters SET count = 0 WHERE user_id = ?",
            [phone_e164]
        )
        
        log_payment_activity(phone_e164, "subscription_activated", 
                           f"plan: {plan_id}, quota: {meta.get('questions', 0)}")
        
        logger.info(f"Subscription activated successfully for {phone_e164}: {plan_id}")
        return sub
        
    except Exception as e:
        logger.error(f"Subscription activation failed for {phone_e164}: {e}")
        raise


def get_usage_state(phone_e164: str) -> tuple[dict | None, dict | None]:
    """Get current subscription and usage state"""
    try:
        # Get active subscription
        sub = get_current_subscription_row(phone_e164)
        if not sub:
            return None, None
        
        # Get usage for current period
        rows = execute_d1_query("""
            SELECT * FROM wa_usage_periods 
            WHERE user_id = ? AND period_start = ? AND period_end = ?
        """, [phone_e164, sub["period_start"], sub["period_end"]])
        
        usage = rows[0] if rows else None
        return sub, usage
        
    except Exception as e:
        logger.error(f"Error getting usage state for {phone_e164}: {e}")
        return None, None
def ensure_period_rollover_if_needed(phone_e164: str):
    sub = get_current_subscription_row(phone_e164)
    if not sub:
        return
    
    now = datetime.utcnow()
    ps = datetime.fromisoformat(sub["period_start"])
    pe = datetime.fromisoformat(sub["period_end"])
    
    if now >= pe:
        # Create next window
        days = PLAN_QUOTAS.get(sub["plan_code"], {}).get("days", 1)
        nps, npe = compute_period_window(pe, days)
        upsert_active_subscription(phone_e164, sub["plan_code"], nps, npe, sub["sub_external_id"])
        
        execute_d1_query(
            "UPDATE user_message_counters SET count = 0 WHERE user_id = ?",
            [phone_e164]
        )
def get_remaining(phone_e164: str) -> tuple[int, int]:
    sub, usage = get_usage_state(phone_e164)
    if not sub:
        return (0, 0)
    ensure_period_rollover_if_needed(phone_e164)
    sub, usage = get_usage_state(phone_e164)
    used = int(usage["used"]) if usage else 0
    quota = PLAN_QUOTAS.get(sub["plan_code"], {}).get("questions", 0)
    return (max(quota - used, 0), quota)

async def handle_paid_confirmation(from_number: str, text: str):
    """Handle manual payment confirmation"""
    parts = text.split()
    ref_provided = parts[1] if len(parts) > 1 else None
    
    if not ref_provided:
        send_whatsapp(from_number, "Please send: paid <your reference id>")
        return {"status": "awaiting_ref"}

    # Check if payment exists
    from app.services.cloudflare.payments_service import get_payment
    p = get_payment(ref_provided)
    
    if not p or p["user_id"] != from_number:
        send_whatsapp(from_number, "Reference not found for this number. Please verify the ID.")
        return {"status": "invalid_reference"}

    # Try activating subscription
    try:
        # Determine plan based on amount
        amt = int(p["amount_paise"])
        if amt == PAYMENT_PLANS["9"]["amount"]:
            plan_id = "9"
        elif amt == PAYMENT_PLANS["49"]["amount"]:
            plan_id = "49"
        else:
            send_whatsapp(from_number, "Unsupported amount on the reference. Contact support.")
            update_payment_status(ref_provided, "failed", {"reason": "unsupported_amount_fallback"})
            return {"status": "error"}

        # Activate subscription
        sub = activate_subscription(from_number, plan_id, f"ext_{ref_provided}")
        update_payment_status(ref_provided, "paid", {"reason": "user_confirmed"})
        
        # Send success message
        send_whatsapp(
            from_number,
            f"✅ *Payment Confirmed!* ✅\n\n"
            f"Your {PAYMENT_PLANS[plan_id]['description']} is now active!\n\n"
            f"💫 Ask away - the cosmos awaits your questions! ✨\n\n"
            f"You now have {PLAN_QUOTAS[PAYMENT_PLANS[plan_id]['plan_code']]['questions']} questions available."
        )
        
        return {"status": "subscription_activated", "subscription_id": sub.get("external_id")}
        
    except Exception as e:
        logger.error(f"Activation via user confirmation failed: {e}")
        send_whatsapp(from_number, "Payment received but activation failed. Support will assist.")
        return {"status": "error", "reason": "activation_failed"}


def send_payment_prompt(to: str, user_id: str):
    """Send payment options to user - simplified to avoid 400 errors"""
    if user_id is None:
        user_id = to

    sub, usage = get_usage_state(user_id)
    
    if not sub:
        used, quota = 3, 3  # Free tier
        tier_msg = "You've reached your 3 free questions!"
    else:
        used, quota = get_remaining(user_id)
        tier_msg = f"You've used {used}/{quota} questions in your current period!"

    # Use simple text message instead of interactive to avoid 400 errors
    body = (
        f"🔒 *{tier_msg}*\n\n"
        "🔓 *Unlock More Cosmic Wisdom!*\n\n"
        "Choose a plan to continue:\n\n"
        f"1. Reply '9' for {PAYMENT_PLANS['9']['display_price']} → {PAYMENT_PLANS['9']['description']}\n"
        f"2. Reply '49' for {PAYMENT_PLANS['49']['display_price']} → {PAYMENT_PLANS['49']['description']}\n\n"
        "Reply with the number of the plan you want to choose! 💫"
    )
    
    log_payment_activity(user_id, "payment_prompt_sent", f"used: {used}, quota: {quota}")
    send_whatsapp(to, body)


def within_period(now_iso: str, ps_iso: str, pe_iso: str) -> bool:
    now = datetime.fromisoformat(now_iso.replace("Z",""))
    ps = datetime.fromisoformat(ps_iso)
    pe = datetime.fromisoformat(pe_iso)
    return ps <= now < pe

def check_and_prompt(phone_e164: str) -> bool:
    try:
        sub, usage = get_usage_state(phone_e164)
        if not sub:
            # Free tier
            rows = execute_d1_query("SELECT count FROM user_message_counters WHERE user_id = ?", [phone_e164])
            count = rows[0]["count"] if rows else 0
            if count >= 3:
                send_payment_prompt(to=phone_e164, user_id=phone_e164)
                return False
            return True
        else:
            # Paid user
            ensure_period_rollover_if_needed(phone_e164)
            sub, usage = get_usage_state(phone_e164)
            
            used = int(usage["used"]) if usage else 0
            quota = PLAN_QUOTAS.get(sub["plan_code"], {}).get("questions", 0)
            
            if used >= quota:
                send_payment_prompt(to=phone_e164, user_id=phone_e164)
                return False
            return True
    except Exception as e:
        logger.error(f"Error in check_and_prompt for {phone_e164}: {e}")
        return True  # Allow on error

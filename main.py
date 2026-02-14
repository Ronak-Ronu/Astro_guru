import os
import json
import threading
import time
import logging
import random
from typing import Any, Counter, Dict, List, Tuple
import uuid
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
import pytz
import requests
import warnings
from datetime import date, datetime, timedelta
from datetime import datetime

from typing import Optional
import swisseph as swe

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from kerykeion import AstrologicalSubject
from sentence_transformers import SentenceTransformer
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
import chromadb

from app.config.settings import settings
from app.helpers import coerce_time_to_hm, get_city_info, parse_date_flexible, parse_date_flexible_safe, parse_time_flexible, parse_time_flexible_safe
from app.schemas import ChatRequest, ChatResponse, CompatibilityRequest, CompatibilityResponse, HoroscopeRequest, HoroscopeResponse, PaymentWebhookRequest, Profile, ProfileListRequest, ProfileListResponse, SimulatePaymentRequest, StartCheckoutRequest, StartCheckoutResponse
from app.chatcontextmanager import ChatContextManager

from app.config.constants import HEAVY_TASKS, LANGUAGES, PAYMENT_PLANS, PLAN_QUOTAS, PROMPTS, SIGN_ABBREV_TO_FULL, SIGNS, SKIP_COMMANDS, detect_special_intent
from app.services.astrology.chart_calculations import calculate_natal_chart_multi_method, get_transits_swisseph
from app.services.astrology.synastry_flow import handle_compatibility_flow, split_message
from app.services.chroma_cloud.chromadbClient import create_chroma_client, get_relevant_passages, safe_get_relevant_passages
from app.services.cloudflare.d1_client import execute_d1_query
from app.services.cloudflare.feedback_service import create_feedback_tables,handle_feedback_flow_webhook, normalize_emoji, process_text_feedback_step, send_feedback_rating_prompt, start_feedback_flow, start_text_feedback, feedback_sessions
from app.services.cloudflare.payments_service import ensure_payments_table, update_payment_status, upsert_payment
from app.services.cloudflare.synastry_service import calculate_synastry_aspects, create_compatibility_tables, delete_compatibility_session, save_compatibility_result, save_compatibility_session
from app.services.cloudflare.users_service import create_message_counter_table, create_profile, create_profiles_table, deactivate_all_profiles, delete_user, get_user, get_user_language, insert_user, list_profiles, reset_user_message_count, switch_active_profile, update_user_dob, update_user_language
from app.services.lago.subscription import activate_subscription, check_and_prompt, compute_period_window, create_billing_tables, ensure_lago_plans, ensure_period_rollover_if_needed, get_current_subscription_row, get_usage_state, lago_upsert_customer, log_payment_activity, send_payment_prompt, terminate_subscription, upsert_active_subscription
from app.services.whatsapp.payments import send_upi_intent_payment_message, verify_meta_signature
from app.services.whatsapp.send_messageAndEvents import send_feedback_request_prompt, send_language_selector, send_payment_invoice, send_profile_list_whatsapp, send_typing_indicator, send_whatsapp, send_whatsapp_interactive, send_whatsapp_location_request, send_whatsapp_reaction
from app.util.natal_chart.send_chart import send_user_chart_pdf
from app.util.CTA_buttons_NLP.buttons_nlp import determine_context_buttons

import re
import os

# --- Initialization ---
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()
SWEPH_EPHE_PATH = os.getenv("SWEPH_EPHE_PATH", "./ephe") 
swe.set_ephe_path(SWEPH_EPHE_PATH)

# Embedding models
# embed_model = SentenceTransformer("all-MiniLM-L6-v2")
# embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

# Vector store (DEV)
# chroma_client = chromadb.PersistentClient(path="./chromadb_data")
# vector_store = Chroma(client=chroma_client, collection_name="astro_passages", embedding_function=embeddings)

# ChromaDB client setup (CLOUD)
chroma_client, vector_store = create_chroma_client()

# Whatsapp Business API config
WA_ACCESS_TOKEN = settings.WA_ACCESS_TOKEN
WA_PHONE_NUMBER_ID = settings.WA_PHONE_NUMBER_ID
VERIFY_TOKEN = settings.VERIFY_TOKEN

# Cloudfalre config
WORKER = settings.WORKER_URL
TOKEN = settings.CF_TOKEN
CF_ACCOUNT_ID = settings.CF_ACCOUNT_ID
CF_D1_DATABASE_ID = settings.CF_D1_DATABASE_ID
CF_API_TOKEN = settings.CF_API_TOKEN
if not WORKER or not TOKEN:
    raise RuntimeError("Missing WORKER_URL or CF_TOKEN in .env")

processed_messages = set()
MESSAGE_TTL = 300  # 5 minutes

def is_duplicate_message(message_id: str) -> bool:
    """Check if message has been processed recently"""
    global processed_messages
    if message_id in processed_messages:
        return True
    processed_messages.add(message_id)
    # Clean up old messages
    if len(processed_messages) > 1000:
        # Keep only recent 1000 messages
        processed_messages = set(list(processed_messages)[-1000:])
    return False


# --- FastAPI app ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])



from timezonefinder import TimezoneFinder
tf = TimezoneFinder()


# Add this new endpoint after your existing endpoints
@app.post("/compatibility", response_model=CompatibilityResponse)
async def compatibility_analysis(req: CompatibilityRequest):
    """Generate compatibility analysis between two people"""
    try:
        # Calculate synastry aspects
        aspects = calculate_synastry_aspects(req.user_natal_chart, req.partner_natal_chart)
        
        # Get relevant astrological passages for compatibility
        user_sun = req.user_natal_chart.get('Sun', {}).get('sign', 'Unknown')
        user_moon = req.user_natal_chart.get('Moon', {}).get('sign', 'Unknown')
        partner_sun = req.partner_natal_chart.get('Sun', {}).get('sign', 'Unknown')
        partner_moon = req.partner_natal_chart.get('Moon', {}).get('sign', 'Unknown')
        
        compatibility_query = f"compatibility {user_sun} {user_moon} {partner_sun} {partner_moon} synastry relationship"
        passages = safe_get_relevant_passages(compatibility_query, k=5)
        
        # Prepare payload for Cloudflare Worker
        payload = {
            "user_natal_chart": req.user_natal_chart,
            "partner_natal_chart": req.partner_natal_chart,
            "synastry_aspects": aspects,
            "passages": passages,
            "names": req.names,


        }
        
        headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
        
        try:
            logger.info(f"Sending compatibility request to Worker: {WORKER}/compatibility")
            res = requests.post(f"{WORKER}/compatibility", json=payload, headers=headers, timeout=60)
            logger.info(f"Worker compatibility response: {res.text}")
            res.raise_for_status()
            content = res.json()
            
            return CompatibilityResponse(**content)
            
        except requests.RequestException as e:
            logger.error(f"Worker error in compatibility: {e}")
            raise HTTPException(502, "AI service unavailable for compatibility analysis")
            
    except Exception as e:
        logger.error(f"Compatibility analysis error: {e}")
        raise HTTPException(500, "Compatibility analysis failed")


context_manager =None



@app.on_event("startup")
def startup():
    global context_manager
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        name TEXT,
        dob TEXT,
        birth_time TEXT,
        birth_city TEXT,
        lat REAL,
        lng REAL,
        timezone TEXT,
        natal_chart TEXT,
        language TEXT DEFAULT 'en'
    );
    """

    try:
        create_compatibility_tables();
        execute_d1_query(create_table_sql)

        logger.info("Users table created or already exists in Cloudflare D1.")
        context_manager = ChatContextManager(
            cf_account_id=CF_ACCOUNT_ID,
            cf_d1_database_id=CF_D1_DATABASE_ID,
            cf_api_token=CF_API_TOKEN
        )
        context_manager.create_chat_context_table()
        create_feedback_tables()
        create_message_counter_table()
        create_profiles_table()
        logger.info("Chat context system initialized")
        create_billing_tables()
        ensure_payments_table()
        ensure_lago_plans()


        
        create_payment_log_table = """
        CREATE TABLE IF NOT EXISTS payment_activity_log (
            log_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL
        );
        """
        execute_d1_query(create_payment_log_table)
        logger.info("Payment activity log table created or already exists")
    except Exception as e:
        logger.error(f"Failed to create users table: {e}")

def is_heavy_task(intent: str, text: str) -> bool:
    if intent in HEAVY_TASKS:
        return True
    if not intent and text and len(text.strip()) > 3:
        return True
    return False


active_payment_flows = {}

def _clean_e164(e164: str) -> str:
    return e164.replace("whatsapp:", "").strip()

def _get_active_payment(phone_e164: str) -> dict | None:
    return active_payment_flows.get(_clean_e164(phone_e164))

def _clear_active_payment(phone_e164: str):
    active_payment_flows.pop(_clean_e164(phone_e164), None)


@app.post("/webhook/payment")
async def payment_webhook(
    request: Request,
    x_hub_signature_256: str = Header(None)
):
    raw_body = await request.body()

    # Verify Meta signature
    if not verify_meta_signature(raw_body, x_hub_signature_256):
        logger.warning("Invalid Meta signature")
        return {"status": "error", "reason": "invalid_signature"}

    data = await request.json()
    logger.info(f"Received payment webhook: {json.dumps(data)}")

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                statuses = change.get("value", {}).get("statuses", [])
                for st in statuses:
                    if st.get("status") != "payment":
                        continue

                    payment = st.get("payment", {})
                    reference_id = payment.get("reference_id")
                    status = payment.get("status", "").lower()
                    amount = int(payment.get("amount", {}).get("value", 0))
                    payer_id = payment.get("payer", {}).get("wa_id")  # ✅ correct user
                    if not reference_id:
                        continue

                    if status in ("completed", "success", "paid", "captured"):
                        update_payment_status(reference_id, "paid", {"payload": payment})

                        # Resolve plan from amount dynamically
                        plan_id = None
                        for k, v in PAYMENT_PLANS.items():
                            if v["amount"] == amount:
                                plan_id = k
                                break
                        if not plan_id:
                            plan_id = "custom"

                        activate_subscription(f"whatsapp:{payer_id}", plan_id, f"ext_{reference_id}")
                        send_whatsapp(f"whatsapp:{payer_id}", f"✅ Payment successful! {plan_id} activated 🎉")

                    else:
                        update_payment_status(reference_id, "failed", {"payload": payment})
                        send_whatsapp(f"whatsapp:{payer_id}", f"❌ Payment failed for {reference_id}. Try again.")

        return {"status": "ok"}
    except Exception as e:
        logger.exception("Error handling payment webhook")
        return {"status": "error", "reason": str(e)}

    
@app.post("/checkout/start-upi")
def start_checkout_upi(req: StartCheckoutRequest):
    if req.plan not in PAYMENT_PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan")
    plan = PAYMENT_PLANS[req.plan]
    amount_paise = plan["amount"]            # already in paise (900, 4900, etc.)
    reference_id = f"ORDER-{req.phone}-{int(time.time())}"

    # Record order
    upsert_payment(reference_id, req.phone, amount_paise, "INR", "created", raw_event=None)

    # ==== TEST MODE SHORT-CIRCUIT ====
    if settings.TEST_MODE:
        # Mark as pending -> paid
        update_payment_status(reference_id, "pending", {"reason": "test_mode_started"})
        update_payment_status(reference_id, "paid", {"reason": "test_mode_paid"})

        # Activate subscription (mimics webhook doing this)
        sub = activate_subscription(
            phone_e164=req.phone if req.phone.startswith("whatsapp:") else f"whatsapp:{req.phone}",
            plan_id=req.plan,
            external_sub_id=f"test_{reference_id}"
        )


        # Tell the user (simple text)
        send_whatsapp(
            req.phone if req.phone.startswith("whatsapp:") else f"whatsapp:{req.phone}",
            f"✅ [TEST MODE] Payment simulated for {PAYMENT_PLANS[req.plan]['description']}. Subscription activated 🎉"
        )

        return {
            "status": "simulated_payment_success",
            "reference_id": reference_id,
            "subscription_id": sub.get("external_id")
        }
    # ==== /TEST MODE ====

    # REAL flow (unchanged): send UPI interactive message
    conf = settings.WA_PAYMENT_CONFIGURATION
    send_upi_intent_payment_message(
        to_e164=req.phone if req.phone.startswith("whatsapp:") else f"whatsapp:{req.phone}",
        reference_id=reference_id,
        amount_in_paise=amount_paise,
        description=plan["description"],
        configuration_name_or_id=conf,
        items=[{"retailer_id": req.plan, "name": plan["description"], "amount": {"value": amount_paise, "offset": 100}, "quantity": 1}],
    )
    update_payment_status(reference_id, "pending", {"reason": "upi_intent_sent"})
    return {"status": "upi_intent_sent", "reference_id": reference_id}


FREE_PLAN_KEY = "free_tier"


def ensure_free_subscription(phone_e164: str) -> bool:
    """
    Ensure a free-tier subscription row exists for this user.
    Uses upsert_active_subscription(...) so we keep the schema consistent.
    Returns True on success, False on error.
    """
    try:
        uid = normalize_user_id(phone_e164)

        # If user already has a current subscription, do nothing
        existing = get_current_subscription_row(uid)
        if existing:
            return True

        # fallback quotas/days if free_tier not present
        free_meta = PLAN_QUOTAS.get(FREE_PLAN_KEY, {})
        days = int(free_meta.get("days", 1))

        now = datetime.utcnow()
        ps, pe = compute_period_window(now, days)

        sub_external_id = f"sub_free_{uid}_{int(time.time())}"

        # Use upsert_active_subscription (expects datetime objects for ps, pe)
        upsert_active_subscription(uid, FREE_PLAN_KEY, ps, pe, sub_external_id)

        # Ensure user_message_counters exists
        execute_d1_query(
            """
            INSERT OR IGNORE INTO user_message_counters (user_id, count, last_reset)
            VALUES (?, 0, ?)
            """,
            [uid, datetime.utcnow().isoformat()]
        )

        logger.info(f"[SUB] Free-tier subscription created for {uid}")
        return True

    except Exception as e:
        logger.error(f"[SUB ERROR] Failed to create free-tier subscription for {phone_e164}: {e}")
        return False

# --- Endpoint ---
@app.post("/generate", response_model=HoroscopeResponse)
async def generate(req: HoroscopeRequest):
    t0 = time.perf_counter()
    # Natal chart (unchanged)
    subj = AstrologicalSubject(
        name=req.name, year=req.birth_year, month=req.birth_month, day=req.birth_day,
        hour=req.birth_hour, minute=req.birth_minute, lat=req.lat, lng=req.lng, tz_str=req.timezone, online=False
    )
    print(subj.mars)
    print(subj.sun)
    logger.info("Calculating natal chart...")

    natal, retro = {}, []
    for p in ["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune", "pluto"]:
        d = getattr(subj, p)
        full_sign = SIGN_ABBREV_TO_FULL.get(d.get("sign"), "Unknown")
        natal[p.capitalize()] = {"sign": full_sign, "degree": round(d["position"], 1), "house": d["house"]}
        logger.info(f"Natal {p.capitalize()}: {full_sign} {natal[p.capitalize()]['degree']}°, House {d['house']}")
        if d.get("retrograde"):
            retro.append(p.capitalize())
            logger.info(f"{p.capitalize()} is retrograde")
    logger.info(f"Retrogrades: {retro if retro else 'None'}")
    
    # Transits (Swiss Ephemeris, not async)
    dt = req.date or date.today().isoformat()
    trans = get_transits_swisseph(req.lat, req.lng, dt)
    logger.info("Calculating aspects...")
    zodiac = SIGNS
    aspects = []
    aspect_types = {0: "conjunction", 60: "sextile", 90: "square", 120: "trine", 180: "opposition"}
    for nat_p, nd in natal.items():
        if nd["sign"] == "Unknown":
            logger.warning(f"Skipping aspects for {nat_p} due to Unknown sign")
            continue
        for tr_p, td in trans.items():
            if td["sign"] == "Unknown":
                logger.warning(f"Skipping aspects for transit {tr_p} due to Unknown sign")
                continue
            nat_deg = zodiac.index(nd["sign"]) * 30 + nd["degree"]
            tr_deg = zodiac.index(td["sign"]) * 30 + td["degree"]
            diff = abs(nat_deg - tr_deg) % 360
            diff = diff if diff <= 180 else 360 - diff
            for ang, name in aspect_types.items():
                if abs(diff - ang) <= 8:
                    aspects.append(f"{tr_p} {name} natal {nat_p}")
                    logger.info(f"Aspect detected: {tr_p} {name} natal {nat_p} (angle: {diff:.1f}°)")
                    break

    logger.info("Calculating natal-natal aspects...")
    natal_aspects = []
    planet_pairs = [
        (p1, p2) for i, p1 in enumerate(natal.keys()) for p2 in list(natal.keys())[i+1:]
    ]
    for p1, p2 in planet_pairs:
        if natal[p1]["sign"] == "Unknown" or natal[p2]["sign"] == "Unknown":
            logger.warning(f"Skipping natal aspect between {p1} and {p2} due to Unknown sign")
            continue
        try:
            deg1 = zodiac.index(natal[p1]["sign"]) * 30 + natal[p1]["degree"]
            deg2 = zodiac.index(natal[p2]["sign"]) * 30 + natal[p2]["degree"]
            diff = abs(deg1 - deg2) % 360
            diff = diff if diff <= 180 else 360 - diff
            for ang, name in aspect_types.items():
                if abs(diff - ang) <= 8:
                    natal_aspects.append(f"{p1} {name} {p2}")
                    logger.info(f"Natal aspect detected: {p1} {name} {p2} (angle: {diff:.1f}°)")
                    break
        except Exception as e:
            logger.error(f"Error calculating natal aspect between {p1} and {p2}: {e}")


    # RAG query with transit availability check
    unknown_count = sum(1 for p in trans.values() if p["sign"] == "Unknown")
    trans_str = "Transit data unavailable" if unknown_count > 3 else json.dumps(trans)
    qc = (f"Vedic horoscope for {req.name}: Natal Sun {natal['Sun']['sign']} {natal['Sun']['degree']}°, "
          f"Moon {natal['Moon']['sign']} {natal['Moon']['degree']}°, Date {dt}, "
          f"Transits {trans_str}, Aspects {aspects}, Retrogrades {retro}")
    passages = safe_get_relevant_passages(qc)

    # Prepare worker payload (unchanged)
    payload = {
        "name": req.name,
        "natal_chart": natal,
        "current_transits": trans,
        "aspects": aspects,
        "retrogrades": retro,
        "passages": passages,
        "date": dt,
        "language": getattr(req, "language", "en")

    }
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    logger.info(f"Worker payload: {json.dumps(payload, indent=2)}")
    try:
        logger.info(f"Sending request to Worker: {WORKER}/personal")
        res = requests.post(f"{WORKER}/personal", json=payload, headers=headers, timeout=60)
        logger.info(f"Worker response: {res.text}")
        res.raise_for_status()
        content = res.json()
    except requests.RequestException as e:
        logger.error(f"Worker error: {e}")
        raise HTTPException(502, "AI service unavailable")

    if isinstance(content, dict):
        content.setdefault("practical_guidance", {})
        content["practical_guidance"]["lucky_numbers"] = random.sample(range(1, 91), 4)
        content["practical_guidance"]["lucky_colors"] = random.sample(
            ["Saffron", "Emerald", "Gold", "Silver", "Coral", "Pearl"], 2
        )

    gen_time = time.perf_counter() - t0
    logger.info(f"Response generated in {gen_time:.3f} seconds")
    return HoroscopeResponse(horoscope=content, generation_time_seconds=gen_time)




@app.post("/profiles/list", response_model=ProfileListResponse)
async def profiles_list(req: ProfileListRequest):
    rows = list_profiles(req.user_id)
    profiles = [
        Profile(
            profile_id=r["profile_id"],
            name=r["name"],
            dob=r["dob"],
            birth_time=r["birth_time"],
            birth_city=r["birth_city"]
        )
        for r in rows
    ]
    active = next((r["profile_id"] for r in rows if r["is_active"] == 1), None)
    return ProfileListResponse(profiles=profiles, active_profile_id=active)


def get_active_profile(owner_user_id: str):
    try:
        # Single-line SQL avoids leading newline issues
        sql = "SELECT * FROM user_profiles WHERE owner_user_id = ? AND is_active = 1"
        rows = execute_d1_query(sql, [owner_user_id])
        if rows:
            return rows[0]
    except Exception as e:
        logger.error(f"get_active_profile error: {e}")
    # Fallback to main user record
    return get_user(owner_user_id)



@app.post("/chat", response_model=ChatResponse)
async def astro_chat(req: ChatRequest):
    query = req.message
    passages = safe_get_relevant_passages(query, k=6)
    
    messages = [
        {
            "role": "system",
            "content": (
                "You are an ancient Vedic astrologer. "
                "Answer as an expert using classical wisdom and reference context if provided. "
                "Be insightful, positive, and practical."
            )
        },
        {
            "role": "user",
            "content": (
                f"User question: {query}\n\n"
                f"Relevant classical astrology passages (if any):\n{passages}"
            )
        }
    ]
    
    worker_url = os.getenv("WORKER_URL")
    token = os.getenv("CF_TOKEN")
    llm_payload = {
        "messages": messages,
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        res = requests.post(f"{worker_url}/chat", json=llm_payload, headers=headers, timeout=60)
        res.raise_for_status()
        result = res.json()
        answer = result.get("response", "I'm unable to answer at the moment.")
    except Exception as e:
        logger.error(f"LLM chat error: {e}")
        answer = "Sorry, there was an AI service error."

    return ChatResponse(response=answer)

def call_worker(payload: dict) -> dict:
    res = requests.post(
        f"{WORKER}/cosmic-guidance",
        json=payload,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        timeout=30
    )
    res.raise_for_status()
    return res.json()

def normalize_user_id(user_id: str) -> str:
    if not user_id.startswith("whatsapp:"):
        return f"whatsapp:{user_id}"
    return user_id
import re

def enforce_structure(reply: str, user_name: str) -> str:
    """Ensure all sections exist with proper formatting"""
    reply = reply.strip()

    # Normalize headers instead of deleting them
    replacements = {
        r"(?i)^right now.*": "Right now",
        r"(?i)^what this means.*": "What this means",
        r"(?i)^advice for you.*": "Advice for you",
        r"(?i)^summary.*": "Summary",
    }
    for pat, repl in replacements.items():
        reply = re.sub(pat, repl, reply, flags=re.M)

    # Split into sentences if missing headers entirely
    if not any(h.lower() in reply.lower() for h in ["right now", "what this means", "advice for you", "summary"]):
        sentences = re.split(r'(?<=[.!?])\s+', reply)
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) < 4:
            return f"Hello {user_name}, {reply}"
        reply = f"Right now\n{sentences[0]}\n\nWhat this means\n{sentences[1]}\n\nAdvice for you\n{sentences[2]}\n\nSummary\n{' '.join(sentences[3:])}"

    return reply


def format_for_whatsapp(reply: str) -> str:
    """Beautify horoscope response with emojis + spacing for WhatsApp"""
    sections = {
        "Right now": "✅ *Right now*",
        "What this means": "🔮 *What this means*", 
        "Advice for you": "✨ *Advice for you*",
        "Summary": "🌟 *Summary*"
    }

    cleaned = reply.strip()
    
    # Replace section headers with decorated versions
    for sec, decorated in sections.items():
        cleaned = re.sub(
            rf"^{sec}$",  # Match exactly the section header on its own line
            f"\n{decorated}",
            cleaned,
            flags=re.I | re.M
        )
    
    # Ensure proper spacing between sections
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)  # Replace multiple newlines with double
    cleaned = re.sub(r'(?<!\n)\n(?!\n)', '\n\n', cleaned)  # Ensure single newlines become double
    
    return cleaned.strip()

def format_lucky_number(reply: str, user_name: str) -> str:
    """Format lucky number response into 3 short readable parts"""
    reply = reply.strip()
    reply = re.sub(r'^[, ]+', '', reply)

    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', reply)

    if len(sentences) >= 3:
        numbers = sentences[0]
        usage   = sentences[1]
        timing  = " ".join(sentences[2:])
        return f"👋 Hello {user_name},\n\n{numbers}\n\n{usage}\n\n{timing}"
    else:
        # Fallback if response too short
        return f"👋 Hello {user_name},\n\n{reply}"
    

from datetime import datetime
FREE_PLAN_KEY = "free_tier"

def ensure_llm_quota(user_id: str, from_number: str) -> bool:
    uid = normalize_user_id(user_id)

    # Ensure subscription row exists, fallback to free
    sub = get_current_subscription_row(uid)
    if not sub:
        ensure_free_subscription(uid)
        sub = get_current_subscription_row(uid)

    plan_code = sub.get("plan_code") if isinstance(sub, dict) else None

    # -------------------- PAID PATH --------------------
    if plan_code and plan_code != FREE_PLAN_KEY:
        ensure_period_rollover_if_needed(uid)
        sub, usage = get_usage_state(uid)  # sub has period_start/end, usage tracks count

        if not sub or not isinstance(sub, dict):
            plan_code = None  # fallback to free
        else:
            # Ensure row exists for this billing period
            execute_d1_query(
                """
                INSERT OR IGNORE INTO wa_usage_periods
                (user_id, period_start, period_end, used, plan_code)
                VALUES (?, ?, ?, 0, ?)
                """,
                [uid, sub["period_start"], sub["period_end"], sub["plan_code"]],
            )

            # Get current usage
            rows = execute_d1_query(
                """
                SELECT COALESCE(used, 0) AS used
                FROM wa_usage_periods
                WHERE user_id = ? AND period_start = ? AND period_end = ?
                LIMIT 1
                """,
                [uid, sub["period_start"], sub["period_end"]],
            )
            used = int(rows[0]["used"]) if rows and "used" in rows[0] else 0
            quota = int(PLAN_QUOTAS.get(plan_code, {}).get("questions", 0))

            new_used = used + 1
            if new_used > quota:  # block after exceeding
                logger.info(f"Paid limit reached for {uid}: {used}/{quota}")
                send_whatsapp(
                    to_wa_recipient(uid),
                    f"🔒 You've used {used}/{quota} questions!\n\n"
                    "🔓 Upgrade to continue:\n\n"
                    "• ~₹29~ *₹9* → 2 more questions (valid 24 hrs)\n"
                    "• ~₹149~ *₹49* → 10 questions (valid 7 days)\n\n"
                    "Choose a plan to continue your cosmic journey! 💫\n\n"
                    "*Reply with 9 or 49 to upgrade now!*"
                )
                return False

            # Commit increment safely
            execute_d1_query(
                """
                UPDATE wa_usage_periods
                SET used = ?
                WHERE user_id = ? AND period_start = ? AND period_end = ?
                """,
                [new_used, uid, sub["period_start"], sub["period_end"]],
            )
            bar_length = min(20, max(5, quota // 2))
            filled = int((new_used / quota) * bar_length)
            empty = bar_length - filled
            quota_message = f"💫 Usage: [{'█'*filled}{'░'*empty}] ({quota - new_used}/{quota} Questions left)"
            send_whatsapp(to_wa_recipient(uid), quota_message)
            logger.info(f"[USAGE OK-PAID] {from_number} used {new_used}/{quota} (plan={plan_code})")
            return True

    # -------------------- FREE PATH --------------------
    free_limit = int(PLAN_QUOTAS.get(FREE_PLAN_KEY, {}).get("questions", 3))
    rows = execute_d1_query(
        "SELECT COALESCE(count, 0) AS count FROM user_message_counters WHERE user_id = ? LIMIT 1",
        [uid],
    )
    current_count = int(rows[0]["count"]) if rows and "count" in rows[0] else 0

    new_count = current_count + 1
    if new_count > free_limit:  # block after exceeding
        logger.info(f"Free tier limit reached for {uid}: {current_count}/{free_limit}")
        send_whatsapp(
            to_wa_recipient(uid),
            "*✨ You’ve reached your 3 free questions!*\n\n"
            "🔓 *Unlock more answers from the stars:*\n\n"
            "• ~₹29~ *₹9* → 2 more questions (valid 24 hrs)\n"
            "• ~₹149~ *₹49* → 10 questions (valid 7 days)\n\n"
            "*Reply with 9 or 49 to upgrade now!*"
            
        )
        return False

    # Commit increment safely
    if rows:
        execute_d1_query(
            "UPDATE user_message_counters SET count = ?, last_reset = ? WHERE user_id = ?",
            [new_count, datetime.utcnow().isoformat(), uid],
        )
    else:
        execute_d1_query(
            "INSERT INTO user_message_counters (user_id, count, last_reset) VALUES (?, ?, ?)",
            [uid, new_count, datetime.utcnow().isoformat()],
        )

    bar_length = min(20, max(5, free_limit // 2))
    filled = int((new_count / free_limit) * bar_length)
    empty = bar_length - filled
    quota_message = f"💫 Usage: [{'█'*filled}{'░'*empty}] ({free_limit - new_count}/{free_limit} Questions left)"
    send_whatsapp(to_wa_recipient(uid), quota_message)
    logger.info(f"[USAGE OK-FREE] {from_number} used {new_count}/{free_limit}")

    return True



def call_worker1(natal_chart: dict) -> dict:
    """Call worker for cosmic guidance with proper payload structure"""
    try:
        # Prepare payload with required structure
        payload = {
            "natal_chart": natal_chart,
            "name": natal_chart.get("name", "User"),
            "language": "en"  # Add language if available
        }
        
        res = requests.post(
            f"{WORKER}/cosmic-guidance",
            json=payload,
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
            timeout=30
        )
        res.raise_for_status()
        return res.json()
    except Exception as e:
        logger.error(f"Worker call failed: {e}")
        # Return fallback response
        return {
            "decision": "Yes",
            "confidence": 85,
            "reasoning": "The stars are aligning in your favor!",
            "best_timing": "Anytime this week",
            "bonus_tip": "Trust your intuition"
        }


def summarize_user_ask(last_user_text: str) -> str:
    if not last_user_text:
        return ""
    t = last_user_text.strip().rstrip("?!.")
    if len(t) > 140:
        return t[:137] + "..."
    return t

def dynamic_intro(name: str, intent: str, last_user_text: str,
                  sun_sign: str = None, moon_sign: str = None) -> str:
    ask = summarize_user_ask(last_user_text)
    if ask:
        # Intent-aware intros
        if intent in ("career", "daily"):
            return f"{name}, asked about “{ask}”. Checked birth chart and current transits for alignment."
        if intent == "love":
            return f"{name}, asked about “{ask}”. Looked at Venus/Moon factors and current influences."
        if intent == "health":
            return f"{name}, asked about “{ask}”. Considered vitality markers and today’s transits."
        # generic
        return f"{name}, asked “{ask}”. Assessed your chart and present planetary influences."
    # Fallbacks when no explicit ask is found
    if sun_sign and moon_sign:
        return f"{name}, here’s today’s snapshot for a {sun_sign} Sun, {moon_sign} Moon."
    return f"{name}, here’s today’s personalized cosmic snapshot."


BUTTON_TITLE_STOPLIST = {
    "Daily Horoscope", "Ask Question", "Lucky Number",
    "Compatibility", "Get Cosmic Guidance", "Exit to Main",
    "Cancel", "Skip", "Change Language"
}

def is_natural_text(s: str) -> bool:
    if not s:
        return False
    t = s.strip()
    # Exclude one-character or pure emoji-only blips
    if len(t) < 2:
        return False
    # Heuristic: exclude common button titles/commands
    if t in BUTTON_TITLE_STOPLIST:
        return False
    # Exclude likely command tokens
    if t.startswith(("/", "#", ".")) or t.upper() in {"HI", "HELLO"}:
        return False
    # Require at least one letter to avoid numeric-only or symbols-only messages
    return bool(re.search(r"[A-Za-z]", t))

def get_last_natural_user_text(
    context_manager,
    user_id: str,
    current_webhook_value: Dict[str, Any] = None
) -> Optional[str]:
    """
    Returns the most recent meaningful free-form user text.
    1) Try conversation history via context_manager (newest first).
    2) Fallback to current webhook's text message if present.
    """
    # 1) Try recent history (implement get_user_messages to suit your store)
    try:
        recent: List[Dict[str, Any]] = context_manager.get_user_messages(user_id, limit=20)  # newest first
        for msg in recent:
            if not isinstance(msg, dict):
                continue
            # Expect structure like {"role":"user","type":"text","text":"..."} in your store
            if msg.get("role") == "user":
                if msg.get("type") == "text":
                    txt = (msg.get("text") or "").strip()
                    if is_natural_text(txt):
                        return txt
                # If interactive, ignore button titles
    except Exception:
        pass

    # 2) Fallback: current webhook payload
    try:
        if current_webhook_value:
            messages = current_webhook_value.get("messages") or []
            if isinstance(messages, list) and messages:
                m0 = messages or {}
                if m0.get("type") == "text":
                    txt = (m0.get("text", {}) or {}).get("body", "") or ""
                    if is_natural_text(txt):
                        return txt
                # Ignore interactive.button_reply.title here
    except Exception:
        pass

    return None



async def handle_payment_plan_selection(from_number: str, plan_id: str):
    """Handle payment plan selection"""
    plan = PAYMENT_PLANS.get(plan_id)
    if not plan:
        send_whatsapp(from_number, "❌ Invalid plan. Please choose 9 or 49.")
        return {"status": "invalid_plan"}

    reference_id = f"ORDER-{from_number}-{int(time.time())}"

    # Save payment record
    upsert_payment(
        reference_id, from_number,
        plan["amount"], "INR", "created",
        raw_event=json.dumps({"reason": "user_selected_plan"})
    )

    try:
        # Send UPI intent message
        send_upi_intent_payment_message(
            to_e164=f"whatsapp:{from_number}",
            reference_id=reference_id,
            amount_in_paise=plan["amount"],
            description=plan["description"],
            configuration_name_or_id=settings.WA_PAYMENT_CONFIGURATION,
            items=[{"name": plan["description"], "amount": plan["amount"], "quantity": 1}]
        )
        
        update_payment_status(reference_id, "pending", {"reason": "upi_intent_sent"})
        
        # Send confirmation message
        send_whatsapp(
            from_number,
            f"💰 *Payment Request Sent* 💰\n\n"
            f"Please complete the payment for {plan['description']}.\n\n"
            f"📋 *Reference ID:* {reference_id}\n\n"
            f"Once payment is completed, you'll get immediate access to all features! ✨"
        )
        
        return {"status": "upi_intent_sent", "reference_id": reference_id}
    
    except Exception as e:
        logger.error(f"UPI intent send failed: {e}")
        send_whatsapp(from_number, "⚠️ Failed to send payment request. Please try again.")
        return {"status": "error", "reason": "upi_send_failed"}




users = {}
question_states = {}
compatibility_sessions = {}
def to_wa_recipient(wa_id: str) -> str:
    return wa_id if str(wa_id).startswith("whatsapp:") else f"whatsapp:{wa_id}"

@app.get("/whatsapp")
async def whatsapp_webhook_verify(request: Request):
    params = dict(request.query_params)
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == VERIFY_TOKEN
    ):
        # Verification successful, echo back challenge
        return PlainTextResponse(params.get("hub.challenge", ""), status_code=200)
    return PlainTextResponse("Error, invalid token", status_code=403)


@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    global context_manager

    buttons = []  
    footer=None
    try:
        raw_body = await request.body()
        payload = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse JSON: {e}")
        return PlainTextResponse("Invalid JSON", status_code=400)
    body = json.loads(raw_body.decode("utf-8"))
    logger.info(f"Incoming WA webhook: {json.dumps(body)[:500]}")

    reply = None
    from_number = None
    text = None
    message_id = None
    reaction_emoji = None
    use_location_request = False
    lang_code = None
    msg_count = None
    feedback_reply = None

    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
    except Exception as e:
        logger.error(f"Failed to extract message info: {e}")
        return PlainTextResponse("Invalid message payload", status_code=400)


    logger.info(f"Incoming WhatsApp webhook payload: {json.dumps(payload)}")
    # 1) Handle payment status updates delivered via statuses[type=payment]
    try:
        for status_obj in value.get("statuses", []) or []:
            if status_obj.get("type") == "payment":
                payment_info = status_obj.get("payment", {}) or {}
                tx_id = payment_info.get("reference_id") or (payment_info.get("transaction", {}) or {}).get("id")
                status_text = (status_obj.get("status") or "").lower()

                amt = payment_info.get("amount", {}) or {}
                amount_value = int(amt.get("value", 0))            # e.g., 900
                amount_offset = int(amt.get("offset", 100)) or 100 # e.g., 100
                normalized_amount = amount_value / amount_offset   # e.g., 9.0
                currency = payment_info.get("currency", "INR")
                payer_wa_id = status_obj.get("recipient_id")
                if not payer_wa_id:
                    logger.warning("Payment status without recipient_id; ignoring")
                    return JSONResponse({"status": "payment status ignored"})

                user_key = normalize_user_id(payer_wa_id)          # for DB/billing
                recipient = to_wa_recipient(payer_wa_id)           # for sending

                update_payment_status(tx_id, status_text, {"source": "wa_status_payment", "payload": payment_info})

                if status_text in ("success", "captured", "completed"):
                    if normalized_amount == 9.0 or amount_value == 900:
                        activate_subscription(user_key, "9", external_sub_id=tx_id)
                        send_whatsapp(recipient, "✅ Payment received for ₹9 plan (2 questions / 24 hrs).")
                    elif normalized_amount == 49.0 or amount_value == 4900:
                        activate_subscription(user_key, "49", external_sub_id=tx_id)
                        send_whatsapp(recipient, "✅ Payment received for ₹49 plan (10 questions / 7 days).")
                    else:
                        activate_subscription(user_key, "custom", external_sub_id=tx_id)
                        send_whatsapp(recipient, f"✅ Payment received: {normalized_amount:.2f} {currency}. Subscription updated.")
                else:
                    send_whatsapp(recipient, f"⚠️ Payment status: {status_text.upper()}. Please try again.")

                return JSONResponse({"status": "payment status handled"})
    except Exception as e:
        logger.exception(f"Error handling payment status: {e}")
        # Return 200 so Meta does not retry indefinitely; log for investigation
        return JSONResponse({"status": "payment status error"})

    try:
        if "flow" in payload.get("message", {}):
            user_id = payload["from"]
            message_id = payload["message"]["id"]
            flow_payload = payload["message"]["flow"]["payload"]
            handle_feedback_flow_webhook(user_id, message_id, flow_payload)
        if "payment" in value:
            payment_info = value.get("payment") or {}
            tx_id = payment_info.get("reference_id") or (payment_info.get("transaction", {}) or {}).get("id")
            status_text = (payment_info.get("status") or "").lower()

            amt = payment_info.get("amount", {}) or {}
            amount_value = int(amt.get("value", 0))
            amount_offset = int(amt.get("offset", 100)) or 100
            normalized_amount = amount_value / amount_offset
            currency = payment_info.get("currency", "INR")
            payer_wa_id = (payment_info.get("payer", {}) or {}).get("wa_id") or ((value.get("statuses", [{}])[0] or {}).get("recipient_id"))
            if not payer_wa_id:
                logger.warning("Root payment without payer_wa_id; ignoring")
                return JSONResponse({"status": "payment ignored"})

            user_key = normalize_user_id(payer_wa_id)
            recipient = to_wa_recipient(payer_wa_id)

            update_payment_status(tx_id, status_text, {"source": "wa_payment_root", "payload": payment_info})

            if status_text in ("success", "captured", "completed"):
                if normalized_amount == 9.0 or amount_value == 900:
                    activate_subscription(user_key, "9", external_sub_id=tx_id)
                    send_whatsapp(recipient, "✅ Payment received for ₹9 plan (2 questions / 24 hrs).")
                elif normalized_amount == 49.0 or amount_value == 4900:
                    activate_subscription(user_key, "49", external_sub_id=tx_id)
                    send_whatsapp(recipient, "✅ Payment received for ₹49 plan (10 questions / 7 days).")
                else:
                    activate_subscription(user_key, "custom", external_sub_id=tx_id)
                    send_whatsapp(recipient, f"✅ Payment received: {normalized_amount:.2f} {currency}. Subscription updated.")
            else:
                send_whatsapp(recipient, f"⚠️ Payment status: {status_text.upper()}. Please try again.")

            return JSONResponse({"status": "payment handled"})
    except Exception as e:
        logger.exception(f"Error handling root payment: {e}")
        return JSONResponse({"status": "payment error"})

    messages = value.get("messages", []) or []
    if not messages:
        # Not a payment; not a message either — nothing to do
        return JSONResponse({"status": "no message"})
    messages = value.get("messages", [])
    msg = messages[0]
    from_number = msg["from"]
    user_id = normalize_user_id(from_number)
    message_id  = messages[0].get("id")
    msg_type = msg.get("type")
    button_id = msg.get("interactive", {}).get("button_reply", {}).get("id")
    display_name = None
   

    contacts_list = value.get("contacts") or []
    if isinstance(contacts_list, list) and len(contacts_list) > 0:
        first_contact = contacts_list or {}
        if isinstance(first_contact, dict):
            profile = first_contact.get("profile") or {}
            display_name = profile.get("name")

    if button_id == "skip_current_flow":
        users.pop(from_number, None)
        compatibility_sessions.pop(f"compat_{from_number}", None)
        reply = "Current flow skipped. What would you like to do?"
        buttons = ["Daily Horoscope", "Ask Question", "Compatibility"]

    if msg_type == 'text':
        text = msg['text']['body'].strip() if 'text' in msg and 'body' in msg['text'] else None

    elif msg_type == "payment":
        logger.warning("Received payment msg of unknown structure: %s", json.dumps(msg))

        payment_info = msg.get("payment", {})
        status = payment_info.get("status", "").lower()
        amount = int(payment_info.get("amount", 0))  # value is in paise
        currency = payment_info.get("currency", "INR")
        tx_id = payment_info.get("transaction_id") or payment_info.get("reference_id")

        logger.info(f"[PAYMENT EVENT] status={status}, amount={amount}, currency={currency}, tx_id={tx_id}")

        # Always update DB first
        update_payment_status(
            tx_id,
            status,
            {"source": "whatsapp_message_event", "payload": payment_info}
        )

        if status in ("success", "captured", "completed"):
            user_key = normalize_user_id(from_number)
            if amount == 900:   # ₹9
                activate_subscription(user_key, "9", external_sub_id=tx_id)
                plan_text = "✅ Payment received for ₹9 plan (2 questions / 24 hrs)."
            elif amount == 4900:  # ₹49
                activate_subscription(user_key, "49", external_sub_id=tx_id)
                plan_text = "✅ Payment received for ₹49 plan (10 questions / 7 days)."
            else:
                activate_subscription(user_key, "custom", external_sub_id=tx_id)
                plan_text = f"✅ Payment received: {amount/100:.2f} {currency}. Your subscription is updated."
            send_whatsapp(user_key, plan_text)
        else:
            send_whatsapp(f"whatsapp:{from_number}", f"⚠️ Payment status: {status.upper()}. Please try again.")

    elif msg_type == 'interactive':
        interactive = msg['interactive']
        itype = interactive.get('type')
        if itype == 'button_reply':
            button_reply = interactive.get('button_reply', {})
            button_id = button_reply.get('id')
            text = button_reply.get('title', '').strip()
            if button_id in ["plan_9", "plan_49"]:
                plan_id = button_id.replace("plan_", "")
                return await handle_payment_plan_selection(from_number, plan_id)

            user_id = from_number
        elif itype == 'list_reply':
            selected_id = msg['interactive']['list_reply']['id']
            # success = switch_active_profile(from_number, selected_id)
            # reply = "Switched to profile successfully!" if success else "Failed to switch profile."
            # send_whatsapp(from_number, reply)
            if selected_id == "exit_main":
                deactivate_all_profiles(from_number)
                user_data = get_user(from_number)
                name = user_data["name"] if user_data else "Your"
                reply = f"✨ Welcome back to {name} main profile! How can I assist you?"
                buttons = ["Daily Horoscope", "Ask Question", "Compatibility"]
                send_whatsapp_interactive(from_number, reply, buttons)
            else:
                if switch_active_profile(from_number, selected_id):
                    profile = execute_d1_query(
                        "SELECT name FROM user_profiles WHERE profile_id = ?",
                        [selected_id]
                    )[0]
                    reply = f"✨ Switched to {profile['name']}'s profile! What would you like to do?"
                    buttons = ["Daily Horoscope", "Get Cosmic Guidance", "Exit to Main"]
                    send_whatsapp_interactive(from_number, reply, buttons)
            text = selected_id
            return {"status": "switched"}

    elif msg_type == 'location':
        location = msg['location']
        lat = location['latitude']
        lng = location['longitude']
        location_name = location.get('name', 'Custom Location')
        text = f"location:{lat},{lng}:{location_name}"
        logger.info(f"Received location: {lat}, {lng} - {location_name}")
    
    elif msg_type == 'reaction':
        reaction_emoji = msg['reaction']['emoji']
        text = reaction_emoji
    if msg_type == 'image':
        # Log the event
        logger.info(f"User {from_number} uploaded an image in the flow.")

        send_whatsapp(
            from_number,
            "Thank you for sharing! However, I can only process text in this flow. Please provide your response as text."
        )
        return {"status": "image_not_supported"}
    try:
        send_typing_indicator(WA_PHONE_NUMBER_ID, message_id, WA_ACCESS_TOKEN)
        message_id = msg.get("id")
        if is_duplicate_message(message_id):
            return JSONResponse({"status": "duplicate"})

    except Exception as e:
        logger.error(f"Failed to mark blue tick: {e}")
    if text == "Change Language":
        if from_number not in users:
            users[from_number] = {"stage": "choose_language"}
        else:
            users[from_number]["stage"] = "choose_language"
        send_language_selector(from_number, "Please choose your preferred language:")
        return {"status": "sent"}

    if text and text.strip() in LANGUAGES:
        chosen_lang_code = LANGUAGES[text.strip()]
        sess = users.setdefault(from_number, {})
        sess["language"] = chosen_lang_code
        update_user_language(from_number, chosen_lang_code)

        confirmations = {
            "en": "✅ Language switched to English!",
            "hi": "✅ भाषा हिंदी में बदल गई!",
            "hi-en": "✅ Language Hinglish (Roman) mein badal gayi!",
        }
        send_whatsapp(from_number, confirmations.get(chosen_lang_code, confirmations["en"]))

        # Determine if returning user by presence of active profile with natal_chart
        _active = get_active_profile(from_number)
        has_active_profile = bool(_active and isinstance(_active, dict) and _active.get("natal_chart"))

        if has_active_profile:
            # Returning user: greet and show main actions
            reply = PROMPTS["casual_greet_message"][chosen_lang_code]
            buttons = ["Daily Horoscope", "Ask Question", "Compatibility"]
            send_whatsapp_interactive(from_number, reply, buttons)
            return {"status": "language_changed_returning"}
        else:
            # New user: show privacy next
            sess["stage"] = "show_privacy"
            reply = PROMPTS["welcome_privacy_message"][chosen_lang_code]
            buttons = [PROMPTS["privacy_continue_button"][chosen_lang_code]]
            send_whatsapp_interactive(from_number, reply, buttons)
            return {"status": "language_changed_new"}

    user_data = get_active_profile(from_number)

    special_intent = detect_special_intent(text)
    if special_intent == 'create_profile':
        # Start new profile creation flow
        if from_number not in users:
            users[from_number] = {}
        users[from_number]["stage"] = "new_profile"
        users[from_number]["new_profile_data"] = {}
        
        # Send name prompt
        lang_code = get_user_language(user_data, users, from_number)
        reply = PROMPTS["name"][lang_code]
        send_whatsapp(from_number, reply)
        return {"status": "profile_creation_started"}
    if text == "Change Language" or special_intent == 'change_language':
        if from_number not in users:
            users[from_number] = {"stage": "choose_language"}
        else:
            users[from_number]["stage"] = "choose_language"
        send_language_selector(from_number, "Please choose your preferred language:")
        return {"status": "sent"}
  



    if special_intent:
        logger.info(f"Detected special intent: {special_intent} for text: '{text}'")
        user_data = get_active_profile(from_number)
        if text == "Daily Horoscope":
                text = "today-horoscope"
                reaction_emoji = "🌟"
        elif text == "Compatibility":
                text = "compatibility"
                reaction_emoji = "💕"
        elif text == "Career Focus":
                text = "What career opportunities are coming for me?"
                reaction_emoji = "💼"
        elif text == "Love Advice":
                text = "What does my love life look like this month?"
                reaction_emoji = "❤️"   
        elif text == "Health Tips":
                text = "What health guidance do my stars suggest?"
                reaction_emoji = "💪"
        elif text == "Chat With AI Astrologer":
                text = "I'm ready for a personal consultation"
                reaction_emoji = "🧙‍♂️"
        elif text == "Another Question":
                text = "Ask me another question"
                reaction_emoji = "❓"
        elif text == "Diet Tips":
                text = "What dietary recommendations do my stars suggest?"
                reaction_emoji = "🥗"
        elif text == "Exercise Plan":
                text = "What physical activities align with my cosmic energy?"
                reaction_emoji = "🏋️"
        elif text == "Mental Wellness":
                text = "How can I improve my mental wellness based on my zodiac?"
                reaction_emoji = "🧠"
       
        elif text == "Ask Question":
                # Set state to indicate we're waiting for a question
                question_states[from_number] = True
                reaction_emoji = "❓"
                send_whatsapp_interactive(from_number, "Sure! What would you like to ask? ✨", ["Cancel Question"])

                return {"status": "sent"}

        elif text == "Change Language":
            if from_number not in users:
                users[from_number] = {"stage": "choose_language"}
            else:
                users[from_number]["stage"] = "choose_language"
            send_language_selector(from_number, "Please choose your preferred language:")
            return {"status": "sent"}

        elif text == "Restart Session":
                users.pop(from_number, None)
                text = "restart"
                reaction_emoji = "🔄"

        # trigger_feedback = False

        # # 1️⃣ Check text reactions
        # if text and text.strip():
        #     normalized_text = normalize_emoji(text.strip())
        #     logger.info(f"Normalized text: '{normalized_text}'")
            
        #     # Check for thumbs up/down in any variation
        #     if any(emoji in normalized_text for emoji in ["👍", "👎", "THUMBS UP", "THUMBS DOWN"]):
        #         trigger_feedback = True

        # # 2️⃣ Check actual reaction events
        # if reaction_emoji and reaction_emoji.strip():
        #     normalized_reaction = normalize_emoji(reaction_emoji.strip())
        #     logger.info(f"Normalized reaction: '{normalized_reaction}'")
            
        #     if any(emoji in normalized_reaction for emoji in ["👍", "👎", "THUMBS UP", "THUMBS DOWN"]):
        #         trigger_feedback = True

        # # 3️⃣ Check button replies
        # if button_id in ("feedback_up", "feedback_down"):
        #     trigger_feedback = True

        # # 4️⃣ Trigger feedback flow and return immediately
        # if trigger_feedback:
        #     try:
        #         start_feedback_flow(from_number)  # triggers your WhatsApp Flow
        #         logger.info(f"[FEEDBACK] Flow triggered for {from_number}")
        #     except Exception as e:
        #         logger.error(f"[FEEDBACK] Failed to trigger flow: {e}", exc_info=True)
        #     return {"status": "flow_triggered"}

        # feedback_flow with text process

        if from_number in feedback_sessions:
            handled = process_text_feedback_step(from_number, msg)
            if handled:
                return {"status": "feedback_step"}

        # 2) Trigger detection (emoji, buttons, or intent)
        trigger_feedback = False
        inferred_rating = None
        if text:
            normalized_text = normalize_emoji(text.strip())
            if any(t in normalized_text for t in ["👍", "THUMBS UP"]):
                trigger_feedback = True
                inferred_rating = "up"
            if any(t in normalized_text for t in ["👎", "THUMBS DOWN"]):
                trigger_feedback = True
                inferred_rating = "down"

        if button_id in ("feedback_up", "feedback_down"):
            trigger_feedback = True
            inferred_rating = "up" if button_id == "feedback_up" else "down"

        if special_intent == "give_feedback":
            trigger_feedback = True

        if trigger_feedback:
            start_text_feedback(from_number, message_id=message_id, inferred_rating=inferred_rating,display_name=display_name)
            logger.info(f"[FEEDBACK] Text-based flow started for {from_number} (seed={inferred_rating})")
            return {"status": "flow_triggered"}


        if special_intent == 'change_language':
            logger.info(f"User {from_number} wants to change language, sending selector.")
            if from_number not in users:
                users[from_number] = {}
            users[from_number]["stage"] = "choose_language"
            send_language_selector(from_number, "Please choose your preferred language:")
            return {"status": "sent"}

        elif special_intent == 'delete_data':
            delete_user(from_number)

            # terminate any active subscriptions + reset counters
            terminate_subscription(from_number, reason="user_deleted")

            # also reset free-tier counter explicitly
            from app.services.cloudflare.users_service import reset_user_message_count
            reset_user_message_count(from_number)

            if context_manager:
                context_manager.clear_user_context(from_number)

            reply = "Your data has been deleted. You can start fresh by sending 'hi'."
            send_whatsapp(from_number, reply)
            return {"status": "sent"}

        elif special_intent == "give_feedback":
            try:
                send_feedback_rating_prompt(from_number)
                # start_feedback_flow(from_number)
                logger.info(f"[FEEDBACK] WhatsApp Flow triggered for user {from_number}")
            except Exception as e:
                logger.error(f"[FEEDBACK] Failed to trigger WhatsApp Flow for {from_number}: {e}", exc_info=True)
            # Immediately return to prevent hitting LLM
            return {"status": "flow_triggered"}

        elif special_intent == 'restart':
            users.pop(from_number, None)
            if context_manager:
                context_manager.clear_user_context(from_number)
            reply = "Sure! Let's start over. Send 'hi' to begin."
            send_whatsapp(from_number, reply)
            return {"status": "sent"}
        elif special_intent == "casual_hello" and user_data:
            reaction_emoji = "👋"
            reply = f"Hey {user_data['name'] if user_data else 'there'}! {PROMPTS['casual_greet_message'][get_user_language(user_data, users, from_number)]}"
            buttons = ["Daily Horoscope", "Ask Question", "Compatibility"]
            send_whatsapp_interactive(from_number, reply, buttons,footer="Enjoying this? Send 👍/👎 to share quick feedback")
            return {"status": "casual_greeting_handled"}
        elif special_intent == "start_compatibility":
            if user_data:
                if not ensure_llm_quota(user_id, from_number):
                  return JSONResponse({"status": "limit_reached"})
                comp_msg = handle_compatibility_flow(from_number, "compatibility", user_data)
                if comp_msg:
                    send_whatsapp(from_number, comp_msg)
                else:
                    send_whatsapp(from_number, "Let's start by getting your partner's details.")
            else:
                send_whatsapp(from_number, "You need to complete your profile first. Send 'hi' to start!")
            return {"status": "compatibility_trigger_handled"}
        if special_intent == "initiate_payment":
            send_payment_prompt(to=from_number,user_id=from_number)
            return PlainTextResponse("OK", status_code=200)
        
        elif special_intent == "select_payment_plan":
            plan_id = text
            try:
                from app.services.whatsapp.payments import send_upi_intent_payment_message
                from app.config.settings import settings
                
                plan = PAYMENT_PLANS[plan_id]
                reference_id = f"ORDER-{from_number}-{int(time.time())}"
                
                # Send UPI intent message directly
                send_upi_intent_payment_message(
                    to_e164=f"whatsapp:{from_number}",
                    reference_id=reference_id,
                    amount_in_paise=plan["amount"],
                    description=plan["description"],
                    configuration_name_or_id=settings.WA_PAYMENT_CONFIGURATION,
                    items=[{"name": plan["description"], "amount": plan["amount"], "quantity": 1}]
                )
                
                send_whatsapp(from_number, "📨 Payment request sent. Tap to pay via UPI inside WhatsApp.")
                return {"status": "payment_invoice_sent"}
            except Exception as e:
                logger.error(f"Failed to send UPI intent: {e}")
                send_whatsapp(from_number, "❌ Couldn't send the payment request. Try again.")
                return {"status": "error"}

                
        elif special_intent == "view_chart":
                if not ensure_llm_quota(user_id, from_number):
                   return JSONResponse({"status": "limit_reached"})

                user = get_user(from_number)  
                if user:
                    try:
                        dob_str = user_data.get("dob") if user_data else user.get("dob")
                        btime_str = user_data.get("birth_time") if user_data else user.get("birth_time")
                        lat = float(user_data.get("lat") if user_data else user.get("lat"))
                        lng = float(user_data.get("lng") if user_data else user.get("lng"))
                        tz_str = user_data.get("timezone") if user_data else user.get("timezone")
                        name_str = user_data.get("name") if user_data else user.get("name")

                        birth_date = parse_date_flexible_safe(dob_str)
                        hour, minute = parse_time_flexible_safe(btime_str)

                        send_user_chart_pdf(
                            to_e164=f"whatsapp:{from_number}",  
                            name=name_str or "Friend",
                            year=birth_date.year,
                            month=birth_date.month,
                            day=birth_date.day,
                            hour=hour,
                            minute=minute,
                            lat=lat,
                            lng=lng,
                            tz_str=tz_str,
                            wa_phone_number_id=WA_PHONE_NUMBER_ID,
                            wa_access_token=WA_ACCESS_TOKEN,
                            caption=f"Here's your natal chart, {name_str or 'Friend'}! 🌌"
                        )
                        return {"status": "chart_sent"}
                    except Exception as e:
                        logger.error(f"Chart generation failed: {e}", exc_info=True)
                        reply = "There was an error generating your chart. Please try again later."
                        send_whatsapp(from_number, reply)
                        return {"status": "error", "message": str(e)}

    if text == "manage profiles" or special_intent == "manage_profiles":
        try:
            resp = await profiles_list(ProfileListRequest(user_id=from_number))
            if resp.profiles:
                send_profile_list_whatsapp(from_number, resp.profiles, resp.active_profile_id)
            else:
                send_whatsapp(from_number, "No profiles found. You can create one by sending 'New Profile'.")
            return {"status": "sent"}
        except Exception as e:
            logger.error(f"Profile listing failed: {e}")
            send_whatsapp(from_number, "⚠️ I couldn't access your profiles right now. Please try again later.")
            return {"status": "error"}
            

    if from_number in question_states:
        if text == "Cancel Question" or button_id == "cancel_question":
            del question_states[from_number]
            buttons = ["Daily Horoscope", "Compatibility", "Ask Question"]
            send_whatsapp_interactive(
                from_number,
                "Okay, question cancelled. What would you like to do instead?",
                buttons
            )
            return {"status": "sent"}
        else:
            del question_states[from_number]
            text = f"QUESTION: {text}"  
    
    if from_number in users and users[from_number].get("stage") == "new_profile":
        profile_data = users[from_number]["new_profile_data"]
        lang_code = users[from_number].get("language", "en")
        
        if not profile_data.get("name"):
            profile_data["name"] = text
            reply = PROMPTS["ask_birth_date"][lang_code]
            send_whatsapp(from_number, reply)
            return {"status": "profile_name_set"}
        
        elif not profile_data.get("dob"):
            try:
                birth_date = parse_date_flexible(text)
                profile_data["dob"] = text
                reply = PROMPTS["ask_birth_time"][lang_code]
                send_whatsapp(from_number, reply)
                return {"status": "profile_dob_set"}
            except ValueError:
                reply = PROMPTS["birth_date_error"][lang_code]
                send_whatsapp(from_number, reply)
                return {"status": "error"}

        elif not profile_data.get("birth_time"):
            try:
                hour, minute = parse_time_flexible(text)
                profile_data["birth_time"] = f"{hour}:{minute}"
                reply = PROMPTS["ask_birth_city"][lang_code]
                send_whatsapp(from_number, reply)
                return {"status": "profile_time_set"}
            except ValueError:
                reply = PROMPTS["birth_time_error"][lang_code]
                send_whatsapp(from_number, reply)
                return {"status": "error"}
        
        elif not profile_data.get("birth_city"):
            city_name = text
            profile_data["birth_city"] = city_name
            
            try:
                city_info = get_city_info(city_name)
                profile_data.update(city_info)
                
                # Calculate natal chart
                birth_date = parse_date_flexible(profile_data["dob"])
                hour, minute = profile_data["birth_time"].split(":")
                
                natal_chart = calculate_natal_chart_multi_method(
                    profile_data["name"],
                    birth_date.year,
                    birth_date.month,
                    birth_date.day,
                    int(hour),
                    int(minute),
                    city_info["lat"],
                    city_info["lng"],
                    city_info["tz"]
                )
                
                profile_id = create_profile(
                    from_number,
                    profile_data["name"],
                    profile_data["dob"],
                    profile_data["birth_time"],
                    profile_data["birth_city"],
                    city_info["lat"],
                    city_info["lng"],
                    city_info["tz"],
                    natal_chart
                )

                if profile_id:  
                    switch_active_profile(from_number, profile_id)
                    reply = "✅ New profile created and activated!"
                    buttons = ["Manage Profiles", "Daily Horoscope"]
                    send_whatsapp_interactive(from_number, reply, buttons)
                    new_profile = execute_d1_query(
                        "SELECT * FROM user_profiles WHERE profile_id = ?",
                        [profile_id]
                    )[0]
                    
                    natal_chart_data = json.loads(new_profile["natal_chart"])
                    ai_response = call_worker1(natal_chart_data)
                    
                    decision = ai_response.get("decision", "Maybe")
                    confidence = ai_response.get("confidence", 70)
                    reasoning = ai_response.get("reasoning", "Let me consult your stars deeper.")
                    timing = ai_response.get("best_timing", "Trust your intuition")
                    tip = ai_response.get("bonus_tip", "Stay positive!")
                    
                    # Format and send the response
                    conf_emoji = "🔥" if confidence >= 80 else "✨" if confidence >= 60 else "🌟"
                    decision_emoji = "✅" if decision == "Yes" else "❌" if decision == "No" else "🤔"

                    reply = (
                        f"🌟 *COSMIC GUIDANCE FOR {new_profile['name']}* 🌟\n\n"
                        f"{decision_emoji} *Decision*: {decision} ({confidence}% {conf_emoji})\n\n"
                        f"💫 *Insight*:\n{reasoning}\n\n"
                        f"⏰ *Best Timing*: {timing}\n\n"
                        f"✨ *Cosmic Tip*: {tip}"
                    )
                    
                    send_whatsapp(from_number, reply)
                    del users[from_number]
                    return {"status": "profile_created"}
                else:
                    reply = "⚠️ Failed to create profile. Please try again."
                    send_whatsapp(from_number, reply)
                    return {"status": "error"}

                
            except Exception as e:
                logger.error(f"Profile creation failed: {e}")
                reply = "⚠️ Failed to create profile. Please try again."
                send_whatsapp(from_number, reply)
                return {"status": "error"}

    if user_data:
        # Returning user
        lang_code = get_user_language(user_data, users, from_number)
        compatibility_response = handle_compatibility_flow(from_number, text, user_data)
        if compatibility_response is not None:
            if context_manager:
                    try:
                        user_text = text[:500] if len(text) > 500 else text
                        assistant_text = compatibility_response[:2000] if len(compatibility_response) > 2000 else compatibility_response
                        
                        context_manager.add_message_to_context(
                            user_id=from_number,
                            message_text=user_text,
                            role="user",
                            message_type="compatibility",
                            message_id=message_id
                        )
                        context_manager.add_message_to_context(
                            user_id=from_number,
                            message_text=assistant_text,
                            role="assistant",
                            message_type="compatibility",
                            message_id=message_id
                        )
                    except Exception as e:
                        logger.error(f"Error adding compatibility messages to context: {e}")
                
            # Send reaction if available
            if message_id and reaction_emoji:
                try:
                    send_whatsapp_reaction(from_number, message_id, reaction_emoji)
                except Exception as e:
                    logger.error(f"Failed to send reaction: {e}")
            
            # Send the compatibility response and return early
            if len(compatibility_response) > 1024:
                chunks = split_message(compatibility_response)
                for chunk in chunks[:-1]:
                    send_whatsapp(from_number, chunk)
                    time.sleep(0.5)
                send_whatsapp(from_number, chunks[-1])
            else:
                send_whatsapp(from_number, compatibility_response)
            
            return {"status": "compatibility_handled"}

        elif text.lower() == "delete my data":
            reaction_emoji="😢"
            delete_user(from_number)
            if context_manager:
                context_manager.clear_user_context(from_number)
            reply = "Your data has been deleted."
        elif text.lower() == "clear chat context":
            reaction_emoji= "✨"
            if context_manager:
                context_manager.clear_user_context(from_number)
            reply = "Chat history cleared! Starting fresh. ✨"
            buttons = ["Daily Horoscope", "Ask Question", "Compatibility"]
        contact = payload['entry'][0]['changes'][0]['value']['contacts'][0]
        wa_id = contact['wa_id']  # e.g. "918870516028"
        name = contact['profile']['name']  # e.g. "Ronak(Ronu)"

        if text.lower() in ("view my chart", "view kundli"):
            if not ensure_llm_quota(user_id, from_number):
                return JSONResponse({"status": "limit_reached"})

            user = get_user(from_number)
            if user:
                try:
                    dob_str = user_data.get("dob") if user_data else user.get("dob")
                    btime_str = user_data.get("birth_time") if user_data else user.get("birth_time")
                    lat = float(user_data.get("lat") if user_data else user.get("lat"))
                    lng = float(user_data.get("lng") if user_data else user.get("lng"))
                    tz_str = user_data.get("timezone") if user_data else user.get("timezone")
                    name_str = user_data.get("name") if user_data else user.get("name")

                    birth_date = parse_date_flexible_safe(dob_str)
                    hour, minute = parse_time_flexible_safe(btime_str)

                    send_user_chart_pdf(
                        to_e164=f"whatsapp:{wa_id}",
                        name=name_str or "Friend",
                        year=birth_date.year,
                        month=birth_date.month,
                        day=birth_date.day,
                        hour=hour,
                        minute=minute,
                        lat=lat,
                        lng=lng,
                        tz_str=tz_str,
                        wa_phone_number_id=WA_PHONE_NUMBER_ID,
                        wa_access_token=WA_ACCESS_TOKEN,
                        caption=f"Here's your natal chart, {name_str or 'Friend'}! 🌌"
                    )
                    return {"status": "chart_sent"}
                except Exception as e:
                    logger.error(f"Chart generation failed: {e}", exc_info=True)
                    reply = "There was an error generating your chart. Please try again later."
                    send_whatsapp(from_number, reply)
                    return {"status": "error", "message": str(e)}



        elif "ask_question_flow" in text.lower():
                question_states[from_number] = True
                buttons = ["Cancel Question"]
                send_whatsapp_interactive(
                    from_number,
                    "Sure! What would you like to know about your cosmic journey? ✨",
                    buttons
                )

        elif text.lower().startswith("update dob"):
            try:
                new_dob = text.split(" ", 2)[2]
                if update_user_dob(from_number, new_dob):
                    reply = "DOB updated and natal chart recalculated!"
                    if context_manager:
                        context_manager.add_message_to_context(
                            user_id=from_number,
                            message_text=f"Updated DOB to {new_dob}",
                            role="system",
                            message_type="update",
                            message_id=message_id
                        )
                else:
                    reaction_emoji= "❓"

                    reply = "Failed to update DOB. Please check the format (e.g., 20/09/2002)."
            except IndexError:
                reaction_emoji= "❓"
                reply = "Please provide the new DOB, e.g., 'update dob 20/09/2002'"

        
        
        else:
            # Use stored natal chart
            try:
                natal_chart = json.loads(user_data["natal_chart"])
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse natal_chart for user {from_number}: {e}")
                reaction_emoji= "❓"
                reply = PROMPTS["cosmic_data_issue"][lang_code]
                buttons = ["Restart"]

                send_whatsapp(from_number, reply)
                return {"status": "error", "message": "Invalid natal chart data"}

            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            transits = get_transits_swisseph(float(user_data["lat"]), float(user_data["lng"]), today_str)
            sun_info = natal_chart.get("Sun", {})
            moon_info = natal_chart.get("Moon", {})
            asc_info = natal_chart.get("Ascendant", {})

            if context_manager:
                    context_manager.add_message_to_context(
                        user_id=from_number,
                        message_text=text,
                        role="user",
                        message_type="text",
                        metadata={"source": "whatsapp", "user_name": user_data.get("name")},
                        message_id=message_id
                    )

            context_summary = ""
            if context_manager:
                try:
                    
                    context_summary = context_manager.get_context_summary(from_number)
                except Exception as e:
                    logger.warning(f"Failed to get context summary: {e}")
                    context_summary = "No previous conversation context available."

            context = (
                f"{sun_info.get('sign', 'Unknown')} sun, {moon_info.get('sign', 'Unknown')} moon, "
                f"ascendant {asc_info.get('sign', 'Unknown')}.\n"
                f"Current transits: {json.dumps(transits)}"
            )

            if "today-horoscope" in text.lower().strip():
                # Call /generate route for daily horoscope
                reaction_emoji = "🌟"

                payload = {
                    "name": user_data.get("name", "Friend"),
                    "natal_chart": natal_chart,
                    "current_transits": transits,
                    "aspects": [],
                    "retrogrades": [],
                    "passages": safe_get_relevant_passages(context),
                    "date": today_str,
                    "language": lang_code
                }
                try:
                    birth_date = datetime.strptime(user_data["dob"], "%d/%m/%Y")
                    birth_hour, birth_minute = parse_time_flexible(user_data["birth_time"])

                    horo_request = HoroscopeRequest(
                        name=user_data["name"],
                        birth_year=birth_date.year,
                        birth_month=birth_date.month,
                        birth_day=birth_date.day,
                        birth_hour=birth_hour,
                        birth_minute=birth_minute,
                        lat=float(user_data["lat"]),
                        lng=float(user_data["lng"]),
                        timezone=user_data["timezone"],
                        date=datetime.utcnow().strftime("%Y-%m-%d"),
                        language=lang_code
                    )

                    response = await generate(horo_request)
                    horoscope_data = response.horoscope

                    # Core summary
                    cosmic_summary = horoscope_data.get('cosmic_summary') or horoscope_data.get('summary') or "A day of cosmic flow awaits."

                    # Helper to safely pick category
                    categories = horoscope_data.get('categories') or {}
                    def pick_cat(name):
                        obj = categories.get(name) or {}
                        if isinstance(obj, list) and obj:
                            obj = obj[0] if isinstance(obj[0], dict) else {}
                        return obj.get("description") or ""

                    energy = pick_cat("Energy")
                    career = pick_cat("Career")
                    relationships = pick_cat("Relationships")
                    health = pick_cat("Health")

                    # Practical guidance (mantra / tips)
                    pg = horoscope_data.get('practical_guidance')
                    tip_line = ""
                    if isinstance(pg, dict):
                        if pg.get("recommended_mantra"):
                            tip_line = f"\n✨ Mantra: {pg['recommended_mantra']}"
                        elif pg.get("lucky_numbers") or pg.get("lucky_colors"):
                            nums = ", ".join(str(n) for n in pg.get("lucky_numbers", [])[:3])
                            cols = ", ".join(pg.get("lucky_colors", [])[:2])
                            tip_line = f"🍀 Lucky: {nums or ''} {cols or ''}".strip()
                    elif isinstance(pg, list) and pg:
                        tip_line = f"\n🍀 Lucky numbers: {', '.join(str(n) for n in pg[:3])}"

                    # personal_message = horoscope_data.get('personal_message') or ""

                    last_user_text = get_last_natural_user_text(context_manager, from_number)  
                    sun = horoscope_data.get("generation_info", {}).get("sun_sign")
                    moon = horoscope_data.get("generation_info", {}).get("moon_sign")
                    intro_line = dynamic_intro(user_data['name'], intent="daily", last_user_text=last_user_text, sun_sign=sun, moon_sign=moon)

                    reply = (
                        f"🌟 {intro_line} 🌟\n\n"
                        f"💫 {cosmic_summary}\n\n"
                    )
                    if energy: reply += f"⚡ *Energy*:\n {energy}\n\n"
                    if career: reply += f"💼 *Career*:\n {career}\n\n"
                    if relationships: reply += f"❤️ *Relationships*:\n {relationships}\n\n"
                    if health: reply += f"🌱 *Health*:\n {health}\n\n"
                    if tip_line: reply += f"\n{tip_line}\n\n"
                    # if personal_message: reply += f"\n💌 {personal_message}"

                    # Keep buttons simple
                    buttons = determine_context_buttons(from_number, context_manager, text)
                    
                    footer="Guided by NASA-verified data, helpful? Send 👍/👎 for feedback"

                except Exception as e:
                    logger.error(f"Daily horoscope request failed: {e}")
                    reaction_emoji = "❓"
                    reply = (
                        f"🌟 *Daily Horoscope Unavailable* 🌟\n\n"
                        f"Your {sun_info.get('sign', 'Unknown')} Sun and {moon_info.get('sign', 'Unknown')} Moon "
                        "suggest a day of potential. Try again later or ask another question! ✨"
                    )

            elif "cosmic guidance" in text.lower().strip():
                if not ensure_llm_quota(user_id, from_number):
                    return JSONResponse({"status": "limit_reached"})

                passages = safe_get_relevant_passages(context + " " + text)
                payload = {
                    "name": user_data["name"],
                    "natal_chart": natal_chart,
                    "current_transits": transits,
                    "aspects": [],
                    "retrogrades": [],
                    "passages": passages,
                    "question": text,
                    "date": today_str,
                    "language": lang_code,
                }
                try:
                    ai_response = call_worker(payload)
                    decision = ai_response.get("decision", "Maybe")
                    confidence = ai_response.get("confidence", 70)
                    reasoning = ai_response.get("reasoning", "Let me consult your stars deeper.")
                    timing = ai_response.get("best_timing", "Trust your intuition")
                    tip = ai_response.get("bonus_tip", "Stay positive!")
                    conf_emoji = "🔥" if confidence >= 80 else "✨" if confidence >= 60 else "🌟"
                    decision_emoji = "✅" if decision == "Yes" else "❌" if decision == "No" else "🤔"
                    reaction_emoji= "🔮"

                    reply = (
                        f"🔮 *COSMIC GUIDANCE FOR {user_data['name'].upper()}*\n\n"
                        f"{decision_emoji} *Decision*: {decision} ({confidence}% {conf_emoji})\n\n"
                        f"💫 *Cosmic Insight*:\n{reasoning}\n\n"
                        f"⏰ *Best Timing*: {timing}\n\n"
                        f"🎯 *Cosmic Tip*: {tip}\n\n"
                        "─────────────────────\n"
                        # f"☀️ {sun_info.get('sign', 'Unknown')} Sun • 🌙 {moon_info.get('sign', 'Unknown')} Moon • ⬆️ {asc_info.get('sign', 'Unknown')} Rising\n\n"
                        "Ask another question for more cosmic wisdom! 🪐✨"
                    )
                    buttons = determine_context_buttons(from_number, context_manager, text)
                    footer="Guided by NASA-verified data, helpful? Send 👍/👎 for feedback"


                    # buttons = ["Another Question", "Daily Horoscope", "Compatibility 💖"]

                except Exception as e:
                    logger.error(f"AI worker error: {e}")
                    reaction_emoji= "❓"

                    reply = (
                        "🌟 The cosmic winds are a bit turbulent right now.\n\n"
                        f"Based on your {sun_info.get('sign', 'Unknown')} Sun and {moon_info.get('sign', 'Unknown')} Moon, "
                        "I sense this is important to you. Try asking again! 🔮"
                    )
            else:
                if not ensure_llm_quota(user_id, from_number):
                        return JSONResponse({"status": "limit_reached"})
                
                passages = safe_get_relevant_passages(context + " " + text)
                entry = payload.get("entry", [])[0]
                changes = entry.get("changes", [])[0]
                value = changes.get("value", {})
                messages = value.get("messages", [])
                if not messages:
                    return JSONResponse({"status": "no message"})


                button_reply = msg.get("interactive", {}).get("button_reply")
                is_lucky_number = (
                    button_reply is not None 
                    and (button_reply.get("id") == "btn_0" or button_reply.get("title") == "Lucky Number")
                )
                if is_lucky_number and special_intent == "lucky_number":
                   
                    contextual_prompt = f"""
                        You are a warm, empathetic Vedic astrologer speaking with {user_data.get('name', 'a friend')}.

                        ASTROLOGICAL PROFILE:
                        - Sun: {sun_info.get('sign', 'Unknown')} at {sun_info.get('degree', 0)}°
                        - Moon: {moon_info.get('sign', 'Unknown')} at {moon_info.get('degree', 0)}°
                        - Rising: {asc_info.get('sign', 'Unknown')} at {asc_info.get('degree', 0)}°
                        USERS CONTEXT SUMMARY: {context_summary}
                        DIRECTIONS (numbers + timing for today):
                        1) Use ruler→number mapping: Sun=1, Moon=2, Jupiter=3, Rahu=4, Mercury=5, Venus=6, Ketu=7, Saturn=8, Mars=9. Zodiac rulers: Aries(Mars), Taurus(Venus), Gemini(Mercury), Cancer(Moon), Leo(Sun), Virgo(Mercury), Libra(Venus), Scorpio(Mars), Sagittarius(Jupiter), Capricorn(Saturn), Aquarius(Saturn), Pisces(Jupiter).
                        2) Compute:
                        - Primary number from the rulers of Sun, Moon, and Rising (break ties by Moon, then Rising).
                        - Two alternates from the remaining rulers (if distinct).
                        - A “today booster” from the current Moon’s sign ruler; if unknown, use the day‑lord’s number (Sun→Sun, Mon→Moon, Tue→Mars, Wed→Mercury, Thu→Jupiter, Fri→Venus, Sat→Saturn).
                        3) Best time today:
                        - Give one or two short local windows (e.g., 10–12 and 17–19) aligned to Moon or day‑lord; prefer morning/evening.
                        4) Practical use:
                        - Say how to apply numbers (quick choices, short codes, seat/row picks, counts).
                        5) Style:
                        - WhatsApp markdown, 45–75 words, 1–3 emojis, bold only for the numbers and the “Best time” tag.

                        OUTPUT (single message, no lists/sections/JSON):
                        "👋 Hello user’s name, your lucky numbers are **X**, also **Y**, **Z**.
                        Use them for picks, codes, quick decisions, and small risks today.
                        Best time: **HH–HH** and **HH–HH**.
                        A boost from today’s anchor, e.g., Moon or day‑lord makes **B** extra potent. 🌟"


                        CURRENT QUESTION: {text}
                        Respond concisely and naturally - NO sections, NO JSON!
                    """
                else:
                   contextual_prompt = f"""
You are a warm, empathetic Vedic astrologer speaking with {user_data.get('name', 'a friend')}.

ASTROLOGICAL PROFILE:
- Sun: {sun_info.get('sign', 'Unknown')} at {sun_info.get('degree', 0)}°
- Moon: {moon_info.get('sign', 'Unknown')} at {moon_info.get('degree', 0)}°
- Rising: {asc_info.get('sign', 'Unknown')} at {asc_info.get('degree', 0)}°
- Birth City: {user_data.get('birth_city', 'Unknown')}
- Retrogrades: {', '.join(natal_chart.get('retrogrades', [])) if natal_chart.get('retrogrades') else 'None'}
- Aspects: {', '.join(natal_chart.get('aspects', [])) if natal_chart.get('aspects') else 'None'}
USERS CONTEXT SUMMARY: {context_summary}
CURRENT QUESTION: {text}

RESPONSE REQUIREMENTS (Never ever break this format):
Write ONLY in the following format. Do not use bullet points, stars (*), colons, or extra headings. 
Each section must be short (1,2 sentences max). Split longer thoughts into separate lines.

[Opening greeting, 1–2 sentences, personal tone]

Right now
[2 short sentences. Insert a blank line between them for WhatsApp readability.]

What this means
[2–3 short sentences. Keep each sentence on a separate line.]

Advice for you
[2–3 short sentences. Each on its own line, like chat-style advice.]

Summary
[1–2 short sentences. Positive and uplifting.]

IMPORTANT:
- Never break this format.
- Always insert line breaks (`\\n\\n`) between sentences or sections so it displays cleanly on WhatsApp.
- Do not add JSON, bullet points, or extra formatting.
- Keep the entire response under 250 words.
"""
                llm_payload = {
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a contextual, empathetic Vedic astrologer who remembers previous conversations and provides personalized guidance."
                        },
                        {"role": "user", "content": contextual_prompt}
                    ],
                    "temperature": 0.9,
                    "language": lang_code
                }

                try:
                    response = requests.post(
                        f"{WORKER}/chat",
                        json=llm_payload,
                        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
                        timeout=60
                    )
                    response.raise_for_status()
                    result = response.json()

                    if is_lucky_number and special_intent == "lucky_number":
                        reply = result.get("response") or "I'm unable to answer at the moment."
                        reply = format_lucky_number(reply, user_data.get("name", "friend"))
                        footer = "Guided by NASA-verified data, helpful? Send 👍/👎 for feedback"
                        buttons = ["Profile Switch", "Ask Question", "View Chart"]
                    else:
                        reply = result.get("response") or "I'm unable to answer at the moment."
                        reply = enforce_structure(reply, user_data.get("name", "friend"))
                        reply = format_for_whatsapp(reply)
                        footer = "Guided by NASA-verified data, helpful? Send 👍/👎 for feedback"

                        # only fallback if *really* missing sections
                        markers = ["right now", "what this means", "advice for you"]
                        if not reply.strip():
                            reply = (
                                f"Hello {user_data.get('name', 'friend')}, {reply}\n\n"
                                "Do you have any other questions in your mind?"
                            )

                    # context-based buttons (don’t wipe earlier if already set)
                    if not is_lucky_number:
                        if context_manager:
                            buttons = determine_context_buttons(from_number, context_manager, text)
                        else:
                            buttons = ["Daily Horoscope", "Ask Question", "Compatibility"]


                except Exception as e:
                    logger.error(f"Chat request failed: {e}")
                    reply = (
                        f"🌟 *Cosmic Winds Are Shifting* 🌟\n\n"
                        f"Dear {user_data.get('name', 'Friend')}, your {sun_info.get('sign', 'Unknown')} Sun and {moon_info.get('sign', 'Unknown')} Moon suggest a moment to pause and reflect. "
                        "The stars are aligning, but I couldn't fetch the answer this time.\n\n"
                        "Try asking again or type 'today-horoscope' for your daily cosmic guide! 🔮"
                    )
                    buttons = ["Daily Horoscope", "Ask Question", "Compatibility"]

                # Add to context if needed
                if context_manager and reply:
                    context_manager.add_message_to_context(
                        user_id=from_number,
                        message_text=reply[:1024],
                        role="assistant",
                        message_type="response",
                        metadata={"response_type": "contextual", "user_name": user_data.get("name")},
                        message_id=message_id
                    )

    else:
        # New user
        use_location_request = False
        user = users.setdefault(from_number, {"stage": "welcome"})
        stage = user["stage"]
        logger.info(f"WhatsApp message from {from_number}: {text} (stage: {stage})")
        lang_code = user.get("language") 

        try:
            
            if stage == "welcome" or text.lower() in ['hi', 'hello', 'start', 'restart']:
                user.clear()
                user["stage"] = "choose_language"  
                reaction_emoji = "👋"
                if context_manager:
                    context_manager.clear_user_context(from_number)
                
                send_language_selector(from_number, "Welcome! Please choose your preferred language:")

            elif stage == "choose_language":
                selection = text.strip()
                if selection in LANGUAGES:
                    lang_code = LANGUAGES[selection]
                else:
                    lang_code = "en"
                
                user["language"] = lang_code
                user["stage"] = "show_privacy"  # PRIVACY SECOND, IN SELECTED LANGUAGE
                reaction_emoji = "✅"
                
                reply = PROMPTS["welcome_privacy_message"][lang_code]
                buttons = [PROMPTS["privacy_continue_button"][lang_code]]

            elif stage == "show_privacy":
                user["stage"] = "name"
                reaction_emoji = "✅"
                lang_code = user.get("language", "en")
                
                reply = PROMPTS["name"][lang_code]
                buttons = ["Restart"]

            elif stage == "name":
                user["name"] = text
                user["stage"] = "language"
                user["stage"] = "birth_date"
                reaction_emoji = "👍"
               
                reply = PROMPTS["ask_birth_date"][lang_code]
                
                buttons = ["Restart"]

            elif stage == "birth_date":
                try:
                    user["birth_date"] = parse_date_flexible(text)
                    user["stage"] = "birth_time"
                    date_formatted = user["birth_date"].strftime("%d %B %Y")
                    reaction_emoji = "👍"
                    reply = PROMPTS["ask_birth_time"][lang_code]
                    buttons = ["Restart"]

                except ValueError:
                    reaction_emoji = "❓"
                    reply = PROMPTS["birth_date_error"][lang_code]
                    buttons = ["Restart"]

            elif stage == "birth_time":
                try:
                    hour, minute = parse_time_flexible(text)
                    user["birth_hour"] = hour
                    user["birth_minute"] = minute
                    user["birth_time_str"] = text
                    user["stage"] = "birth_city"

                    if text.lower() in ['unknown', 'not known', 'dont know', "don't know", 'na', 'n/a']:
                        time_msg = "12:00 PM (noon - default)"
                    else:
                        time_msg = f"{hour:02d}:{minute:02d}"
                    reaction_emoji = "👍"
                    reply = PROMPTS["ask_birth_city"][lang_code]
                    
                    use_location_request = True
                    buttons = ["Restart"]

                except Exception as e:
                    logger.error(f"Time parsing error: {e}")
                    reaction_emoji = "❓"
                    reply = PROMPTS["birth_time_error"][lang_code]
                    buttons = ["Restart"]

            elif stage == "birth_city":
                if text and text.startswith("location:"):
                        try:
                            _, coords, name = text.split(":", 2)
                            lat, lng = coords.split(",", 1)
                            user["birth_city"] = name
                            user["lat"] = float(lat)
                            user["lng"] = float(lng)
                            user["timezone"] = tf.timezone_at(lat=float(lat), lng=float(lng)) or "Asia/Kolkata"
                            reaction_emoji = "📍"
                            reply = PROMPTS["creating_cosmic_profile"][lang_code]
                        except Exception as e:
                            logger.error(f"Location parsing error: {e}")
                            reply = PROMPTS["location_error"][lang_code]
                            buttons = ["Restart"]
                            send_whatsapp(from_number, reply)
                            return {"status": "error"}
                else:
                    # Handle typed city
                    user["birth_city"] = text.strip()
                    city_info = get_city_info(text)
                    user["lat"] = city_info["lat"]
                    user["lng"] = city_info["lng"]
                    user["timezone"] = city_info["tz"]
                    reaction_emoji = "🏙️"
                    reply = PROMPTS["creating_cosmic_profile"][lang_code]
            


                user["stage"] = "complete"
                logger.info(f"Birth city: {user['birth_city']} (type: {'location' if 'location:' in text else 'text'})")
                reply = PROMPTS["profile_complete"][lang_code]
                
                send_whatsapp(from_number, reply)

                try:
                    birth_date = user['birth_date']
                    hour = user.get("birth_hour", 12)
                    minute = user.get("birth_minute", 0)

                    if not (0 <= hour <= 23):
                        hour = 12
                    if not (0 <= minute <= 59):
                        minute = 0
                    natal_chart = calculate_natal_chart_multi_method(
                        user.get("name", "User"),
                        birth_date.year,
                        birth_date.month,
                        birth_date.day,
                        hour,
                        minute,
                        user.get("lat", 19.0760),
                        user.get("lng", 72.8777),
                        user.get("timezone", "Asia/Kolkata")
                    )
                    user["natal_chart"] = natal_chart
                    insert_success = insert_user(
                        from_number,
                        user["name"],
                        birth_date.strftime("%d/%m/%Y"),
                        user["birth_time_str"],
                        user["birth_city"],
                        user["lat"],
                        user["lng"],
                        user["timezone"],
                        natal_chart
                    )
                    if insert_success:
                            logger.info(f"User {from_number} inserted successfully")
                            ensure_free_subscription(from_number)
                            # Clear temp onboarding state
                            users.pop(from_number, None)
                            if "language" in user:
                                update_user_language(from_number, user["language"])

                            try:
                                birth_date_dt = user.get("birth_date")  # This is already a datetime during onboarding
                                if not isinstance(birth_date_dt, datetime):
                                    birth_date_dt = parse_date_flexible_safe(user.get("birth_date"))

                                hour, minute = coerce_time_to_hm(user["birth_time_str"])  # Use the string version

                                send_user_chart_pdf(
                                    to_e164=f"whatsapp:{from_number}",  # Use from_number here
                                    name=user.get("name", "Friend"),
                                    year=birth_date_dt.year,
                                    month=birth_date_dt.month,
                                    day=birth_date_dt.day,
                                    hour=hour,
                                    minute=minute,
                                    lat=float(user['lat']),
                                    lng=float(user['lng']),
                                    tz_str=user['timezone'],
                                    wa_phone_number_id=WA_PHONE_NUMBER_ID,
                                    wa_access_token=WA_ACCESS_TOKEN,
                                    caption=f"{user.get('name', 'Your')} natal chart"
                                )

                            except Exception as e:
                                logger.error(f"Chart generation failed: {e}", exc_info=True)

                
                            if context_manager:
                                try:
                                    context_manager.add_message_to_context(
                                        user_id=from_number,
                                        message_text=f"New user registration completed: {user['name']}",
                                        role="system",
                                        message_type="registration",
                                        metadata={"birth_city": user["birth_city"], "name": user["name"]},
                                        message_id=message_id
                                    )
                                except Exception as e:
                                    logger.error(f"Failed to add message to context: {e}")

                    else:
                        logger.error(f"Failed to insert user {from_number} into D1")
                        reply = PROMPTS["cosmic_profile_error"][lang_code]
                        send_whatsapp(from_number,reply)
                        return {"status": "error", "message": "Failed to insert user"}

                    today_str = datetime.utcnow().strftime("%Y-%m-%d")
                    transits = get_transits_swisseph(user["lat"], user["lng"], today_str)
                    sun_info = natal_chart.get('Sun', {})
                    moon_info = natal_chart.get('Moon', {})
                    asc_info = natal_chart.get('Ascendant', {})
                    successful_planets = sum(1 for planet in natal_chart.values() if planet.get('sign') != 'Unknown')
                    if successful_planets >= 3:
                        quality_msg = "🎯 *High Precision Data*" if successful_planets >= 6 else "✨ *Good Quality Data*"
                        reply = (
                            f"🌟 *{user.get('name', 'Your')} Cosmic Profile Complete!* 🌟\n\n"
                            f"{quality_msg}\n\n"
                            f"☀️ *Sun Sign*: {sun_info.get('sign', 'Calculating...')} ({sun_info.get('degree', 0)}°)\n"
                            f"🌙 *Moon Sign*: {moon_info.get('sign', 'Calculating...')} ({moon_info.get('degree', 0)}°)\n"
                            f"⬆️ *Rising Sign*: {asc_info.get('sign', 'Calculating...')} ({asc_info.get('degree', 0)}°)\n\n"
                            "✨ *Your stars are aligned and ready!*\n\n"
                            "💫 Ask me anything:\n"
                            "• Should I change jobs?\n"
                            "• When will I find love?\n"
                            "• What's my lucky time today?\n"
                            "• Will this decision work out?\n"
                            "• What do my stars say about [topic]?\n\n"
                            "Type your question and let the cosmos guide you! 🔮"
                        )

                        buttons = ["Daily Horoscope", "Ask Question", "Compatibility"]
                        footer="Guided by NASA-verified data, helpful? Send 👍/👎 for feedback"


                    else:
                        reply = (
                            f"🌟 *{user.get('name', 'Your')} Cosmic Profile Partial!* 🌟\n\n"
                            "⚡ *Partial Stellar Data Available*\n\n"
                            f"☀️ *Sun Sign*: {sun_info.get('sign', 'Unknown')} ({sun_info.get('degree', 0)}°)\n"
                            f"🌙 *Moon Sign*: {moon_info.get('sign', 'Unknown')} ({moon_info.get('degree', 0)}°)\n"
                            f"⬆️ *Rising Sign*: {asc_info.get('sign', 'Unknown')} ({asc_info.get('degree', 0)}°)\n\n"
                            "🔮 Even with partial data, I can provide cosmic wisdom!\n\n"
                            "Ask me any question - the stars will guide us! ✨"
                        )
                        buttons = ["Daily Horoscope", "Ask Question", "Compatibility"]

                except Exception as e:
                    logger.error(f"Multi-method horoscope calculation failed: {e}")
                    reply = (
                        "⚠️ *Stellar Calculation Complex*\n\n"
                        "The cosmic calculations encountered some deep mysteries. "
                        "This might indicate:\n"
                        "• Very rare birth timing\n"
                        "• Unique celestial configuration\n"
                        "• Temporary cosmic data access issues\n\n"
                        "🔄 Try 'restart' for a fresh attempt, or\n"
                        "💫 Ask me questions anyway - I can still provide guidance! ✨\n\n"
                        "The cosmos works in mysterious ways! 🌌"
                    )
                    buttons = ["Daily Horoscope", "Ask Question", "Compatibility"]

        except Exception as e:
            logger.error(f"WhatsApp webhook error: {e}")
            reply = (
                "⚠️ Cosmic interference detected!\n\n"
                "Something went wrong in the stellar calculations. "
                "Type 'restart' to begin fresh! 🔄✨"
            )
            buttons = ["Restart"]
        finally:
            if message_id and reaction_emoji:
                try:
                    send_whatsapp_reaction(from_number, message_id, reaction_emoji)
                except Exception as e:
                    logger.error(f"Failed to send reaction: {e}")


    if reply:
        if len(reply) > 1800:
            chunks = split_message(reply)
            
            # Send all chunks except last as text messages
            for chunk in chunks[:-1]:
                send_whatsapp(from_number, chunk)
                time.sleep(0.5)  # Brief delay between messages
            
            # Handle last chunk with buttons
            last_chunk = chunks[-1]
            if buttons and len(last_chunk) <= 1024:
                send_whatsapp_interactive(from_number, last_chunk, buttons,footer)
            else:
                send_whatsapp(from_number, last_chunk)
                if buttons:
                    time.sleep(0.5)
                    prompt = "What would you like to do next?"
                    send_whatsapp_interactive(from_number, prompt, buttons,footer)
        else:
            if use_location_request:
                send_whatsapp_location_request(from_number, reply)
            if buttons:
                send_whatsapp_interactive(from_number, reply, buttons,footer)
            else:
                send_whatsapp(from_number, reply)
    return {"status": "sent"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception handler: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error"}
    )
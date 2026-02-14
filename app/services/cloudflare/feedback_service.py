from datetime import datetime
from typing import Dict, Optional
import unicodedata
import uuid

from app.services.cloudflare.d1_client import execute_d1_query
import logging
from app.services.whatsapp.send_messageAndEvents import send_feedback_flow_template, send_whatsapp, send_whatsapp_interactive_v2
logger = logging.getLogger(__name__)


feedback_sessions: Dict[str, dict] = {}  # key: user_id (E.164), value: {"stage": str, "rating": str|None, "started_at": str, "last_msg_id": str|None}

def create_feedback_tables():
    sql = """
    CREATE TABLE IF NOT EXISTS user_feedback (
        feedback_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        message_id TEXT,
        rating TEXT,
        comments TEXT,
        created_at TEXT NOT NULL
    );
    """
    execute_d1_query(sql)
    logger.info("Feedback table ready.")

def save_user_feedback(user_id, message_id, rating, comments=None):
    feedback_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()
    sql = """
    INSERT INTO user_feedback (feedback_id, user_id, message_id, rating, comments, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """
    execute_d1_query(sql, [feedback_id, user_id, message_id, rating, comments, created_at])
    logger.info(f"[FEEDBACK] Saved: {feedback_id} ({rating}, {comments})")

def normalize_emoji(e: str) -> str:
    normalized = unicodedata.normalize('NFKD', e)
    return ''.join([
        c for c in normalized 
        if not unicodedata.category(c).startswith('M')  
        and not unicodedata.name(c, '').endswith('MODIFIER')  
    ]).strip()

def start_feedback_flow(from_number: str):
    """
    Trigger WhatsApp Flow for feedback.
    """
    template_name="feedback_flow_template"
    send_feedback_flow_template(to_number=from_number,template_name=template_name)

def handle_feedback_flow_webhook(user_id: str, message_id: str, flow_payload: dict):
    """
    Called when WhatsApp Flow submission webhook hits.
    flow_payload: {"Leave_a_comment_2ac7f5": "xyz", "Rate_Your_Experience_1caea6": "★★★★★ Excellent"}
    """
    try:
        comment = flow_payload.get("Leave_a_comment_2ac7f5")
        rating = flow_payload.get("Rate_Your_Experience_1caea6")
        
        if comment:
            comment = normalize_emoji(comment)

        save_user_feedback(user_id=user_id, message_id=message_id, rating=rating, comments=comment)

        send_whatsapp_interactive_v2(
            from_number=user_id,
            body="Thanks for your feedback! 🌟",
            buttons=[]
        )
        return True
    except Exception as e:
        logger.error(f"[FEEDBACK] Failed to handle flow submission: {e}", exc_info=True)
        return False

def send_feedback_rating_prompt(user_id: str, display_name: Optional[str] = None, inferred: Optional[str] = None):
    name_bit = f"{display_name.split('(').strip()}, " if display_name else ""
    inferred_bit = "Noted the 👍. " if inferred == "up" else ("Thanks for telling us 👎. " if inferred == "down" else "")
    text = (
        f"{inferred_bit}{name_bit}was this helpful? Pick a quick rating below and help improve future guidance ✨"  # 1–1024 chars
    )
    buttons = [
        {"id": "feedback_up", "title": "👍 Good"},
        {"id": "feedback_down", "title": "👎 Bad"},
        {"id": "feedback_skip", "title": "Skip"},
    ]
    send_whatsapp_interactive_v2(user_id, text, buttons)  # reply buttons payload per WA spec

def send_feedback_comment_prompt(user_id: str, display_name: Optional[str] = None):
    name_bit = f"{display_name.split('(').strip()}, " if display_name else ""
    text = f"{name_bit}want to add a short comment? A few words help a lot—or tap Skip 🙏"
    buttons = [
        {"id": "feedback_skip", "title": "Skip"},
    ]
    send_whatsapp_interactive_v2(user_id, text, buttons)

def complete_text_feedback(user_id: str, message_id: Optional[str]):
    feedback_sessions.pop(user_id, None)
    send_whatsapp(user_id, "Thanks for the feedback! 🌟")

def cancel_text_feedback(user_id: str):
    feedback_sessions.pop(user_id, None)
    send_whatsapp(user_id, "Feedback cancelled—send 👍 or 👎 anytime to try again.")

def complete_text_feedback(user_id: str, message_id: Optional[str]):
    # Clear session and thank
    feedback_sessions.pop(user_id, None)
    send_whatsapp(user_id, "Thanks for the feedback! 🌟")

def cancel_text_feedback(user_id: str):
    feedback_sessions.pop(user_id, None)
    send_whatsapp(user_id, "Feedback cancelled. If needed later, just send 👍 or 👎.")

def start_text_feedback(user_id: str, message_id: Optional[str] = None,
                        inferred_rating: Optional[str] = None, display_name: Optional[str] = None):
    feedback_sessions[user_id] = {
        "stage": "awaiting_rating",
        "rating": inferred_rating,     # hint only
        "started_at": datetime.utcnow().isoformat(),
        "last_msg_id": message_id,
    }
    send_feedback_rating_prompt(user_id, display_name=display_name, inferred=inferred_rating)


def process_text_feedback_step(user_id: str, msg: dict) -> bool:
    sess = feedback_sessions.get(user_id)
    if not sess:
        return False

    msg_type = msg.get("type")
    message_id = msg.get("id")
    sess["last_msg_id"] = message_id

    # Interactive buttons
    if msg_type == "interactive":
        interactive = msg.get("interactive", {}) or {}
        itype = interactive.get("type")
        if itype == "button_reply":
            b = interactive.get("button_reply", {}) or {}
            bid = b.get("id")
            if bid == "feedback_cancel":
                cancel_text_feedback(user_id)
                return True
            if bid == "feedback_skip":
                if sess["stage"] == "awaiting_comment":
                    try:
                        save_user_feedback(user_id, message_id, sess.get("rating") or "unknown", comments=None)
                    except Exception:
                        logger.exception("[FEEDBACK] Save failed")
                    complete_text_feedback(user_id, message_id)
                    return True
                else:
                    cancel_text_feedback(user_id)
                    return True
            if bid in ("feedback_up", "feedback_down"):
                sess["rating"] = "up" if bid == "feedback_up" else "down"
                sess["stage"] = "awaiting_comment"
                send_feedback_comment_prompt(user_id)
                return True
        return True

    # Text messages
    if msg_type == "text":
        text = (msg.get("text", {}) or {}).get("body", "") or ""
        norm = normalize_emoji(text.upper().strip())
        if sess["stage"] == "awaiting_rating":
            if "👍" in norm or "THUMBS UP" in norm or norm in ("UP", "GOOD", "LIKE"):
                sess["rating"] = "up"
                sess["stage"] = "awaiting_comment"
                send_feedback_comment_prompt(user_id)
                return True
            if "👎" in norm or "THUMBS DOWN" in norm or norm in ("DOWN", "BAD", "DISLIKE"):
                sess["rating"] = "down"
                sess["stage"] = "awaiting_comment"
                send_feedback_comment_prompt(user_id)
                return True
            send_feedback_rating_prompt(user_id)  # re-prompt
            return True

        if sess["stage"] == "awaiting_comment":
            comment = text.strip()
            try:
                save_user_feedback(user_id, message_id, sess.get("rating") or "unknown", comments=comment or None)
            except Exception:
                logger.exception("[FEEDBACK] Save failed")
            complete_text_feedback(user_id, message_id)
            return True

        cancel_text_feedback(user_id)
        return True

    # Other message kinds -> re-prompt appropriately
    if sess["stage"] == "awaiting_rating":
        send_feedback_rating_prompt(user_id)
    else:
        send_feedback_comment_prompt(user_id)
    return True
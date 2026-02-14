# app/services/whatsapp/payments.py
from datetime import datetime
import hmac, hashlib, json, logging, requests, time
import uuid
from typing import Optional
from app.config.settings import settings
from app.services.cloudflare.d1_client import execute_d1_query
from app.services.cloudflare.payments_service import update_payment_status, upsert_payment
logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v20.0"

def _wa_headers():
    return {
        "Authorization": f"Bearer {settings.WA_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

def verify_meta_signature(raw_body: bytes, x_hub_signature_256: str) -> bool:
    if not x_hub_signature_256 or not settings.META_APP_SECRET:
        return False
    secret = settings.META_APP_SECRET.encode("utf-8")
    digest = hmac.new(secret, msg=raw_body, digestmod=hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    return hmac.compare_digest(expected, x_hub_signature_256)

def send_upi_intent_payment_message(
    to_e164: str,
    reference_id: str,
    amount_in_paise: int,
    description: str,
    configuration_name_or_id: str,
    items: Optional[list[dict]] = None,
):
    if items is None:
        items = [{
            "retailer_id": reference_id,
            "name": description,
            "amount": {"value": amount_in_paise, "offset": 100},
            "quantity": 1
        }]
    else:
        items = [{
            "retailer_id": item.get("item_code", reference_id),
            "name": item.get("product_name", description),
            "amount": {
                "value": item.get("item_price", amount_in_paise),
                "offset": 100
            },
            "quantity": item.get("quantity", 1),
            "image": item.get("image", None)  
        } for item in items]

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_e164,
        "type": "interactive",
        "interactive": {
            "type": "order_details",
            "body": {"text": description[:1024]},
            "action": {
                "name": "review_and_pay",
                "parameters": {
                    "reference_id": reference_id,
                    "type": "digital-goods",
                    "payment_type": "upi",
                    "currency": "INR",
                    "payment_type": "payment_gateway:razorpay",
                    "payment_configuration": "SprinklerV",
                    "total_amount": {"value": amount_in_paise, "offset": 100},
                    "order": {
                        "status": "pending",
                        "expiration": {
                            "timestamp": int(time.time()) + 600,
                            "description": "Payment link valid for 10 minutes"
                        },
                        "subtotal": {"value": amount_in_paise, "offset": 100},
                        "tax": {"value": 0, "offset": 100},  # Required even if zero
                        "shipping": {"value": 0, "offset": 100},  # Optional but recommended
                        "discount": {"value": 0, "offset": 100},  # Optional but recommended
                        "items": items
                    }
                }
            }
        }
    }


    # Save to DB
    upsert_payment(
        reference_id=reference_id,
        user_id=to_e164.replace("whatsapp:", ""),
        amount_paise=amount_in_paise,
        currency="INR",
        status="pending",
        raw_event=json.dumps({"reason": "order_initiated", "timestamp": datetime.utcnow().isoformat()})
    )

    url = f"{GRAPH_API}/{settings.WA_PHONE_NUMBER_ID}/messages"
    r = requests.post(url, headers=_wa_headers(), json=payload, timeout=30)
    try:
        r.raise_for_status()
        logger.info(f"UPI intent message sent to {to_e164}, ref={reference_id}")
        return r.json()
    except requests.HTTPError:
        logger.error(f"Failed sending payment message: {r.status_code} {r.text}")
        update_payment_status(reference_id, "failed", {"send_error": r.text[:1000]})
        raise

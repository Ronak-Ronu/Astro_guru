import logging
from typing import List
import requests

from app.config.constants import LANG_BUTTONS, PAYMENT_PLANS
from app.config.settings import settings
logger = logging.getLogger(__name__)
def send_whatsapp_interactive(to: str, body: str, buttons: list, footer: str = None):
    url = f"https://graph.facebook.com/v22.0/{settings.WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WA_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    # Ensure valid body
    body = (body or "Please select an option below:")[:1024]

    button_objects = []
    for i, button in enumerate(buttons):
        if isinstance(button, dict):
            bid = str(button.get("id", f"btn_{i}"))
            title = str(button.get("title", f"Button {i+1}"))[:20]
        else:
            bid = f"btn_{i}"
            title = str(button)[:20]
        button_objects.append({
            "type": "reply",
            "reply": {"id": bid, "title": title}
        })

    interactive_obj = {
        "type": "button",
        "body": {"text": body},
        "action": {"buttons": button_objects}
    }
    if footer:
        interactive_obj["footer"] = {"text": footer[:60]} 

    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to.replace("whatsapp:", ""),
        "type": "interactive",
        "interactive": interactive_obj
    }

    try:
        resp = requests.post(url, json=data, headers=headers, timeout=15)
        resp.raise_for_status()
        logger.info(f"Interactive message sent to {to}")
    except requests.HTTPError as e:
        logger.error(f"WhatsApp API interactive send error: {e} | response={getattr(e.response, 'text', '')}")
    except Exception as e:
        logger.error(f"WhatsApp API interactive send error: {e}")

def send_whatsapp_interactive_v2(to: str, body: str, buttons: list, footer: str = None):
    url = f"https://graph.facebook.com/v22.0/{settings.WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WA_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    button_objects = []
    for i, button in enumerate(buttons):
        if isinstance(button, dict):
            bid = str(button.get("id", f"btn_{i}"))
            title = str(button.get("title", f"Button {i+1}"))[:20]  # WA UI truncation safety
        else:
            bid = f"btn_{i}"
            title = str(button)[:20]
        button_objects.append({
            "type": "reply",
            "reply": {"id": bid, "title": title}
        })

    interactive_obj = {
        "type": "button",
        "body": {"text": body},
        "action": {"buttons": button_objects}
    }
    if footer:
        interactive_obj["footer"] = {"text": footer[:60]} 

    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to.replace("whatsapp:", ""),
        "type": "interactive",
        "interactive": interactive_obj
    }

    try:
        resp = requests.post(url, json=data, headers=headers, timeout=15)
        resp.raise_for_status()
        logger.info(f"Interactive message sent to {to}")
    except requests.HTTPError as e:
        logger.error(f"WhatsApp API interactive send error: {e} | response={getattr(e.response, 'text', '')}")
    except Exception as e:
        logger.error(f"WhatsApp API interactive send error: {e}")



def send_whatsapp_reaction(to: str, message_id: str, emoji: str):
    url = f"https://graph.facebook.com/v22.0/{settings.WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WA_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to.replace("whatsapp:", ""),
        "type": "reaction",
        "reaction": {
            "message_id": message_id,
            "emoji": emoji
        }
    }
    try:
        resp = requests.post(url, json=data, headers=headers, timeout=15)
        resp.raise_for_status()
        logger.info(f"Reaction sent to {to} for message {message_id}: {emoji}")
    except Exception as e:
        logger.error(f"WhatsApp API reaction send error: {e}")
def send_whatsapp_location_request(to: str, body: str):
    """Send a location request message via WhatsApp Business API"""
    url = f"https://graph.facebook.com/v22.0/{settings.WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WA_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual", 
        "to": to.replace("whatsapp:", ""),
        "type": "interactive",
        "interactive": {
            "type": "location_request_message",
            "body": {
                "text": body
            },
            "action": {
                "name": "send_location"
            }
        }
    }
    
    try:
        resp = requests.post(url, json=data, headers=headers, timeout=15)
        resp.raise_for_status()
        logger.info(f"Location request sent to {to}")
        return True
    except Exception as e:
        logger.error(f"WhatsApp API location request error: {e}")

def send_whatsapp(to: str, body: str):
    url = f"https://graph.facebook.com/v22.0/{settings.WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WA_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to.replace("whatsapp:", ""),
        "type": "text",
        "text": {
            "body": body
        },
    }
    try:
        resp = requests.post(url, json=data, headers=headers, timeout=15)
        resp.raise_for_status()
        logger.info(f"Message sent to {to}: {body}")
    except Exception as e:
        logger.error(f"WhatsApp API send error: {e}")

def send_whatsapp_image(to: str, image_url: str, caption: str = ""):
    url = f"https://graph.facebook.com/v22.0/{settings.WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WA_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to.replace("whatsapp:", ""),
        "type": "image",
        "image": {
            "link": image_url,
            "caption": caption
        }
    }
    try:
        resp = requests.post(url, json=data, headers=headers, timeout=20)
        resp.raise_for_status()
        logger.info(f"Image message sent to {to} with URL: {image_url}")
    except Exception as e:
        logger.error(f"WhatsApp API image send error: {e}")


def mark_message_as_read(phone_number_id: str, message_id: str, access_token: str):
    """
    Marks the given WhatsApp message as read (blue tick) using the Cloud API.
    
    Args:
        phone_number_id (str): Your WhatsApp Business phone number ID.
        message_id (str): The ID of the incoming message to mark read.
        access_token (str): Your WhatsApp Cloud API access token.
    """
    url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        logger.info(f"Marked message {message_id} as read (blue tick).")
    except requests.RequestException as e:
        logger.error(f"Failed to mark message as read: {e}")

def send_typing_indicator(phone_number_id: str, message_id: str, access_token: str):
    url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {
            "type": "text"
        }
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        logger.info(f"Sent typing indicator for message {message_id}")
    except Exception as e:
        logger.error(f"Failed to send typing indicator: {e}")


def send_profile_list_whatsapp(to: str, profiles: List[dict], active_profile_id: str):
    # Add "Exit to Main" option at the top
    rows = [
        {
            "id": "exit_main",
            "title": "🌌 Exit to Main Profile",
            "description": "Return to your primary cosmic profile"
        }
    ]
    
    # Add user profiles
    for p in profiles:
        rows.append({
            "id": p.profile_id,
            "title": p.name,
            "description": f"{p.dob} @ {p.birth_time}{' (Active)' if p.profile_id == active_profile_id else ''}"
        })
    
    sections = [{
        "title": "Your Cosmic Profiles",
        "rows": rows
    }]
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to.replace("whatsapp:", ""),
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "Manage Your Profiles"},
            "body": {"text": "Choose a profile or return to main:"},
            "footer": {"text": "Create new with 'New Profile'"},
            "action": {
                "button": "Switch Profile",
                "sections": sections
            }
        }
    }
    
    url = f"https://graph.facebook.com/v22.0/{settings.WA_PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {settings.WA_ACCESS_TOKEN}"}
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        logger.info(f"Profile list sent to {to}")
    except Exception as e:
        logger.error(f"Failed to send profile list: {e}")

def send_feedback_request_prompt(user_id: str, custom_text: str = None):
    text = custom_text or "How was your experience? Please rate below:"
    buttons = [
        {"id": "feedback_up", "title": "👍 Thumbs Up"},
        {"id": "feedback_down", "title": "👎 Thumbs Down"}
    ]
    button_objects = []
    for b in buttons:
        button_objects.append({
            "type": "reply",
            "reply": {
                "id": b["id"],
                "title": b["title"]
            }
        })
    url = f"https://graph.facebook.com/v22.0/{settings.WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WA_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": user_id.replace("whatsapp:", ""),
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": text},
            "action": {"buttons": button_objects}
        }
    }
    try:
        resp = requests.post(url, json=data, headers=headers, timeout=15)
        resp.raise_for_status()
        logger.info(f"Feedback interactive prompt sent to {user_id}")
    except Exception as e:
        logger.error(f"Failed to send feedback request: {e}")
pending_payments = {}  # key: user_id (E.164), value: {"reference_id": str, "plan_id": str, "amount": int}


def send_payment_invoice(to: str, order_details: dict) -> bool:
    """Send widely-supported interactive buttons invoice with 'paid <ref>' flow"""
    try:
        order_amount = order_details["amount"]
        reference_id = order_details["reference_id"]
        plan_id = order_details["plan_id"]
        to_clean = to.replace("whatsapp:", "")

        # Remember for webhook simulate step
        pending_payments[to_clean] = {
            "reference_id": reference_id,
            "plan_id": plan_id,
            "amount": order_amount,
        }

        # Body: show amount, plan, and instruction to reply "paid <reference_id>"
        plan_desc = PAYMENT_PLANS[plan_id]["description"]
        body_text = (
            f"🔮 Cosmic Wisdom Access\n\n"
            f"Plan: {plan_desc}\n"
            f"Amount: ₹{order_amount}\n"
            f"Ref: {reference_id}\n\n"
            f"How to complete:\n"
            f"1) Pay via your usual method (UPI/QR/etc.)\n"
            f"2) Reply here: paid {reference_id}\n\n"
            f"I'll activate immediately once you reply."
        )

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_clean,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "footer": {"text": "Reply: paid <reference_id>"},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {"id": "copy_ref", "title": "Copy Ref"},
                        },
                        {
                            "type": "reply",
                            "reply": {"id": "cancel_payment", "title": "Cancel"},
                        },
                    ]
                },
            },
        }

        url = f"https://graph.facebook.com/v22.0/{settings.WA_PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {settings.WA_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        logger.info(f"Payment prompt sent to {to_clean} for {plan_id} ({reference_id})")
        return True

    except Exception as e:
        logger.error(f"Failed to send payment prompt: {e}")
        return False



def send_whatsapp_payment_request(to: str, amount: str, currency: str = "INR", reference_id: str = None):
    """Send WhatsApp payment request using UPI intent"""
    url = f"https://graph.facebook.com/v22.0/{settings.WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WA_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    if reference_id is None:
        import time
        reference_id = f"ORDER-{int(time.time())}"

    payload = {
        "messaging_product": "whatsapp",
        "to": to.replace("whatsapp:", ""),
        "type": "interactive",
        "interactive": {
            "type": "payment",
            "payment": {
                "payment_config": settings.WA_PAYMENT_CONFIGURATION,
                "type": "upi_intent",
                "amount": {
                    "currency": currency,
                    "value": amount
                },
                "reference_id": reference_id,
                "expiry": int(time.time()) + 900  # 15 mins validity
            }
        }
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()
def send_language_selector(to: str, prompt_text: str = None):
    body = prompt_text or "Please choose your preferred language:"
    send_whatsapp_interactive(to, body, LANG_BUTTONS)

def send_feedback_flow_template(to_number: str, template_name: str, language="en_US"):
    url = f"https://graph.facebook.com/v22.0/{settings.WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WA_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number.replace("whatsapp:", ""),
        "type": "template",
        "template": {
            "name": template_name,                # must match approved template name exactly
            "language": {"code": language},       # must match an approved locale for the template
            "components": [
                {
                    "type": "button",
                    "sub_type": "flow",
                    "index": "0",
                    "parameters": [
                        {
                            "type": "action",
                            "action": {
                            }
                        }
                    ]
                }
            ]
        }
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        logger.info(f"Feedback flow template sent to {to_number}")
    except requests.HTTPError as e:
        # Log response body to see exact template error code/message
        logger.error(f"Failed to send feedback flow template to {to_number}: {e} | response={getattr(e.response, 'text', '')}")
    except Exception as e:
        logger.error(f"Failed to send feedback flow template to {to_number}: {e}")

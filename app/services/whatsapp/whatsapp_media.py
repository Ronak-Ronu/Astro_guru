import requests

def upload_media_pdf_to_whatsapp(phone_number_id: str, access_token: str, pdf_bytes: bytes, filename: str = "vedic_chart.pdf") -> str:
    url = f"https://graph.facebook.com/v22.0/{phone_number_id}/media"
    files = {
        "file": (filename, pdf_bytes, "application/pdf")
    }
    data = {
        "messaging_product": "whatsapp",
        "type": "application/pdf"
    }
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    resp = requests.post(url, headers=headers, files=files, data=data, timeout=30)
    resp.raise_for_status()
    media_id = resp.json().get("id")
    if not media_id:
        raise RuntimeError(f"WhatsApp PDF upload failed: {resp.text}")
    return media_id

def send_whatsapp_document_by_media_id(to_e164: str, phone_number_id: str, access_token: str, media_id: str, filename: str = "vedic_chart.pdf", caption: str = "") -> None:
    url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_e164.replace("whatsapp:", ""),
        "type": "document",
        "document": {
            "id": media_id,
            "caption": caption,
            "filename": filename
        }
    }
    r = requests.post(url, json=payload, headers=headers, timeout=30)
    r.raise_for_status()

from app.util.natal_chart.chart_svg import render_svg_north_chart
from app.util.natal_chart.core_chart import calc_natal_chart_swe, validate_chart_for_render
from app.util.natal_chart.svg_to_pdf import svg_bytes_to_pdf_bytes
from app.services.whatsapp.whatsapp_media import send_whatsapp_document_by_media_id, upload_media_pdf_to_whatsapp


def send_user_chart_pdf(
    to_e164: str,
    name: str,
    year: int, month: int, day: int, hour: int, minute: int,
    lat: float, lng: float, tz_str: str,
    wa_phone_number_id: str,
    wa_access_token: str,
    caption: str | None = None
) -> None:
    # compute chart, validate 
    chart = calc_natal_chart_swe(name, int(year), int(month), int(day), int(hour), int(minute), float(lat), float(lng), tz_str)
    ok, msg = validate_chart_for_render(chart)
    if not ok:
        raise RuntimeError(f"Chart invalid for rendering: {msg}")

    # 1) SVG
    svg_bytes = render_svg_north_chart(name, chart)

    # 2) Convert to PDF (vector text preserved)
    pdf_bytes = svg_bytes_to_pdf_bytes(svg_bytes, dpi=96)

    # 3) Upload and send as document
    filename = "vedic_chart.pdf"
    media_id = upload_media_pdf_to_whatsapp(wa_phone_number_id, wa_access_token, pdf_bytes, filename=filename)
    cap = caption or f"🌟 {name}'s Vedic Birth Chart (PDF - zoom for clarity) ✨"
    send_whatsapp_document_by_media_id(to_e164, wa_phone_number_id, wa_access_token, media_id, filename=filename, caption=cap)

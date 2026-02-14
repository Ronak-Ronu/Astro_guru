# app/svg_to_pdf.py
import cairosvg

def svg_bytes_to_pdf_bytes(svg_bytes: bytes, dpi: int = 96) -> bytes:
    """
    Convert SVG to PDF using CairoSVG and return PDF bytes.
    dpi influences rasterization of any embedded rasters; vector text remains vector in PDF.
    """
    return cairosvg.svg2pdf(
        bytestring=svg_bytes,
        dpi=dpi,
        background_color="#FFFFFF",
    )

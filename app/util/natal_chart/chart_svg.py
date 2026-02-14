# chart_svg.py - Debug and Fixed Version

import os
import re
import time
import random
import tempfile
import jyotichart as jc
from app.util.natal_chart.core_chart import SIGNS, house_num_for
import logging

logger = logging.getLogger(__name__)

def debug_svg_content(svg_bytes: bytes) -> None:
    """Debug helper to inspect SVG content."""
    try:
        content = svg_bytes.decode("utf-8", errors="replace")
        logger.info(repr(content[:500]))
        lines = content.split('\n')
        for i, line in enumerate(lines[:5], 1):
            logger.info(f"Line {i}: {repr(line)}")
    except Exception as e:
        logger.error(f"Could not debug SVG content: {e}")

def _clean_svg_for_pdf(svg_bytes: bytes) -> bytes:
    """Clean up SVG for PDF conversion while preserving text integrity."""
    try:
        debug_svg_content(svg_bytes)
        
        # Detect encoding and decode properly
        if svg_bytes.startswith(b'\xff\xfe'):
            # UTF-16 little-endian
            content = svg_bytes.decode('utf-16le', errors='replace')
        elif svg_bytes.startswith(b'\xfe\xff'):
            # UTF-16 big-endian
            content = svg_bytes.decode('utf-16be', errors='replace')
        else:
            # Fallback to UTF-8
            content = svg_bytes.decode('utf-8', errors='replace')
        
        # Remove any BOM characters
        content = content.lstrip('\ufeff').strip()
        
        # Remove null bytes that might be present
        content = content.replace('\x00', '')
        
        # Check if it starts with XML declaration, if not add one
        if not content.startswith('<?xml'):
            content = '<?xml version="1.0" encoding="UTF-8"?>\n' + content
        
        # Ensure it has proper SVG opening
        if '<svg' not in content:
            raise ValueError("Not a valid SVG - missing <svg> tag")
        
        # Fix common XML entity issues
        content = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)', '&amp;', content)
        
        # Remove problematic elements
        content = re.sub(r'<clipPath[^>]*>.*?</clipPath>', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'<mask[^>]*>.*?</mask>', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'<filter[^>]*>.*?</filter>', '', content, flags=re.IGNORECASE | re.DOTALL)
        content = re.sub(r'<pattern[^>]*>.*?</pattern>', '', content, flags=re.IGNORECASE | re.DOTALL)
        
        # Add CSS for better text rendering
        css_style = '''
        <style type="text/css">
        <![CDATA[
        text {
            font-family: 'DejaVu Sans', 'Liberation Sans', Arial, sans-serif !important;
            font-size: 16px !important;
            font-weight: bold !important;
            fill: #FFFFFF !important;
            stroke: none !important;
            text-anchor: middle !important;
            dominant-baseline: central !important;
        }
        .planet-text {
            font-size: 14px !important;
            font-weight: bold !important;
        }
        .house-number {
            font-size: 12px !important;
            font-weight: normal !important;
        }
        ]]>
        </style>
        '''
        
        # Insert CSS after the opening <svg> tag
        svg_match = re.search(r'(<svg[^>]*>)', content, re.IGNORECASE)
        if svg_match:
            content = content.replace(svg_match.group(1), svg_match.group(1) + css_style, 1)
        
        # Remove any remaining control characters
        content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', content)
        
        logger.info(f"SVG cleaned successfully: {len(content)} chars")
        return content.encode("utf-8")
        
    except Exception as e:
        logger.error(f"SVG cleanup failed: {e}")
        # Minimal fallback
        try:
            content = svg_bytes.decode("utf-8", errors="replace").strip()
            content = content.replace('\x00', '')
            if not content.startswith('<?xml'):
                content = '<?xml version="1.0" encoding="UTF-8"?>\n' + content
            return content.encode("utf-8")
        except:
            return svg_bytes

def build_placements(chart: dict) -> tuple[str, list[tuple[str, str, int]]]:
    """Build planet placements for the chart."""
    placements = []
    asc_sign = chart.get("Ascendant", {}).get("sign", "Aries")
    
    if asc_sign not in SIGNS:
        asc_sign = "Aries"
    
    # Planets to include in the chart
    planets_to_include = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Rahu", "Ketu"]
    
    # Symbol mapping for display - keep it simple to avoid encoding issues
    sym_map = {
        "Sun": "Su",
        "Moon": "Mo", 
        "Mercury": "Me",
        "Venus": "Ve",
        "Mars": "Ma",
        "Jupiter": "Ju",
        "Saturn": "Sa",
        "Rahu": "Ra",
        "Ketu": "Ke"
    }
    
    for p in planets_to_include:
        pdata = chart.get(p)
        if not isinstance(pdata, dict):
            continue
            
        psign = pdata.get("sign", "Unknown")
        if psign not in SIGNS:
            continue
            
        house = house_num_for(psign, asc_sign)
        sym = sym_map.get(p, p[:2])
        
        # Add retrograde indicator
        if pdata.get("retrograde", False):
            sym += "R"
            
        placements.append((p, sym, house))
    
    logger.info(f"Built {len(placements)} placements for {asc_sign} ascendant")
    return asc_sign, placements

def render_svg_north_chart(person_name: str, chart: dict) -> bytes:
    """Render a North Indian style Vedic chart as SVG bytes."""
    try:
        asc_sign, placements = build_placements(chart)
        
        if len(placements) < 5:
            raise RuntimeError(f"Insufficient placements to render a chart. Got {len(placements)} placements, need at least 5.")
        
        # Create the chart object
        chart_obj = jc.NorthChart("Rasi Chart", person_name)
        chart_obj.set_ascendantsign(asc_sign)
        
        # Add all planets to the chart
        for pname, sym, hnum in placements:
            try:
                chart_obj.add_planet(pname, sym, hnum)
                logger.debug(f"Added {pname} ({sym}) to house {hnum}")
            except Exception as e:
                logger.warning(f"Could not add {pname} ({sym}) to house {hnum}: {e}")
                continue
        
        # Generate unique filename
        base_name = f"chart_{int(time.time()*1000)}_{random.randint(10000,99999)}"
        
        # Render to SVG
        with tempfile.TemporaryDirectory() as tmp:
            try:
                chart_obj.draw(tmp, base_name)
                svg_path = os.path.join(tmp, f"{base_name}.svg")
                
                if not os.path.exists(svg_path):
                    raise RuntimeError(f"Chart SVG file was not created at {svg_path}")
                
                with open(svg_path, "rb") as f:
                    raw_svg = f.read()
                
                if len(raw_svg) < 100:  # Sanity check
                    raise RuntimeError("Generated SVG is too small, likely invalid")
                
                logger.info(f"Raw SVG generated: {len(raw_svg)} bytes")
                
                # Apply gentle cleanup
                cleaned_svg = _clean_svg_for_pdf(raw_svg)
                
                logger.info(f"Cleaned SVG: {len(cleaned_svg)} bytes")
                return cleaned_svg
                
            except Exception as e:
                logger.error(f"Failed to generate chart SVG: {e}")
                raise RuntimeError(f"Failed to generate chart SVG: {e}")
                
    except Exception as e:
        logger.error(f"Chart rendering failed: {e}", exc_info=True)
        raise

def validate_chart_data(chart: dict) -> tuple[bool, str]:
    """Validate chart data before rendering."""
    required_planets = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Ascendant"]
    
    missing = []
    invalid = []
    
    for planet in required_planets:
        if planet not in chart:
            missing.append(planet)
            continue
            
        pdata = chart[planet]
        if not isinstance(pdata, dict):
            invalid.append(f"{planet}: not a dict")
            continue
            
        if pdata.get("sign") not in SIGNS:
            invalid.append(f"{planet}: invalid sign '{pdata.get('sign')}'")
            
        if not isinstance(pdata.get("degree"), (int, float)):
            invalid.append(f"{planet}: invalid degree '{pdata.get('degree')}'")
    
    if missing:
        return False, f"Missing planets: {missing}"
    if invalid:
        return False, f"Invalid data: {invalid}"
    
    return True, "Valid"
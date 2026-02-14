# core_chart.py

import pytz
import swisseph as swe
from datetime import datetime

SIGNS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]

PLANET_IDS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN,
}

def calc_natal_chart_swe(
    name: str,
    year: int, month: int, day: int,
    hour: int, minute: int,
    lat: float, lng: float, tz_str: str
) -> dict:
    local_tz = pytz.timezone(tz_str)
    dt_local = local_tz.localize(datetime(year, month, day, hour, minute))
    dt_utc = dt_local.astimezone(pytz.UTC)

    jd = swe.julday(
        dt_utc.year,
        dt_utc.month,
        dt_utc.day,
        dt_utc.hour + dt_utc.minute/60.0 + dt_utc.second/3600.0,
        swe.GREG_CAL,
    )

    chart = {}

    # Classical planets
    for pname, pid in PLANET_IDS.items():
        res, _flag = swe.calc_ut(jd, pid, swe.FLG_SWIEPH | swe.FLG_SPEED)
        # res: [lon, lat, dist, speed_lon, ...]
        lon = float(res[0]) % 360.0
        spd = float(res[3])
        sign_idx = int(lon // 30)
        sign = SIGNS[sign_idx] if 0 <= sign_idx < 12 else "Unknown"
        chart[pname] = {
            "sign": sign,
            "degree": round(lon % 30.0, 2),
            "longitude": round(lon, 2),
            "retrograde": spd < 0.0,
        }

    # Rahu/Ketu (mean node)
    node_res, _nflag = swe.calc_ut(jd, swe.MEAN_NODE, swe.FLG_SWIEPH)
    # node_res is a sequence; index its longitude with 
    rahu_lon = float(node_res[0]) % 360.0
    ketu_lon = (rahu_lon + 180.0) % 360.0
    for node_name, lon_val in [("Rahu", rahu_lon), ("Ketu", ketu_lon)]:
        sidx = int(lon_val // 30)
        sign = SIGNS[sidx] if 0 <= sidx < 12 else "Unknown"
        chart[node_name] = {
            "sign": sign,
            "degree": round(lon_val % 30.0, 2),
            "longitude": round(lon_val, 2),
            "retrograde": True,
        }

    # Ascendant via swe.houses: ascmc is a sequence;  is Asc
    house_cusps, ascmc = swe.houses(jd, lat, lng, b'P')
    asc_lon = float(ascmc[0]) % 360.0
    sidx = int(asc_lon // 30)
    chart["Ascendant"] = {
        "sign": SIGNS[sidx] if 0 <= sidx < 12 else "Unknown",
        "degree": round(asc_lon % 30.0, 2),
        "longitude": round(asc_lon, 2),
        "retrograde": False,
    }

    return chart


def validate_chart_for_render(chart: dict) -> tuple[bool, str]:
    req = ["Sun","Moon","Mercury","Venus","Mars","Jupiter","Saturn","Ascendant","Rahu","Ketu"]
    missing = [p for p in req if p not in chart]
    if missing:
        return False, f"Missing placements: {missing}"

    unknowns = [p for p,v in chart.items() if isinstance(v, dict) and v.get("sign") == "Unknown"]
    if len(unknowns) > 4:
        return False, f"Too many Unknown signs: {unknowns}"

    for p, v in chart.items():
        if not isinstance(v, dict):
            continue
        if not isinstance(v.get("degree"), (int, float)):
            return False, f"{p}.degree must be numeric, got {type(v.get('degree'))}"
        if not isinstance(v.get("longitude"), (int, float)):
            return False, f"{p}.longitude must be numeric, got {type(v.get('longitude'))}"
        if "retrograde" in v and not isinstance(v["retrograde"], bool):
            return False, f"{p}.retrograde must be bool, got {type(v['retrograde'])}"

    return True, "OK"

def house_num_for(planet_sign: str, asc_sign: str) -> int:
    try:
        ai = SIGNS.index(asc_sign)
        pi = SIGNS.index(planet_sign)
        return ((pi - ai) % 12) + 1
    except ValueError:
        return 1


import logging
import pytz
import requests
from datetime import datetime
import swisseph as swe
from kerykeion import AstrologicalSubject

from app.config.constants import PLANET_IDS, SIGN_ABBREV_TO_FULL, SIGNS

logger = logging.getLogger(__name__)

# --- Ephemeris: Get daily transits ---
from skyfield.api import load
from datetime import datetime

ts = load.timescale()
planets = load('de421.bsp')

def get_transits_swisseph(lat: float, lng: float, dt_str: str) -> dict:
    dt_obj = datetime.strptime(dt_str, "%Y-%m-%d")
    t = ts.utc(dt_obj.year, dt_obj.month, dt_obj.day, 12)
    observer = planets['earth'].at(t)
    planet_keys = {
        "Sun": "sun",
        "Moon": "moon",
        "Mercury": "mercury",
        "Venus": "venus",
        "Mars": "mars",
        "Jupiter": "jupiter barycenter",
        "Saturn": "saturn barycenter",
    }
    SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
             "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
    results = {}
    for name, key in planet_keys.items():
        planet = planets[key]
        astrometric = observer.observe(planet).ecliptic_latlon()
        lon = astrometric[1].degrees % 360
        sign_idx = int(lon // 30)
        sign_name = SIGNS[sign_idx]
        degree = round(lon % 30, 1)
        results[name] = {"sign": sign_name, "degree": degree}
        logger.info(f"Transit {name}: {sign_name} {degree}°")
    return results



def calculate_natal_chart_nasa_horizons(birth_datetime, lat, lng, tz_str):
    """
    Calculate natal chart using NASA HORIZONS API with proper data parsing
    """
    try:
        import pytz
        import re
        
        # Convert to UTC
        local_tz = pytz.timezone(tz_str)
        if birth_datetime.tzinfo is None:
            birth_datetime = local_tz.localize(birth_datetime)
        utc_datetime = birth_datetime.astimezone(pytz.UTC)
        
        # Format for HORIZONS API
        start_time = utc_datetime.strftime('%Y-%m-%d %H:%M')
        stop_time = utc_datetime.strftime('%Y-%m-%d %H:%M')
        
        # NASA HORIZONS planets (NAIF IDs)
        nasa_planets = {
            "Sun": "10",
            "Moon": "301", 
            "Mercury": "199",
            "Venus": "299",
            "Mars": "499",
            "Jupiter": "599",
            "Saturn": "699"
        }
        
        natal_chart = {}
        
        for planet_name, planet_id in nasa_planets.items():
            try:
                # HORIZONS API URL
                url = "https://ssd.jpl.nasa.gov/api/horizons.api"
                params = {
                    'format': 'json',
                    'COMMAND': planet_id,
                    'OBJ_DATA': 'YES',
                    'MAKE_EPHEM': 'YES',
                    'EPHEM_TYPE': 'OBSERVER',
                    'CENTER': 'coord@399',
                    'COORD_TYPE': 'GEODETIC',
                    'SITE_COORD': f'{lng},{lat},0',
                    'START_TIME': start_time,
                    'STOP_TIME': stop_time,
                    'STEP_SIZE': '1d',
                    'QUANTITIES': '31',  # This gives us ecliptic longitude and latitude
                    'REF_SYSTEM': 'ICRF',
                    'CAL_FORMAT': 'CAL',
                    'TIME_DIGITS': 'MINUTES',
                    'ANG_FORMAT': 'DEG',
                    'APPARENT': 'AIRLESS',
                    'RANGE_UNITS': 'AU',
                    'SUPPRESS_RANGE_RATE': 'NO',
                    'SKIP_DAYLT': 'NO',
                    'SOLAR_ELONG': '0,180',
                    'EXTRA_PREC': 'NO',
                    'R_T_S_ONLY': 'NO'
                }
                
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                
                if 'result' in data and data['result']:
                    # Parse the ephemeris data
                    lines = data['result'].split('\n')
                    
                    # Find the data section (between $SOE and $EOE)
                    data_started = False
                    longitude = None
                    
                    for line in lines:
                        if '$SOE' in line:
                            data_started = True
                            continue
                        if '$EOE' in line:
                            break
                            
                        if data_started and line.strip():
                            # Clean up the line and split by whitespace
                            line = line.strip()
                            if not line:
                                continue
                                
                            # The ephemeris data format varies, but typically:
                            # For QUANTITIES=31, we get: Date, Time, EC_LON, EC_LAT, ...
                            # We need to extract the ecliptic longitude (3rd column usually)
                            parts = line.split()
                            
                            if len(parts) >= 4:
                                try:
                                    # Try to find ecliptic longitude
                                    # It's usually in the 3rd or 4th column after date/time
                                    # Look for a number that could be a longitude (0-360)
                                    for i in range(2, min(len(parts), 6)):
                                        try:
                                            potential_lon = float(parts[i])
                                            # Ecliptic longitude should be between 0 and 360
                                            if 0 <= potential_lon <= 360:
                                                longitude = potential_lon
                                                logger.info(f"NASA HORIZONS - {planet_name} raw longitude: {longitude}")
                                                break
                                        except ValueError:
                                            continue
                                    
                                    if longitude is not None:
                                        break
                                        
                                except (ValueError, IndexError) as e:
                                    logger.debug(f"Error parsing line for {planet_name}: {line} - {e}")
                                    continue
                    
                    if longitude is not None:
                        # Convert longitude to zodiac sign and degree
                        longitude = longitude % 360
                        sign_index = int(longitude // 30)
                        
                        if 0 <= sign_index < 12:
                            sign_name = SIGNS[sign_index]
                        else:
                            sign_name = "Unknown"
                            
                        degree = longitude % 30
                        
                        natal_chart[planet_name] = {
                            "sign": sign_name,
                            "degree": round(degree, 2),
                            "longitude": round(longitude, 2),
                            "retrograde": False  # Would need velocity data for this
                        }
                        
                        logger.info(f"NASA HORIZONS - {planet_name}: {sign_name} {degree:.2f}°")
                    else:
                        logger.error(f"Could not extract longitude for {planet_name}")
                        natal_chart[planet_name] = {
                            "sign": "Unknown",
                            "degree": 0.0,
                            "longitude": 0.0,
                            "retrograde": False
                        }
                else:
                    logger.error(f"No result data for {planet_name}")
                    natal_chart[planet_name] = {
                        "sign": "Unknown",
                        "degree": 0.0,
                        "longitude": 0.0,
                        "retrograde": False
                    }
                    
            except Exception as e:
                logger.error(f"NASA HORIZONS failed for {planet_name}: {e}")
                natal_chart[planet_name] = {
                    "sign": "Unknown",
                    "degree": 0.0,
                    "longitude": 0.0,
                    "retrograde": False
                }
        
        # Calculate Ascendant using Swiss Ephemeris (more reliable for houses)
        try:
            import swisseph as swe
            
            jd = swe.julday(
                utc_datetime.year,
                utc_datetime.month,
                utc_datetime.day,
                utc_datetime.hour + utc_datetime.minute/60.0
            )
            
            houses = swe.houses(jd, lat, lng, b'P')  # Placidus houses
            asc_longitude = houses[1][0] % 360
            asc_sign_index = int(asc_longitude // 30)
            asc_degree = asc_longitude % 30
            
            if 0 <= asc_sign_index < 12:
                asc_sign_name = SIGNS[asc_sign_index]
            else:
                asc_sign_name = "Unknown"
            
            natal_chart["Ascendant"] = {
                "sign": asc_sign_name,
                "degree": round(asc_degree, 2),
                "longitude": round(asc_longitude, 2),
                "retrograde": False
            }
            
            logger.info(f"NASA/Swiss - Ascendant: {asc_sign_name} {asc_degree:.2f}°")
            
        except Exception as e:
            logger.error(f"Ascendant calculation failed: {e}")
            natal_chart["Ascendant"] = {
                "sign": "Unknown",
                "degree": 0.0,
                "longitude": 0.0,
                "retrograde": False
            }
        
        # Validate that we got meaningful data
        successful_planets = sum(1 for planet_data in natal_chart.values() 
                               if planet_data.get("sign") != "Unknown")
        
        logger.info(f"NASA HORIZONS: {successful_planets} planets calculated successfully")
        
        return natal_chart
        
    except Exception as e:
        logger.error(f"NASA HORIZONS calculation failed entirely: {e}")
        return None



def get_transits_nasa_horizons(lat: float, lng: float, dt_str: str) -> dict:
    """
    Get current transits using NASA HORIZONS API
    """
    try:
        dt_obj = datetime.strptime(dt_str, "%Y-%m-%d")
        start_time = f"{dt_obj.year}-{dt_obj.month:02d}-{dt_obj.day:02d} 12:00"
        
        nasa_planets = {
            "Sun": "10",
            "Moon": "301",
            "Mercury": "199", 
            "Venus": "299",
            "Mars": "499",
            "Jupiter": "599",
            "Saturn": "699"
        }
        
        results = {}
        
        for planet_name, planet_id in nasa_planets.items():
            try:
                url = "https://ssd.jpl.nasa.gov/api/horizons.api"
                
                params = {
                    'format': 'json',
                    'COMMAND': planet_id,
                    'MAKE_EPHEM': 'YES',
                    'EPHEM_TYPE': 'OBSERVER',
                    'CENTER': 'coord@399',
                    'COORD_TYPE': 'GEODETIC',
                    'SITE_COORD': f'{lng},{lat},0',
                    'START_TIME': start_time,
                    'STOP_TIME': start_time,
                    'STEP_SIZE': '1d',
                    'QUANTITIES': '31',
                    'REF_SYSTEM': 'ICRF',
                    'CAL_FORMAT': 'CAL',
                    'ANG_FORMAT': 'DEG',
                    'APPARENT': 'AIRLESS'
                }
                
                response = requests.get(url, params=params, timeout=20)
                response.raise_for_status()
                
                data = response.json()
                
                if 'result' in data:
                    lines = data['result'].split('\n')
                    
                    data_started = False
                    for line in lines:
                        if '$SOE' in line:
                            data_started = True
                            continue
                        if '$EOE' in line:
                            break
                            
                        if data_started and line.strip():
                            parts = line.split()
                            if len(parts) >= 3:
                                try:
                                    longitude = float(parts[2])
                                    sign_idx = int(longitude // 30)
                                    sign_name = SIGNS[sign_idx]
                                    degree = round(longitude % 30, 1)
                                    
                                    results[planet_name] = {
                                        "sign": sign_name,
                                        "degree": degree,
                                        "longitude": round(longitude, 1)
                                    }
                                    
                                    logger.info(f"NASA Transit {planet_name}: {sign_name} {degree}°")
                                    break
                                    
                                except (ValueError, IndexError):
                                    continue
                
                if planet_name not in results:
                    results[planet_name] = {"sign": "Unknown", "degree": 0.0}
                    
            except Exception as e:
                logger.error(f"NASA transit failed for {planet_name}: {e}")
                results[planet_name] = {"sign": "Unknown", "degree": 0.0}
        
        return results
        
    except Exception as e:
        logger.error(f"NASA transit calculation failed: {e}")
        return {}


def calculate_natal_chart_swiss_ephemeris(birth_datetime: datetime, lat: float, lng: float, tz_str: str) -> dict:
    """Calculate natal chart with Rahu and Ketu for complete Vedic charts"""
    try:
        local_tz = pytz.timezone(tz_str)
        if birth_datetime.tzinfo is None:
            birth_datetime = local_tz.localize(birth_datetime)
        utc_datetime = birth_datetime.astimezone(pytz.UTC)
        logger.info(f"Birth datetime localized and converted to UTC: {utc_datetime}")

        jd = swe.julday(
            utc_datetime.year,
            utc_datetime.month,
            utc_datetime.day,
            utc_datetime.hour + utc_datetime.minute / 60.0 + utc_datetime.second / 3600.0,
            swe.GREG_CAL
        )
        logger.info(f"Julian Day (UT): {jd}")

        natal_chart = {}

        # Calculate traditional planets
        for planet_name, planet_id in PLANET_IDS.items():
            try:
                result, ret_flag = swe.calc_ut(jd, planet_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
                longitude = float(result[0]) % 360
                speed = float(result[3])
                sign_index = int(longitude // 30)
                
                if 0 <= sign_index < 12:
                    sign_name = SIGNS[sign_index]
                else:
                    sign_name = "Unknown"

                degree = longitude % 30
                retrograde = speed < 0
                natal_chart[planet_name] = {
                    "sign": sign_name,
                    "degree": round(degree, 2),
                    "longitude": round(longitude, 2),
                    "retrograde": retrograde
                }
                retro_str = " (R)" if retrograde else ""
                logger.info(f"{planet_name}: {sign_name} {degree:.2f}°{retro_str}")

            except Exception as e:
                logger.error(f"Error calculating planet {planet_name}: {e}")
                natal_chart[planet_name] = {
                    "sign": "Unknown", "degree": 0.0, "longitude": 0.0, "retrograde": False
                }

        # ✨ ADD RAHU AND KETU (Essential for jyotichart)
        try:
            # Calculate Moon's North Node (Rahu)
            result, ret_flag = swe.calc_ut(jd, swe.MEAN_NODE, swe.FLG_SWIEPH)
            rahu_longitude = float(result[0]) % 360
            rahu_sign_index = int(rahu_longitude // 30)
            rahu_sign = SIGNS[rahu_sign_index] if 0 <= rahu_sign_index < 12 else "Unknown"
            rahu_degree = rahu_longitude % 30
            
            # Ketu is always 180 degrees opposite to Rahu
            ketu_longitude = (rahu_longitude + 180) % 360
            ketu_sign_index = int(ketu_longitude // 30)
            ketu_sign = SIGNS[ketu_sign_index] if 0 <= ketu_sign_index < 12 else "Unknown"
            ketu_degree = ketu_longitude % 30
            rahu_long = swe.calc_ut(jd, swe.MEAN_NODE)[0][0]
            rahu_sign_idx = int(rahu_long // 30)
            rahu_sign = SIGNS[rahu_sign_idx]
            natal_chart["Rahu"] = {
                "sign": rahu_sign,
                "degree": round(rahu_long % 30, 2),
                "longitude": round(rahu_long, 2)
            }
            
            ketu_long = (rahu_long + 180) % 360
            ketu_sign_idx = int(ketu_long // 30)
            ketu_sign = SIGNS[ketu_sign_idx]
            natal_chart["Ketu"] = {
                "sign": ketu_sign,
                "degree": round(ketu_long % 30, 2),
                "longitude": round(ketu_long, 2)
            }

            
            natal_chart["Rahu"] = {
                "sign": rahu_sign,
                "degree": round(rahu_degree, 2),
                "longitude": round(rahu_longitude, 2),
                "retrograde": True  # Rahu is always retrograde
            }
            
            natal_chart["Ketu"] = {
                "sign": ketu_sign,
                "degree": round(ketu_degree, 2),
                "longitude": round(ketu_longitude, 2),
                "retrograde": True  # Ketu is always retrograde
            }
            
            logger.info(f"Rahu: {rahu_sign} {rahu_degree:.2f}°")
            logger.info(f"Ketu: {ketu_sign} {ketu_degree:.2f}°")
            
        except Exception as e:
            logger.error(f"Lunar nodes calculation failed: {e}")
            natal_chart["Rahu"] = {"sign": "Unknown", "degree": 0.0, "longitude": 0.0, "retrograde": True}
            natal_chart["Ketu"] = {"sign": "Unknown", "degree": 0.0, "longitude": 0.0, "retrograde": True}

        # Calculate Ascendant
        try:
            house_cusps, ascmc = swe.houses(jd, lat, lng, b'P')  
            asc_longitude = ascmc[0] % 360
            sign_index = int(asc_longitude // 30)
            if 0 <= sign_index < 12:
                asc_sign = SIGNS[sign_index]
            else:
                asc_sign = "Unknown"

            asc_degree = asc_longitude % 30
            natal_chart['Ascendant'] = {
                "sign": asc_sign,
                "degree": round(asc_degree, 2),
                "longitude": round(asc_longitude, 2),
                "retrograde": False
            }
            logger.info(f"Ascendant: {asc_sign} {asc_degree:.2f}°")

        except Exception as e:
            logger.error(f"Ascendant calculation failed: {e}")
            natal_chart['Ascendant'] = {
                "sign": "Unknown", "degree": 0.0, "longitude": 0.0, "retrograde": False
            }

        logger.info(f"Swiss Ephemeris calculation complete with {len(natal_chart)} positions (including Rahu/Ketu)")
        return natal_chart

    except Exception as e:
        logger.error(f"Swiss Ephemeris natal chart calculation failed entirely: {e}")
        return None

def calculate_natal_chart_kerykeion_fallback(name, year, month, day, hour, minute, lat, lng, tz_str):
    """
    Fallback method using Kerykeion library with enhanced error handling
    """
    try:
        logger.info(f"Kerykeion calculation for: {name}, {year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}")
        logger.info(f"Location: {lat}, {lng}, Timezone: {tz_str}")
        
        subj = AstrologicalSubject(
            name=name,
            year=year,
            month=month,
            day=day,
            hour=hour,
            minute=minute,
            lat=lat,
            lng=lng,
            tz_str=tz_str,
            online=False ,
            city=None,
            nation=None  
        )
        
        logger.info("AstrologicalSubject created successfully")
        
        natal_chart = {}
        
        planets = ["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn"]
        
        for planet in planets:
            try:
                planet_data = getattr(subj, planet, None)
                
                if planet_data is None:
                    logger.warning(f"No data returned for {planet}")
                    natal_chart[planet.capitalize()] = {
                        "sign": "Unknown",
                        "degree": 0.0,
                        "house": 1,
                        "retrograde": False
                    }
                    continue
                
                logger.info(f"Raw {planet} data: {planet_data}")
                
                sign = getattr(planet_data, 'sign', '')
                if sign in SIGN_ABBREV_TO_FULL:
                    full_sign = SIGN_ABBREV_TO_FULL[sign]
                elif sign in SIGNS:
                    full_sign = sign
                else:
                    full_sign = "Unknown"
                    logger.warning(f"Unrecognized sign for {planet}: {sign}")
                
                position = getattr(planet_data, 'position', 0.0)
                try:
                    position_float = float(position)
                    if position_float > 30:
                        degree = position_float % 30
                    else:
                        degree = position_float
                except (ValueError, TypeError):
                    degree = 0.0
                    logger.warning(f"Invalid position for {planet}: {position}")
                
                house = getattr(planet_data, 'house', 1)
                try:
                    house_int = int(house.replace('_House', '') if isinstance(house, str) else house)
                    if not 1 <= house_int <= 12:
                        house_int = 1
                except (ValueError, TypeError):
                    house_int = 1
                
                retrograde = getattr(planet_data, 'retrograde', False)
                if not isinstance(retrograde, bool):
                    retrograde = False
                
                natal_chart[planet.capitalize()] = {
                    "sign": full_sign,
                    "degree": round(degree, 2),
                    "house": house_int,
                    "retrograde": retrograde
                }
                
                retro_marker = " (R)" if retrograde else ""
                logger.info(f"Kerykeion - {planet.capitalize()}: {full_sign} {degree:.2f}° House {house_int}{retro_marker}")
                
            except Exception as e:
                logger.error(f"Error processing {planet} with Kerykeion: {e}")
                natal_chart[planet.capitalize()] = {
                    "sign": "Unknown",
                    "degree": 0.0,
                    "house": 1,
                    "retrograde": False
                }
        
        # Handle Ascendant
        try:
            asc_data = getattr(subj, 'first_house', None)
            if asc_data and hasattr(asc_data, 'sign') and hasattr(asc_data, 'position'):
                sign_abbrev = getattr(asc_data, 'sign', '')
                full_asc_sign = SIGN_ABBREV_TO_FULL.get(sign_abbrev, sign_abbrev)
                asc_degree = float(getattr(asc_data, 'position', 0))
                
                natal_chart["Ascendant"] = {
                    "sign": full_asc_sign,
                    "degree": round(asc_degree, 2),
                    "longitude": round(asc_degree, 2),
                    "retrograde": False
                }
                logger.info(f"Kerykeion - Ascendant: {full_asc_sign} {asc_degree:.2f}°")
            else:
                natal_chart["Ascendant"] = {
                    "sign": "Unknown",
                    "degree": 0.0,
                    "longitude": 0.0,
                    "retrograde": False
                }
        except Exception as e:
            logger.error(f"Error processing Ascendant with Kerykeion: {e}")
            natal_chart["Ascendant"] = {
                "sign": "Unknown",
                "degree": 0.0,
                "longitude": 0.0,
                "retrograde": False
            }

        successful_planets = sum(1 for planet_data in natal_chart.values() 
                               if isinstance(planet_data, dict) and planet_data.get("sign") != "Unknown")
        
        logger.info(f"Kerykeion calculation complete: {successful_planets} successful positions")
        
        return natal_chart
        
    except Exception as e:
        logger.error(f"Kerykeion calculation completely failed: {e}")
        return None
    

def calculate_simplified_chart(birth_date):
    """
    Simplified chart calculation based only on birth date
    This is used as a last resort when precise calculations fail
    
    Args:
        birth_date: datetime object with birth date
    
    Returns:
        dict: simplified natal chart with at least Sun sign
    """
    try:
        month = birth_date.month
        day = birth_date.day
        
        logger.info(f"Simplified calculation for: {month:02d}/{day:02d}")
        
        if (month == 3 and day >= 21) or (month == 4 and day <= 19):
            sun_sign = "Aries"
        elif (month == 4 and day >= 20) or (month == 5 and day <= 20):
            sun_sign = "Taurus"
        elif (month == 5 and day >= 21) or (month == 6 and day <= 20):
            sun_sign = "Gemini"
        elif (month == 6 and day >= 21) or (month == 7 and day <= 22):
            sun_sign = "Cancer"
        elif (month == 7 and day >= 23) or (month == 8 and day <= 22):
            sun_sign = "Leo"
        elif (month == 8 and day >= 23) or (month == 9 and day <= 22):
            sun_sign = "Virgo"
        elif (month == 9 and day >= 23) or (month == 10 and day <= 22):
            sun_sign = "Libra"
        elif (month == 10 and day >= 23) or (month == 11 and day <= 21):
            sun_sign = "Scorpio"
        elif (month == 11 and day >= 22) or (month == 12 and day <= 21):
            sun_sign = "Sagittarius"
        elif (month == 12 and day >= 22) or (month == 1 and day <= 19):
            sun_sign = "Capricorn"
        elif (month == 1 and day >= 20) or (month == 2 and day <= 18):
            sun_sign = "Aquarius"
        else:  # Pisces
            sun_sign = "Pisces"
        
        if month in [3, 6, 9, 12]:  # Months where sign changes mid-month
            if day < 21:
                degree = day + 10  # Rough approximation
            else:
                degree = day - 20
        else:
            if day < 20:
                degree = day + 10
            else:
                degree = day - 19
        
        degree = max(0, min(29.99, degree))
        
        logger.info(f"Simplified - Sun: {sun_sign} {degree:.1f}°")
        
        simplified_chart = {
            "Sun": {
                "sign": sun_sign,
                "degree": round(degree, 1),
                "house": 1,  # Default
                "retrograde": False
            },
            "Moon": {
                "sign": "Unknown",
                "degree": 0.0,
                "house": 1,
                "retrograde": False
            },
            "Mercury": {
                "sign": "Unknown",
                "degree": 0.0,
                "house": 1,
                "retrograde": False
            },
            "Venus": {
                "sign": "Unknown",
                "degree": 0.0,
                "house": 1,
                "retrograde": False
            },
            "Mars": {
                "sign": "Unknown",
                "degree": 0.0,
                "house": 1,
                "retrograde": False
            },
            "Jupiter": {
                "sign": "Unknown",
                "degree": 0.0,
                "house": 1,
                "retrograde": False
            },
            "Saturn": {
                "sign": "Unknown",
                "degree": 0.0,
                "house": 1,
                "retrograde": False
            },
            "Ascendant": {
                "sign": "Unknown",
                "degree": 0.0,
                "house": 1,
                "retrograde": False
            }
        }
        
        logger.info("Simplified calculation complete: Sun sign determined")
        
        return simplified_chart
        
    except Exception as e:
        logger.error(f"Even simplified calculation failed: {e}")
        
        return {
            "Sun": {"sign": "Unknown", "degree": 0.0, "house": 1, "retrograde": False},
            "Moon": {"sign": "Unknown", "degree": 0.0, "house": 1, "retrograde": False},
            "Mercury": {"sign": "Unknown", "degree": 0.0, "house": 1, "retrograde": False},
            "Venus": {"sign": "Unknown", "degree": 0.0, "house": 1, "retrograde": False},
            "Mars": {"sign": "Unknown", "degree": 0.0, "house": 1, "retrograde": False},
            "Jupiter": {"sign": "Unknown", "degree": 0.0, "house": 1, "retrograde": False},
            "Saturn": {"sign": "Unknown", "degree": 0.0, "house": 1, "retrograde": False},
            "Ascendant": {"sign": "Unknown", "degree": 0.0, "house": 1, "retrograde": False}
        }

def calculate_natal_chart_multi_method(name, year, month, day, hour, minute, lat, lng, tz_str):
    """
    Multi-method calculation with proper validation and Swiss Ephemeris as primary
    """
    birth_datetime = datetime(year, month, day, hour, minute)
    
    logger.info(f"Starting multi-method calculation for: {name}")
    logger.info(f"Birth: {year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}")
    logger.info(f"Location: {lat}, {lng} ({tz_str})")
    
    logger.info("Attempting Method 1: Swiss Ephemeris...")
    natal_chart = calculate_natal_chart_swiss_ephemeris(birth_datetime, lat, lng, tz_str)
    if natal_chart:
        successful_planets = sum(1 for planet_name, planet_data in natal_chart.items()
                               if planet_name != '_house_cusps' and 
                                  isinstance(planet_data, dict) and 
                                  planet_data.get("sign") != "Unknown")
        
        logger.info(f"Swiss Ephemeris: {successful_planets} planets calculated successfully")
        
        if successful_planets >= 5:
            logger.info("Swiss Ephemeris successful - using as primary method")
            return natal_chart
        else:
            logger.warning(f"Swiss Ephemeris insufficient: only {successful_planets} planets")
    
    logger.info("Attempting Method 2: Kerykeion...")
    natal_chart = calculate_natal_chart_kerykeion_fallback(name, year, month, day, hour, minute, lat, lng, tz_str)
    if natal_chart:
        successful_planets = sum(1 for planet_name, planet_data in natal_chart.items()
                               if isinstance(planet_data, dict) and 
                                  planet_data.get("sign") != "Unknown")
        
        logger.info(f"Kerykeion: {successful_planets} planets calculated successfully")
        
        if successful_planets >= 3:  # At least Sun, Moon, and one other planet
            logger.info("Kerykeion successful - using as backup method")
            return natal_chart
        else:
            logger.warning(f"Kerykeion insufficient: only {successful_planets} planets")
    
    logger.info("Attempting Method 3: Simplified calculation...")
    natal_chart = calculate_simplified_chart(birth_datetime)
    if natal_chart and natal_chart.get("Sun", {}).get("sign") != "Unknown":
        logger.info("Simplified calculation completed - at least Sun sign available")
        return natal_chart
    
    logger.error("All calculation methods failed, returning empty structured chart")
    return {
        "Sun": {"sign": "Unknown", "degree": 0.0, "longitude": 0.0, "retrograde": False},
        "Moon": {"sign": "Unknown", "degree": 0.0, "longitude": 0.0, "retrograde": False},
        "Mercury": {"sign": "Unknown", "degree": 0.0, "longitude": 0.0, "retrograde": False},
        "Venus": {"sign": "Unknown", "degree": 0.0, "longitude": 0.0, "retrograde": False},
        "Mars": {"sign": "Unknown", "degree": 0.0, "longitude": 0.0, "retrograde": False},
        "Jupiter": {"sign": "Unknown", "degree": 0.0, "longitude": 0.0, "retrograde": False},
        "Saturn": {"sign": "Unknown", "degree": 0.0, "longitude": 0.0, "retrograde": False},
        "Ascendant": {"sign": "Unknown", "degree": 0.0, "longitude": 0.0, "retrograde": False}
    }


def validate_natal_chart_data(natal_chart_data: dict) -> tuple[bool, str]:
    """Validate natal chart data structure and quality"""
    if not isinstance(natal_chart_data, dict) or not natal_chart_data:
        return False, "Empty or invalid chart data"
    
    # Check for required planets
    required_planets = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Ascendant"]
    missing_planets = []
    unknown_signs = []
    
    for planet in required_planets:
        if planet not in natal_chart_data:
            missing_planets.append(planet)
        elif natal_chart_data[planet].get("sign") == "Unknown":
            unknown_signs.append(planet)
    
    if len(missing_planets) > 2:
        return False, f"Missing critical planets: {missing_planets}"
    
    if len(unknown_signs) > 4:
        return False, f"Too many unknown signs: {unknown_signs}"
    
    return True, "Chart data is valid"

def calculate_house_number(planet_sign: str, ascendant_sign: str) -> int:
    """Calculate house number based on sign positions relative to ascendant"""
    SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
             "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]
    
    try:
        asc_index = SIGNS.index(ascendant_sign)
        planet_index = SIGNS.index(planet_sign)
        
        # Calculate house number (1-12) based on relative position
        house_number = ((planet_index - asc_index) % 12) + 1
        return house_number
    except ValueError:
        logger.warning(f"Invalid sign in house calculation: planet={planet_sign}, asc={ascendant_sign}")
        return 1  # Default to first house

def get_chart_debug_info(natal_chart_data: dict) -> dict:
    """Get detailed debug information about the chart data"""
    debug_info = {
        "total_planets": len(natal_chart_data),
        "valid_signs": 0,
        "unknown_signs": 0,
        "planets_with_degrees": 0,
        "retrograde_planets": [],
        "planet_details": {}
    }
    
    for planet, data in natal_chart_data.items():
        if isinstance(data, dict):
            sign = data.get("sign", "Unknown")
            degree = data.get("degree", 0)
            retrograde = data.get("retrograde", False)
            
            debug_info["planet_details"][planet] = {
                "sign": sign,
                "degree": degree,
                "retrograde": retrograde
            }
            
            if sign != "Unknown":
                debug_info["valid_signs"] += 1
            else:
                debug_info["unknown_signs"] += 1
                
            if degree > 0:
                debug_info["planets_with_degrees"] += 1
                
            if retrograde:
                debug_info["retrograde_planets"].append(planet)
    
    debug_info["quality_score"] = (debug_info["valid_signs"] / max(1, debug_info["total_planets"])) * 100
    
    return debug_info

def calculate_lunar_nodes(birth_datetime: datetime, lat: float, lng: float, tz_str: str):
    """Calculate Rahu (North Node) and Ketu (South Node) positions"""
    try:
        # Convert to UTC for Swiss Ephemeris
        local_tz = pytz.timezone(tz_str)
        if birth_datetime.tzinfo is None:
            birth_datetime = local_tz.localize(birth_datetime)
        utc_datetime = birth_datetime.astimezone(pytz.UTC)
        
        # Calculate Julian day
        jd = swe.julday(
            utc_datetime.year,
            utc_datetime.month,
            utc_datetime.day,
            utc_datetime.hour + utc_datetime.minute / 60.0 + utc_datetime.second / 3600.0,
            swe.GREG_CAL
        )
        
        # Calculate Moon's North Node (Rahu) - swe.MEAN_NODE
        result, ret_flag = swe.calc_ut(jd, swe.MEAN_NODE, swe.FLG_SWIEPH)
        rahu_longitude = float(result[0]) % 360
        rahu_sign_index = int(rahu_longitude // 30)
        rahu_sign = SIGNS[rahu_sign_index] if 0 <= rahu_sign_index < 12 else "Unknown"
        rahu_degree = rahu_longitude % 30
        
        # Ketu is always 180 degrees opposite to Rahu
        ketu_longitude = (rahu_longitude + 180) % 360
        ketu_sign_index = int(ketu_longitude // 30)
        ketu_sign = SIGNS[ketu_sign_index] if 0 <= ketu_sign_index < 12 else "Unknown"
        ketu_degree = ketu_longitude % 30
        
        logger.info(f"Rahu: {rahu_sign} {rahu_degree:.2f}°")
        logger.info(f"Ketu: {ketu_sign} {ketu_degree:.2f}°")
        
        return {
            "Rahu": {
                "sign": rahu_sign,
                "degree": round(rahu_degree, 2),
                "longitude": round(rahu_longitude, 2),
                "retrograde": True  # Rahu is always retrograde
            },
            "Ketu": {
                "sign": ketu_sign,
                "degree": round(ketu_degree, 2),
                "longitude": round(ketu_longitude, 2),
                "retrograde": True  # Ketu is always retrograde
            }
        }
        
    except Exception as e:
        logger.error(f"Lunar nodes calculation failed: {e}")
        return {
            "Rahu": {"sign": "Unknown", "degree": 0.0, "longitude": 0.0, "retrograde": True},
            "Ketu": {"sign": "Unknown", "degree": 0.0, "longitude": 0.0, "retrograde": True}
        }

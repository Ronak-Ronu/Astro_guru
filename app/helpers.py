
from datetime import date, datetime, timedelta

from app.config.constants import CITY_COORDINATES



def parse_date_flexible(date_str: str) -> datetime:
    date_str = date_str.strip().lower()
    
    if date_str in ['unknown', 'not known', 'dont know', "don't know", 'na', 'n/a']:
        raise ValueError("Date unknown - using fallback") 

    formats_with_year = [
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %m %Y",
        "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%y", "%d-%m-%y"
    ]
    formats_without_year = [
        "%d/%m", "%d-%m", "%d.%m", "%d %m", "%m/%d", "%m-%d"
    ]

    for fmt in formats_with_year:
        try:
            parsed = datetime.strptime(date_str, fmt)
            if parsed.year < 100:
                parsed = parsed.replace(year=parsed.year + (2000 if parsed.year <= 30 else 1900))
            return parsed
        except ValueError:
            continue

    default_year = datetime.now().year - 30  
    for fmt in formats_without_year:
        try:
            partial = datetime.strptime(date_str, fmt)
            return partial.replace(year=default_year)
        except ValueError:
            continue

    raise ValueError(f"Unable to parse date: {date_str}")


def parse_time_flexible(time_str: str):
    """Parse time with multiple formats"""
    if time_str.lower() in ['unknown', 'not known', 'dont know', "don't know", 'na', 'n/a']:
        return 12, 0  # Default to noon
    
    time_str = time_str.strip().replace(' ', '')
    
    # Handle AM/PM format
    if 'am' in time_str.lower() or 'pm' in time_str.lower():
        try:
            is_pm = 'pm' in time_str.lower()
            time_str = time_str.lower().replace('am', '').replace('pm', '')
            
            if ':' in time_str:
                hour, minute = map(int, time_str.split(':'))
            else:
                hour = int(time_str)
                minute = 0
            
            if is_pm and hour != 12:
                hour += 12
            elif not is_pm and hour == 12:
                hour = 0
                
            return hour, minute
        except ValueError:
            pass
    
    # Handle 24-hour format
    formats = [
        "%H:%M",    # HH:MM
        "%H.%M",    # HH.MM
        "%H-%M",    # HH-MM
        "%H %M",    # HH MM
    ]
    
    for fmt in formats:
        try:
            time_obj = datetime.strptime(time_str, fmt).time()
            return time_obj.hour, time_obj.minute
        except ValueError:
            continue
    
    # Try to parse as just hour
    try:
        hour = int(time_str)
        if 0 <= hour <= 23:
            return hour, 0
    except ValueError:
        pass
    
    # Default fallback
    return 12, 0

def parse_date_flexible_safe(val):
    from datetime import datetime
    if isinstance(val, datetime):
        return val
    return parse_date_flexible(str(val))

def parse_time_flexible_safe(val):
    h, m = parse_time_flexible(str(val))
    return int(h), int(m)

def coerce_time_to_hm(time_str):
    h, m = parse_time_flexible(str(time_str))
    return int(h), int(m)


def get_city_info(city_name):
    """Get coordinates and timezone for a city"""
    city_key = city_name.lower().strip()
    if city_key in CITY_COORDINATES:
        return CITY_COORDINATES[city_key]
    # Default to Mumbai if city not found
    return CITY_COORDINATES["mumbai"]
    
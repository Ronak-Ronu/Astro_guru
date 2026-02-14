
from datetime import datetime, timedelta
import json
from app.config.constants import SIGNS
from app.schemas import DateTimeEncoder
from app.services.cloudflare.d1_client import execute_d1_query
import logging
logger = logging.getLogger(__name__)


def create_compatibility_tables():
    """Create compatibility-related tables in D1 if they don't exist."""
    create_compatibility_table_sql = """
    CREATE TABLE IF NOT EXISTS compatibility_sessions (
        session_id TEXT PRIMARY KEY,
        user_id TEXT,
        partner_data TEXT,
        stage TEXT,
        created_at TEXT,
        expires_at TEXT
    );
    """
    
    create_compatibility_results_sql = """
    CREATE TABLE IF NOT EXISTS compatibility_results (
        result_id TEXT PRIMARY KEY,
        user_id TEXT,
        partner_id TEXT,
        compatibility_score INTEGER,
        analysis_data TEXT,
        created_at TEXT
    );
    """
    
    try:
        execute_d1_query(create_compatibility_table_sql)
        execute_d1_query(create_compatibility_results_sql)
        logger.info("Compatibility tables created or already exist in Cloudflare D1.")
    except Exception as e:
        logger.error(f"Failed to create compatibility tables: {e}")


def save_compatibility_session(session_id: str, session_data: dict):
    """Save compatibility session to D1."""
    # Create a copy to avoid modifying original data
    session_data_for_db = session_data.copy()
    
    # Remove non-serializable objects
    if 'partner_birth_date_obj' in session_data_for_db:
        del session_data_for_db['partner_birth_date_obj']
    
    sql = """
    INSERT OR REPLACE INTO compatibility_sessions 
    (session_id, user_id, partner_data, stage, created_at, expires_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """
    
    expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat()
    partner_data_json = json.dumps(session_data_for_db, cls=DateTimeEncoder)
    
    params = [
        session_id,
        session_data_for_db.get('user_id'),
        partner_data_json,
        session_data_for_db.get('stage'),
        datetime.utcnow().isoformat(),
        expires_at
    ]
    
    try:
        execute_d1_query(sql, params)
        logger.info(f"Compatibility session {session_id} saved.")
        return True
    except Exception as e:
        logger.error(f"Error saving compatibility session {session_id}: {e}")
        return False


def get_compatibility_session(session_id: str):
    """Retrieve compatibility session from D1."""
    sql = "SELECT * FROM compatibility_sessions WHERE session_id = ? AND expires_at > ?"
    
    try:
        rows = execute_d1_query(sql, [session_id, datetime.utcnow().isoformat()])
        if rows:
            session_data = json.loads(rows[0]['partner_data'])
            return session_data
        return None
    except Exception as e:
        logger.error(f"Error retrieving compatibility session {session_id}: {e}")
        return None

def delete_compatibility_session(session_id: str):
    """Delete compatibility session from D1."""
    sql = "DELETE FROM compatibility_sessions WHERE session_id = ?"
    
    try:
        execute_d1_query(sql, [session_id])
        logger.info(f"Compatibility session {session_id} deleted.")
        return True
    except Exception as e:
        logger.error(f"Error deleting compatibility session {session_id}: {e}")
        return False

def save_compatibility_result(user_id: str, partner_data: dict, analysis_result: dict):
    """Save compatibility analysis result to D1."""
    sql = """
    INSERT INTO compatibility_results 
    (result_id, user_id, partner_id, compatibility_score, analysis_data, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """
    
    result_id = f"{user_id}_{partner_data.get('name', 'partner')}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    partner_id = f"temp_{partner_data.get('name', 'partner')}"
    
    params = [
        result_id,
        user_id,
        partner_id,
        analysis_result.get('compatibility_score', 0),
        json.dumps(analysis_result),
        datetime.utcnow().isoformat()
    ]
    
    try:
        execute_d1_query(sql, params)
        logger.info(f"Compatibility result {result_id} saved.")
        return True
    except Exception as e:
        logger.error(f"Error saving compatibility result: {e}")
        return False

def calculate_synastry_aspects(user_chart: dict, partner_chart: dict) -> list:
    """
    Calculate synastry aspects between two natal charts
    """
    try:
        aspects = []
        aspect_types = {
            0: {"name": "conjunction", "orb": 8, "nature": "neutral", "strength": "strong"},
            60: {"name": "sextile", "orb": 6, "nature": "harmonious", "strength": "moderate"},
            90: {"name": "square", "orb": 8, "nature": "challenging", "strength": "strong"},
            120: {"name": "trine", "orb": 8, "nature": "harmonious", "strength": "strong"},
            180: {"name": "opposition", "orb": 8, "nature": "challenging", "strength": "strong"}
        }
        
        # Planets to analyze
        planets = ["Sun", "Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn"]
        
        for user_planet in planets:
            if user_planet not in user_chart:
                continue
                
            for partner_planet in planets:
                if partner_planet not in partner_chart:
                    continue
                
                user_data = user_chart[user_planet]
                partner_data = partner_chart[partner_planet]
                
                if user_data.get('sign') == 'Unknown' or partner_data.get('sign') == 'Unknown':
                    continue
                
                # Calculate absolute degrees
                user_sign_idx = SIGNS.index(user_data['sign'])
                partner_sign_idx = SIGNS.index(partner_data['sign'])
                
                user_abs_deg = user_sign_idx * 30 + user_data.get('degree', 0)
                partner_abs_deg = partner_sign_idx * 30 + partner_data.get('degree', 0)
                
                # Calculate the angular difference
                diff = abs(user_abs_deg - partner_abs_deg)
                if diff > 180:
                    diff = 360 - diff
                
                # Check for aspects
                for angle, aspect_info in aspect_types.items():
                    if abs(diff - angle) <= aspect_info["orb"]:
                        aspects.append({
                            "user_planet": user_planet,
                            "partner_planet": partner_planet,
                            "aspect": aspect_info["name"],
                            "angle": angle,
                            "orb": abs(diff - angle),
                            "nature": aspect_info["nature"],
                            "strength": aspect_info["strength"],
                            "description": f"{user_planet} {aspect_info['name']} {partner_planet}"
                        })
                        break
        
        # Sort by strength and nature
        aspects.sort(key=lambda x: (x["strength"] == "strong", x["orb"]))
        
        logger.info(f"Calculated {len(aspects)} synastry aspects")
        return aspects
        
    except Exception as e:
        logger.error(f"Error calculating synastry aspects: {e}")
        return []
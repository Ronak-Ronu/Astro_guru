from datetime import datetime
import json
import uuid
from app.helpers import parse_date_flexible
from app.services.astrology.chart_calculations import calculate_natal_chart_multi_method
from app.services.cloudflare.d1_client import execute_d1_query
import logging

logger = logging.getLogger(__name__)

def create_profiles_table():
    sql = """
    CREATE TABLE IF NOT EXISTS user_profiles (
        profile_id TEXT PRIMARY KEY,
        owner_user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        dob TEXT NOT NULL,
        birth_time TEXT NOT NULL,
        birth_city TEXT NOT NULL,
        lat REAL NOT NULL,
        lng REAL NOT NULL,
        timezone TEXT NOT NULL,
        natal_chart TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    """
    execute_d1_query(sql)

def create_message_counter_table():
    sql = """
    CREATE TABLE IF NOT EXISTS user_message_counters (
        user_id TEXT PRIMARY KEY,
        count INTEGER DEFAULT 0,
        last_reset TEXT
    );
    """
    execute_d1_query(sql)
    logger.info("Message counter table ready.")
def get_user(user_id):
    """Retrieve a user’s data from D1 by WhatsApp number."""
    sql = "SELECT * FROM users WHERE user_id = ?"
    try:
        rows = execute_d1_query(sql, [user_id])
        return rows[0] if rows else None
    except Exception as e:
        logger.error(f"Error retrieving user {user_id}: {e}")
        return None

def insert_user(user_id, name, dob, birth_time, birth_city, lat, lng, timezone, natal_chart):
    sql = """
    INSERT INTO users (user_id, name, dob, birth_time, birth_city, lat, lng, timezone, natal_chart)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    natal_chart_json = json.dumps(natal_chart)
    params = [user_id, name, dob, birth_time, birth_city, lat, lng, timezone, natal_chart_json]
    try:
        execute_d1_query(sql, params)  # Don't assign result
        logger.info(f"User {user_id} inserted successfully.")
        return True
    except Exception as e:
        logger.error(f"Error inserting user {user_id}: {e}")
        return False

def update_user_dob(user_id, new_dob):
    """Update a user’s date of birth and recalculate natal chart."""
    user = get_user(user_id)
    if not user:
        return False
    try:
        birth_date = parse_date_flexible(new_dob)
        natal_chart = calculate_natal_chart_multi_method(
            user["name"],
            birth_date.year,
            birth_date.month,
            birth_date.day,
            int(user["birth_hour"]),
            int(user["birth_minute"]),
            float(user["lat"]),
            float(user["lng"]),
            user["timezone"]
        )
        natal_chart_json = json.dumps(natal_chart)
        sql = "UPDATE users SET dob = ?, natal_chart = ? WHERE user_id = ?"
        params = [new_dob, natal_chart_json, user_id]
        result = execute_d1_query(sql, params)
        logger.info(f"User {user_id} DOB updated.")
        return result["success"]
    except Exception as e:
        logger.error(f"Error updating DOB for user {user_id}: {e}")
        return False

def delete_user(user_id):
    """Delete a user’s data from D1."""
    sql = "DELETE FROM users WHERE user_id = ?"
    try:
        result = execute_d1_query(sql, [user_id])
        logger.info(f"User {user_id} deleted.")
        return result["success"]
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        return False
    
def create_profile(owner_user_id: str, name: str, dob: str, birth_time: str,
                   birth_city: str, lat: float, lng: float, timezone: str, natal_chart: dict) -> str:
    profile_id = str(uuid.uuid4())  
    now = datetime.utcnow().isoformat()
    sql = """
    INSERT INTO user_profiles
    (profile_id, owner_user_id, name, dob, birth_time, birth_city, lat, lng, timezone, natal_chart, is_active, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = [
        profile_id, owner_user_id, name, dob, birth_time, birth_city,
        lat, lng, timezone, json.dumps(natal_chart), 0, now
    ]
    try:
        execute_d1_query(sql, params)
        logger.info(f"Profile created: {profile_id} for {owner_user_id}")
        return profile_id  
    except Exception as e:
        logger.error(f"Error creating profile: {e}")
        return None


def list_profiles(owner_user_id: str):
    """List all profiles for a user with proper error handling"""
    try:
        sql = """
        SELECT profile_id, name, dob, birth_time, birth_city, is_active 
        FROM user_profiles 
        WHERE owner_user_id = ?
        """
        logger.info(f"Executing profile list query for user: {owner_user_id}")
        rows = execute_d1_query(sql, [owner_user_id])
        logger.info(f"Found {len(rows)} profiles for user {owner_user_id}")
        return rows
    except Exception as e:
        logger.error(f"Error listing profiles for user {owner_user_id}: {e}")
        return []

def switch_active_profile(owner_user_id: str, profile_id: str) -> bool:
    # Deactivate all
    execute_d1_query(
        "UPDATE user_profiles SET is_active = 0 WHERE owner_user_id = ?",
        [owner_user_id]
    )
    # Activate selected
    updated = execute_d1_query(
        "UPDATE user_profiles SET is_active = 1 WHERE profile_id = ? AND owner_user_id = ?",
        [profile_id, owner_user_id]
    )
    return updated is not None

def reset_user_message_count(user_id: str):
    execute_d1_query("UPDATE user_message_counters SET count = 0, last_reset = ? WHERE user_id = ?",
                     [datetime.utcnow().isoformat(), user_id])

def deactivate_all_profiles(user_id: str):
    """Deactivate all profiles for a user"""
    execute_d1_query(
        "UPDATE user_profiles SET is_active = 0 WHERE owner_user_id = ?",
        [user_id]
    )
def get_user_language(user_row: dict | None, session_users: dict, user_id: str) -> str:
    if user_row and user_row.get("language"):
        return user_row["language"]
    if session_users.get(user_id, {}).get("language"):
        return session_users[user_id]["language"]
    return "en"

def update_user_language(user_id: str, lang_code: str):
    try:
        sql = "UPDATE users SET language = ? WHERE user_id = ?"
        execute_d1_query(sql, [lang_code, user_id])
        logger.info(f"Updated language for {user_id} -> {lang_code}")
    except Exception as e:
        logger.error(f"Failed to update user language in D1: {e}")


    

from datetime import datetime
import json
import logging
import re
import requests

from app.config.settings import settings
from app.config.constants import SKIP_COMMANDS
from app.helpers import get_city_info, parse_date_flexible, parse_time_flexible
from app.services.astrology.chart_calculations import calculate_natal_chart_multi_method
from app.services.chroma_cloud.chromadbClient import get_relevant_passages, safe_get_relevant_passages
from app.services.cloudflare.synastry_service import calculate_synastry_aspects, delete_compatibility_session, save_compatibility_result, save_compatibility_session
from app.services.cloudflare.users_service import get_user, get_user_language
from app.services.whatsapp.send_messageAndEvents import send_whatsapp_interactive
logger = logging.getLogger(__name__)


compatibility_sessions = {}
users = {}


def handle_compatibility_flow(from_number: str, text: str, user_data: dict) -> str:
    """Handle compatibility analysis flow"""
    session_id = f"compat_{from_number}"

    # Check if user wants to skip/exit
    if text.lower() in SKIP_COMMANDS:
        compatibility_sessions.pop(session_id, None)
        delete_compatibility_session(session_id)
        return "Exited compatibility flow. What would you like to do next?"

    # Check if user is starting compatibility flow
    if text.strip().lower() == "compatibility":
        compatibility_sessions.pop(session_id, None)
        delete_compatibility_session(session_id)
        
        try:
            user_chart = json.loads(user_data["natal_chart"])
        except (KeyError, json.JSONDecodeError) as e:
            logger.error(f"Error parsing user natal chart: {e}")
            return "❌ Unable to access your birth chart data. Please ensure your profile is complete."
        compatibility_sessions[session_id] = {
            'user_id': from_number,
            'stage': 'waiting_partner_name',
            'user_chart': user_chart,
            'user_name': user_data.get("name", "You"),
        }
        
        reply = (
            "*COSMIC COMPATIBILITY ANALYSIS*\n\n"
            "Let's explore the cosmic connection between you and someone special! ✨\n\n"
            "Type 'skip' at any time to exit this flow\n\n"
            f"Your Profile:\n"
            f"👤 {user_data.get('name', 'You')}\n"
            f"☀️ Sun: {user_chart.get('Sun', {}).get('sign', 'Unknown')}\n"
            f"🌙 Moon: {user_chart.get('Moon', {}).get('sign', 'Unknown')}\n\n"
            "📝 First, what's their *name*?"
        )
        
        return reply  # Fallback to returning the message

    # Handle existing session
    session = compatibility_sessions.get(session_id)
    if not session:
        return None  # No active session, return empty

    stage = session.get('stage', '')
    UNKNOWN_COMMANDS = ['unknown', 'not known', 'dont know', "don't know", 'na', 'n/a']

    try:
        if stage == 'waiting_partner_name':
            partner_name = text.strip()
            if not partner_name or len(partner_name) < 1:
                return (
                    "Please enter a valid name for your partner.\n\n"
                    "Type 'skip' to exit this flow."
                )
            
            session['partner_name'] = partner_name
            session['stage'] = 'waiting_partner_dob'
            compatibility_sessions[session_id] = session
            save_compatibility_session(session_id, session)
            dob_prompt = (
                f"✨ Great! We're analyzing compatibility between *{session['user_name']}* and *{partner_name}*.\n\n"
                f"📅 Now, what's {partner_name}'s *birth date*?\n\n"
                f"Please use format: DD/MM/YYYY\n"
                f"Example: 15/08/1990\n\n"
                f"Or select 'Unknown' if not known."
                )
            buttons = ["Skip"]
            send_whatsapp_interactive(f"whatsapp:{from_number}", dob_prompt, buttons)
            return ""  
        elif stage == 'waiting_partner_dob':
            if text.lower() in UNKNOWN_COMMANDS: 
                session['partner_dob_unknown'] = True
                session['partner_dob'] = 'unknown'
                session['stage'] = 'waiting_partner_time'  
                compatibility_sessions[session_id] = session
                save_compatibility_session(session_id, session)
                return (
                    f"✅ Noted: Birth date unknown. We'll use a simplified analysis.\n\n"
                    f"⏰ What's {session['partner_name']}'s *birth time*? (or 'unknown')"
                )
            try:
                partner_birth_date = parse_date_flexible(text)
                session['partner_dob'] = text.strip()
                session['partner_birth_date_obj'] = partner_birth_date
                session['stage'] = 'waiting_partner_time'
                compatibility_sessions[session_id] = session
                save_compatibility_session(session_id, session)
                return (
                    f"✅ Birth date recorded: {partner_birth_date.strftime('%d %B %Y')}\n\n"
                    f"⏰ What's {session['partner_name']}'s *birth time*?\n\n"
                    f"Examples:\n• 2:30 PM\n• 14:30\n• unknown\n\n"
                    f"Type 'skip' at any time to exit this flow"
                )
            except ValueError as e:
                if "unknown" in str(e).lower():  
                    session['partner_dob'] = "unknown"
                    session['partner_birth_date_obj'] = datetime(2000, 1, 1)  
                    session['stage'] = 'waiting_partner_time'
                    compatibility_sessions[session_id] = session
                    save_compatibility_session(session_id, session)
                    return (
                        "✅ Noted - birth date unknown. We'll use general insights (less accurate).\n\n"
                        f"⏰ What's {session['partner_name']}'s *birth time*? (or 'unknown')\n\n"
                        f"Type 'skip' to exit."
                    )
                else:
                    return (
                        f"❌ Please enter a valid date format (year optional):\n\n"
                        f"Examples:\n• 15/08/1990\n• 15/08 (no year)\n• unknown\n\n"
                        f"Type 'skip' to exit."
                    )

        
        elif stage == 'waiting_partner_time':
            try:
                if text.lower() in ['unknown', 'not known', 'dont know', "don't know"]:
                    hour, minute = 12, 0  # Default to noon
                    time_display = "12:00 (noon - default)"
                else:
                    hour, minute = parse_time_flexible(text)
                    time_display = f"{hour:02d}:{minute:02d}"
                
                session['partner_birth_time'] = text.strip()
                session['partner_hour'] = hour
                session['partner_minute'] = minute
                session['stage'] = 'waiting_partner_city'
                compatibility_sessions[session_id] = session
                save_compatibility_session(session_id, session)
                
                return (
                    f"✅ Birth time recorded: {time_display}\n\n"
                    f"🏙️ Finally, which *city* was {session['partner_name']} born in?\n\n"
                    f"Examples:\n"
                    f"• Mumbai\n"
                    f"• Delhi\n"
                    f"• Bangalore\n"
                    f"• Any city name\n\n"
                    f"Type 'skip' at any time to exit this flow"
                )
            except Exception as e:
                logger.error(f"Error parsing time: {e}")
                return (
                    f"❌ Please enter time in a valid format:\n\n"
                    f"Examples:\n"
                    f"• 2:30 PM\n"
                    f"• 14:30\n"
                    f"• unknown\n\n"
                    f"Type 'skip' at any time to exit this flow"
                )
        
        elif stage == 'waiting_partner_city':
            city_name = text.strip()
            if not city_name or len(city_name) < 2:
                return (
                    "Please enter a valid city name.\n\n"
                    "Type 'skip' to exit this flow."
                )
            
            session['partner_birth_city'] = city_name
            
            try:
                city_info = get_city_info(city_name)
                session['partner_lat'] = city_info["lat"]
                session['partner_lng'] = city_info["lng"]
                session['partner_timezone'] = city_info["tz"]
            except Exception as e:
                logger.error(f"Error getting city info for {city_name}: {e}")
                # Use default coordinates (Delhi) as fallback
                session['partner_lat'] = 28.6139
                session['partner_lng'] = 77.2090
                session['partner_timezone'] = "Asia/Kolkata"
            
            session['stage'] = 'complete'
            
            # Calculate partner's natal chart
            try:
                partner_birth_date = session['partner_birth_date_obj']
                partner_natal_chart = calculate_natal_chart_multi_method(
                    session['partner_name'],
                    partner_birth_date.year,
                    partner_birth_date.month,
                    partner_birth_date.day,
                    session.get('partner_hour', 12),
                    session.get('partner_minute', 0),
                    session['partner_lat'],
                    session['partner_lng'],
                    session['partner_timezone']
                )
                
                session['partner_natal_chart'] = partner_natal_chart
                
                # Perform compatibility analysis
                user_chart = session['user_chart']
                
                # Calculate synastry aspects
                try:
                    aspects = calculate_synastry_aspects(user_chart, partner_natal_chart)
                except Exception as e:
                    logger.error(f"Error calculating synastry aspects: {e}")
                    aspects = []
                
                # Get compatibility passages
                user_sun = user_chart.get('Sun', {}).get('sign', 'Unknown')
                user_moon = user_chart.get('Moon', {}).get('sign', 'Unknown')
                partner_sun = partner_natal_chart.get('Sun', {}).get('sign', 'Unknown')
                partner_moon = partner_natal_chart.get('Moon', {}).get('sign', 'Unknown')
                
                compatibility_query = f"compatibility {user_sun} {user_moon} {partner_sun} {partner_moon}"
                
                try:
                    passages = safe_get_relevant_passages(compatibility_query, k=5)
                except Exception as e:
                    logger.error(f"Error getting passages: {e}")
                    passages = []
                
                # Call Cloudflare Worker for compatibility analysis
                payload = {
                    "user_natal_chart": user_chart,
                    "partner_natal_chart": partner_natal_chart,
                    "synastry_aspects": aspects,
                    "passages": passages,
                    "names": [session['user_name'], session['partner_name']],
                    "language": get_user_language(get_user(from_number), users, from_number) if 'get_user_language' in globals() else "english",
                }
                
                headers = {"Authorization": f"Bearer {settings.CF_TOKEN}", "Content-Type": "application/json"}
                
                try:
                    res = requests.post(f"{settings.WORKER_URL}/compatibility", json=payload, headers=headers, timeout=60)
                    res.raise_for_status()
                    compatibility_result = res.json()
                    
                    # Save result
                    try:
                        save_compatibility_result(from_number, session, compatibility_result)
                    except Exception as e:
                        logger.error(f"Error saving compatibility result: {e}")
                    
                    # Clean up session
                    compatibility_sessions.pop(session_id, None)
                    delete_compatibility_session(session_id)
                    
                    # Format and return result
                    score = compatibility_result.get('compatibility_score', 70)
                    strengths = compatibility_result.get('strengths', ['Good cosmic connection'])
                    challenges = compatibility_result.get('challenges', ['Minor differences'])
                    emotional_connection = compatibility_result.get('emotional_connection', 'Positive emotional bond')
                    communication_style = compatibility_result.get('communication_style', 'Good communication potential')
                    long_term_potential = compatibility_result.get('long_term_potential', 'Promising future together')
                    cosmic_advice = compatibility_result.get('cosmic_advice', 'Trust the cosmic flow')
                    relationship_guidance = compatibility_result.get('relationship_guidance', {})
                    best_date_ideas = relationship_guidance.get('best_date_ideas', [])
                    conflict_resolution = relationship_guidance.get('conflict_resolution', '')
                    intimacy_guidance = relationship_guidance.get('intimacy_guidance', '')
                    timing_advice = relationship_guidance.get('timing_advice', '')
                    cosmic_calendar = relationship_guidance.get('cosmic_calendar', {})

                    # Determine compatibility level and emoji
                    if score >= 80:
                        level = "EXCELLENT"
                        level_emoji = "🔥"
                        bar = "████████████ 12/12"
                    elif score >= 70:
                        level = "VERY GOOD"
                        level_emoji = "✨"
                        bar = "██████████░░ 10/12"
                    elif score >= 60:
                        level = "GOOD"
                        level_emoji = "⭐"
                        bar = "████████░░░░ 8/12"
                    elif score >= 50:
                        level = "MODERATE"
                        level_emoji = "🌟"
                        bar = "██████░░░░░░ 6/12"
                    else:
                        level = "CHALLENGING"
                        level_emoji = "🌙"
                        bar = "████░░░░░░░░ 4/12"
                    
                    response = (
                        f"💫 *COSMIC COMPATIBILITY REPORT* 💫\n\n"
                        f"👫 *{session['user_name']} & {session['partner_name']}*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"🎯 *Compatibility Score*: {score}% {level_emoji}\n"
                        f"📊 {bar}\n"
                        f"🏆 *Level*: {level}\n\n"
                        f"✨ *Cosmic Profiles*:\n"
                        f"👤 {session['user_name']}: {user_sun} ☀️ • {user_moon} 🌙\n"
                        f"👤 {session['partner_name']}: {partner_sun} ☀️ • {partner_moon} 🌙\n\n"
                        f"💪 *Relationship Strengths*:\n" +
                        "\n".join([f"• {strength}" for strength in strengths[:3]]) + "\n\n"
                        f"⚠️ *Areas to Navigate*:\n" +
                        "\n".join([f"• {challenge}" for challenge in challenges[:2]]) + "\n\n"
                        f"❤️ *Emotional Bond*: {emotional_connection}\n\n"
                        f"💬 *Communication*: {communication_style}\n\n"
                        f"🌅 *Long-term Potential*: {long_term_potential}\n\n"
                        f"🔮 *Cosmic Guidance*:\n{cosmic_advice}\n\n"
                    )
                    
                    # Add relationship guidance if available
                    if best_date_ideas:
                        response += (
                            f"💑 *Perfect Date Ideas*:\n" +
                            "\n".join([f"• {idea}" for idea in best_date_ideas[:3]]) + "\n\n"
                        )
                    
                    if conflict_resolution:
                        response += f"⚖️ *Conflict Resolution*:\n{conflict_resolution}\n\n"
                        
                    if intimacy_guidance:
                        response += f"💕 *Intimacy Guidance*:\n{intimacy_guidance}\n\n"
                        
                    if timing_advice:
                        response += f"⏳ *Best Timing*:\n{timing_advice}\n\n"
                        
                    # Add cosmic calendar
                    if cosmic_calendar:
                        best_days = cosmic_calendar.get('best_days', 'Not specified')
                        careful_days = cosmic_calendar.get('careful_days', 'Not specified')
                        response += (
                            f"📅 *Cosmic Calendar*:\n"
                            f"• Best Days: {best_days}\n"
                            f"• Careful Days: {careful_days}\n\n"
                        )
                    
                    # Add footer
                    response += (
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🌟 *{len(aspects)} planetary aspects analyzed*\n"
                        f"📅 Analysis Date: {datetime.now().strftime('%d %B %Y')}\n\n"
                        f"💡 *Remember*: Compatibility is about growth, understanding, and cosmic harmony! ✨"
                    )
                    
                    return response
                    
                except requests.RequestException as e:
                    logger.error(f"Compatibility analysis failed: {e}")
                    compatibility_sessions.pop(session_id, None)
                    delete_compatibility_session(session_id)
                    return (
                        f"⚠️ *Cosmic Analysis Temporarily Unavailable*\n\n"
                        f"The stellar calculations encountered some complexity. "
                        f"Based on the birth data:\n\n"
                        f"👫 {session['user_name']} ({user_sun} ☀️) & {session['partner_name']} ({partner_sun} ☀️)\n\n"
                        f"Initial cosmic impression suggests interesting potential! ✨\n\n"
                        f"Try 'compatibility' again later for full analysis."
                    )
                    
            except Exception as e:
                logger.error(f"Partner natal chart calculation failed: {e}")
                compatibility_sessions.pop(session_id, None)
                delete_compatibility_session(session_id)
                return (
                    f"⚠️ *Partner's Cosmic Data Complex*\n\n"
                    f"There was an issue calculating {session['partner_name']}'s natal chart. "
                    f"This might be due to:\n"
                    f"• Rare birth timing\n"
                    f"• Unique celestial configuration\n\n"
                    f"Try 'compatibility' again with different birth details if available! 🌟"
                )
    
    except Exception as e:
        logger.error(f"Error in compatibility flow stage {stage}: {e}")
        compatibility_sessions.pop(session_id, None)
        delete_compatibility_session(session_id)
        return (
            "⚠️ *Unexpected Error*\n\n"
            "Something went wrong during the compatibility analysis. "
            "Please try starting over with 'compatibility'. 🌟"
        )
    
    return ""

def split_message(message, max_length=1800):
    """Split a message into chunks at natural breaks without exceeding max_length"""
    chunks = []
    current_chunk = ""

    paragraphs = message.split("\n\n")
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current_chunk) + len(para) + 2 > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""

            sentences = re.split(r'(?<=[.!?])\s+', para)
            for sentence in sentences:
                if not sentence:
                    continue
                if len(sentence) > max_length:
                    # Split oversized sentence by words
                    words = sentence.split()
                    new_sentence = ""
                    for word in words:
                        if len(new_sentence) + len(word) + 1 > max_length:
                            chunks.append(new_sentence.strip())
                            new_sentence = word + " "
                        else:
                            new_sentence += word + " "
                    if new_sentence.strip():
                        chunks.append(new_sentence.strip())
                else:
                    if len(current_chunk) + len(sentence) + 1 > max_length:
                        chunks.append(current_chunk.strip())
                        current_chunk = sentence + " "
                    else:
                        current_chunk += sentence + " "
        else:
            current_chunk += para + "\n\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks

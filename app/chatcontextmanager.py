import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import requests
import os

logger = logging.getLogger(__name__)

# Configuration
MAX_CONTEXT_MESSAGES = 10  # Keep last 10 messages for context
CONTEXT_RETENTION_DAYS = 30  # Keep context for 30 days
MAX_CONTEXT_LENGTH = 4000  # Max characters for context summary

class ChatContextManager:
    def __init__(self, cf_account_id: str, cf_d1_database_id: str, cf_api_token: str):
        self.cf_account_id = cf_account_id
        self.cf_d1_database_id = cf_d1_database_id
        self.cf_api_token = cf_api_token
        
    def execute_d1_query(self, sql: str, params: List = None):
        """Execute D1 query - reusing your existing function"""
        url = f"https://api.cloudflare.com/client/v4/accounts/{self.cf_account_id}/d1/database/{self.cf_d1_database_id}/query"
        headers = {
            "Authorization": f"Bearer {self.cf_api_token}",
            "Content-Type": "application/json"
        }
        data = {
            "sql": sql,
            "params": params or []
        }
        try:
            response = requests.post(url, json=data, headers=headers, timeout=15)
            response.raise_for_status()
            result = response.json()
            
            if not result["success"]:
                raise Exception(f"Query failed: {result['errors']}")
            
            if "result" in result and result["result"]:
                if "results" in result["result"][0]:
                    return result["result"][0]["results"]
            
            return result["result"] if "result" in result else []
        
        except Exception as e:
            logger.error(f"D1 query error: {e}")
            raise

    def create_chat_context_table(self):
        """Create chat context table in D1"""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS chat_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            message_id TEXT,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            message_text TEXT NOT NULL,
            message_type TEXT DEFAULT 'text',
            metadata TEXT,
            timestamp TEXT NOT NULL,
            session_id TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        """
        
        create_index_sql = """
        CREATE INDEX IF NOT EXISTS idx_chat_contexts_user_timestamp 
        ON chat_contexts(user_id, timestamp DESC);
        """
        
        create_session_index_sql = """
        CREATE INDEX IF NOT EXISTS idx_chat_contexts_session 
        ON chat_contexts(session_id);
        """
        
        try:
            self.execute_d1_query(create_table_sql)
            self.execute_d1_query(create_index_sql)
            self.execute_d1_query(create_session_index_sql)
            logger.info("Chat context table and indexes created successfully")
        except Exception as e:
            logger.error(f"Failed to create chat context table: {e}")
            raise

    def generate_session_id(self, user_id: str) -> str:
        """Generate session ID based on user and current date"""
        date_str = datetime.utcnow().strftime("%Y%m%d")
        return f"session_{user_id}_{date_str}"

    def add_message_to_context(
        self, 
        user_id: str, 
        message_text: str, 
        role: str = "user",
        message_type: str = "text",
        metadata: Dict = None,
        message_id: Optional[str] = None,
        
    ) -> bool:
        try:
            session_id = self.generate_session_id(user_id)
            timestamp = datetime.utcnow().isoformat()
            expires_at = (datetime.utcnow() + timedelta(days=CONTEXT_RETENTION_DAYS)).isoformat()
            
            sql = """
            INSERT INTO chat_contexts 
            (user_id, message_id, role, message_text, message_type, metadata, timestamp, session_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            params = [
                user_id,
                message_id,
                role,
                message_text[:2000],  # Limit message length
                message_type,
                json.dumps(metadata or {}),
                timestamp,
                session_id,
                timestamp,
                expires_at
            ]
            
            self.execute_d1_query(sql, params)
            logger.info(f"Message added to context for user {user_id}")
            
            # Clean up old messages for this user
            self._cleanup_old_messages(user_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to add message to context: {e}")
            return False

    def get_user_context(self, user_id: str, limit: int = MAX_CONTEXT_MESSAGES) -> List[Dict]:
        """Get recent chat context for a user"""
        try:
            sql = """
            SELECT role, message_text, message_type, metadata, timestamp, session_id
            FROM chat_contexts 
            WHERE user_id = ? AND expires_at > ?
            ORDER BY timestamp DESC 
            LIMIT ?
            """
            
            params = [user_id, datetime.utcnow().isoformat(), limit]
            rows = self.execute_d1_query(sql, params)
            
            # Reverse to get chronological order
            context = []
            for row in reversed(rows):
                try:
                    metadata = json.loads(row.get('metadata', '{}'))
                except json.JSONDecodeError:
                    metadata = {}
                
                context.append({
                    'role': row['role'],
                    'content': row['message_text'],
                    'type': row.get('message_type', 'text'),
                    'metadata': metadata,
                    'timestamp': row['timestamp'],
                    'session_id': row.get('session_id')
                })
            
            logger.info(f"Retrieved {len(context)} context messages for user {user_id}")
            return context
            
        except Exception as e:
            logger.error(f"Failed to get user context: {e}")
            return []

    def get_context_summary(self, user_id: str) -> str:
        """Get a summarized context for the user"""
        try:
            context = self.get_user_context(user_id, limit=6)
            if not context:
                return "No previous conversation history."
            
            summary_parts = []
            for msg in context[-6:]:  # Last 6 messages
                role_prefix = "User" if msg['role'] == 'user' else "Assistant"
                content = msg['content'][:200] + "..." if len(msg['content']) > 200 else msg['content']
                summary_parts.append(f"{role_prefix}: {content}")
            
            full_summary = "\n".join(summary_parts)
            
            # Truncate if too long
            if len(full_summary) > MAX_CONTEXT_LENGTH:
                full_summary = full_summary[:MAX_CONTEXT_LENGTH] + "\n[Context truncated...]"
            
            return full_summary
            
        except Exception as e:
            logger.error(f"Failed to get context summary: {e}")
            return "Error retrieving conversation history."

    def clear_user_context(self, user_id: str) -> bool:
        """Clear all context for a user"""
        try:
            sql = "DELETE FROM chat_contexts WHERE user_id = ?"
            self.execute_d1_query(sql, [user_id])
            logger.info(f"Context cleared for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to clear context for user {user_id}: {e}")
            return False

    def _cleanup_old_messages(self, user_id: str):
        """Clean up old messages beyond the limit"""
        try:
            # Keep only the most recent MAX_CONTEXT_MESSAGES
            sql = """
            DELETE FROM chat_contexts 
            WHERE user_id = ? AND id NOT IN (
                SELECT id FROM chat_contexts 
                WHERE user_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            )
            """
            params = [user_id, user_id, MAX_CONTEXT_MESSAGES]
            self.execute_d1_query(sql, params)
            
            # Also clean up expired messages
            sql = "DELETE FROM chat_contexts WHERE expires_at < ?"
            self.execute_d1_query(sql, [datetime.utcnow().isoformat()])
            
        except Exception as e:
            logger.error(f"Failed to cleanup old messages: {e}")

    def get_user_stats(self, user_id: str) -> Dict:
        """Get user conversation statistics"""
        try:
            sql = """
            SELECT 
                COUNT(*) as total_messages,
                COUNT(CASE WHEN role = 'user' THEN 1 END) as user_messages,
                COUNT(CASE WHEN role = 'assistant' THEN 1 END) as assistant_messages,
                MIN(timestamp) as first_message,
                MAX(timestamp) as last_message,
                COUNT(DISTINCT session_id) as total_sessions
            FROM chat_contexts 
            WHERE user_id = ? AND expires_at > ?
            """
            
            params = [user_id, datetime.utcnow().isoformat()]
            rows = self.execute_d1_query(sql, params)
            
            if rows:
                stats = dict(rows[0])
                return {
                    'total_messages': stats.get('total_messages', 0),
                    'user_messages': stats.get('user_messages', 0),
                    'assistant_messages': stats.get('assistant_messages', 0),
                    'first_message': stats.get('first_message'),
                    'last_message': stats.get('last_message'),
                    'total_sessions': stats.get('total_sessions', 0)
                }
            
            return {}
            
        except Exception as e:
            logger.error(f"Failed to get user stats: {e}")
            return {}

def create_contextual_prompt(user_data: Dict, user_message: str, context_manager: ChatContextManager) -> str:
    """Create a contextual prompt including chat history"""
    
    # Get user's astrological profile
    natal_chart = json.loads(user_data.get("natal_chart", "{}"))
    sun_info = natal_chart.get("Sun", {})
    moon_info = natal_chart.get("Moon", {})
    asc_info = natal_chart.get("Ascendant", {})
    
    # Get conversation context
    context_summary = context_manager.get_context_summary(user_data["user_id"])
    
    # Build contextual prompt
    prompt = f"""
You are a warm, empathetic Vedic astrologer speaking with {user_data.get('name', 'a friend')}.

ASTROLOGICAL PROFILE:
- Sun: {sun_info.get('sign', 'Unknown')} at {sun_info.get('degree', 0)}°
- Moon: {moon_info.get('sign', 'Unknown')} at {moon_info.get('degree', 0)}°
- Rising: {asc_info.get('sign', 'Unknown')} at {asc_info.get('degree', 0)}°
- Birth City: {user_data.get('birth_city', 'Unknown')}

RECENT CONVERSATION HISTORY:
{context_summary}

CURRENT MESSAGE: {user_message}

Please respond as their personal astrologer, considering:
1. Their astrological profile
2. Previous conversation context
3. Continuity in guidance and advice
4. Personal and warm tone

Keep response concise (2-3 sentences) and actionable.
"""
    
    return prompt

def enhanced_whatsapp_response(from_number: str, text: str, user_data: Dict, context_manager: ChatContextManager) -> Tuple[str, List[str]]:
    """Enhanced WhatsApp response with context awareness"""
    
    # Add user message to context
    context_manager.add_message_to_context(
        user_id=from_number,
        message_text=text,
        role="user",
        message_type="text",
        metadata={"source": "whatsapp"}
    )
    
    # Get contextual prompt
    contextual_prompt = create_contextual_prompt(user_data, text, context_manager)
    
    # Your existing logic for processing different types of messages
    # (horoscope, compatibility, general chat, etc.)
    
    try:
        # Example: Call your AI service with contextual prompt
        response = call_ai_service_with_context(contextual_prompt)
        
        # Add assistant response to context
        context_manager.add_message_to_context(
            user_id=from_number,
            message_text=response,
            role="assistant",
            message_type="text",
            metadata={"source": "ai_response"}
        )
        
        # Determine appropriate buttons based on context
        buttons = determine_context_buttons(from_number, context_manager)
        
        return response, buttons
        
    except Exception as e:
        logger.error(f"Enhanced response failed: {e}")
        
        # Fallback response
        fallback = "The cosmic energies are shifting. Let me try to help you in another way."
        context_manager.add_message_to_context(
            user_id=from_number,
            message_text=fallback,
            role="assistant",
            message_type="error"
        )
        
        return fallback, ["Try Again", "Daily Horoscope", "Ask Question"]

def determine_context_buttons(user_id: str, context_manager: ChatContextManager) -> List[str]:
    """Determine appropriate buttons based on conversation context"""
    
    try:
        recent_context = context_manager.get_user_context(user_id, limit=3)
        
        # Default buttons
        buttons = ["Daily Horoscope", "Ask Question", "Compatibility"]
        
        # Analyze recent conversation to suggest relevant buttons
        recent_topics = []
        for msg in recent_context:
            content = msg['content'].lower()
            if 'love' in content or 'relationship' in content:
                buttons = ["Love Advice", "Compatibility", "Ask Question"]
            elif 'career' in content or 'job' in content:
                buttons = ["Career Focus", "Ask Question", "Daily Horoscope"]
            elif 'health' in content:
                buttons = ["Health Tips", "Ask Question", "Daily Horoscope"]
            elif 'compatibility' in content:
                buttons = ["Another Compatibility", "Love Advice", "Ask Question"]
        
        return buttons[:3]  # Limit to 3 buttons
        
    except Exception as e:
        logger.error(f"Failed to determine context buttons: {e}")
        return ["Daily Horoscope", "Ask Question", "Compatibility"]

def call_ai_service_with_context(prompt: str) -> str:
    """Call your AI service with contextual prompt"""
    # This would integrate with your existing Worker/AI service
    # Example implementation:
    
    worker_url = os.getenv("WORKER_URL")
    token = os.getenv("CF_TOKEN")
    
    llm_payload = {
        "messages": [
            {"role": "system", "content": "You are a contextual Vedic astrologer."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.8
    }
    
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    try:
        response = requests.post(f"{worker_url}/chat", json=llm_payload, headers=headers, timeout=60)
        response.raise_for_status()
        result = response.json()
        return result.get("response", "I'm here to help with your cosmic journey.")
    except Exception as e:
        logger.error(f"AI service call failed: {e}")
        raise

# Initialize context manager (add this to your main.py)
def initialize_chat_context():
    """Initialize chat context system"""
    context_manager = ChatContextManager(
        cf_account_id=os.getenv("CF_ACCOUNT_ID"),
        cf_d1_database_id=os.getenv("CF_D1_DATABASE_ID"),
        cf_api_token=os.getenv("CF_API_TOKEN")
    )
    
    # Create table on startup
    context_manager.create_chat_context_table()
    
    return context_manager
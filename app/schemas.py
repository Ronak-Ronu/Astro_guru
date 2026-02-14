import json
from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime

from requests_cache import Dict

class HoroscopeRequest(BaseModel):
    name: str
    birth_year: int
    birth_month: int
    birth_day: int
    birth_hour: int
    birth_minute: int
    lat: float
    lng: float
    timezone: str
    date: Optional[str] = None
    language: Optional[str] = "en"


class HoroscopeResponse(BaseModel):
    horoscope: Any
    generation_time_seconds: float

class ChatRequest(BaseModel):
    message: str
    astrology_info: dict = None

class ChatResponse(BaseModel):
    response: str


class ChatMessage(BaseModel):
    id: str
    session_id: str
    user_id: str
    role: str 
    content: str
    timestamp: datetime
    metadata: Optional[Dict[str, Any]] = None

class ConversationalChatRequest(BaseModel):
    session_id: str
    user_id: str
    message: str
    user_chart: Optional[Dict[str, Any]] = None  
    include_context: bool = True

class ConversationalChatResponse(BaseModel):
    response: str
    session_id: str
    message_id: str
    confidence: Optional[float] = None
    cosmic_insight: Optional[str] = None
    suggestions: Optional[List[str]] = None

class DecisionGuidanceRequest(BaseModel):
    session_id: str
    user_id: str
    question: str
    user_chart: Dict[str, Any]
    urgency: Optional[str] = "normal" 

class DecisionGuidanceResponse(BaseModel):
    decision: str  
    confidence: float
    cosmic_reason: str
    best_timing: str
    bonus_tip: str
    moon_phase: str
    response_format: str  


class CompatibilityRequest(BaseModel):
    user_natal_chart: dict
    partner_natal_chart: dict
    passages: str
    names: List[str]

class CompatibilityResponse(BaseModel):
    compatibility_score: int
    strengths: List[str]
    challenges: List[str]
    emotional_connection: str
    communication_style: str
    long_term_potential: str
    cosmic_advice: str

class Profile(BaseModel):
    profile_id: str
    name: str
    dob: str
    birth_time: str
    birth_city: str

class ProfileListRequest(BaseModel):
    user_id: str

class ProfileListResponse(BaseModel):
    profiles: List[Profile]
    active_profile_id: Optional[str]

class SwitchProfileRequest(BaseModel):
    user_id: str
    profile_id: str

class SwitchProfileResponse(BaseModel):
    success: bool
    message: str

# --- Payment Flow Endpoints ---
class StartCheckoutRequest(BaseModel):
    phone: str
    plan: str  # "9" or "49"

class StartCheckoutResponse(BaseModel):
    reference_id: str
    plan_code: str
    amount: int
    message: str

class PaymentWebhookRequest(BaseModel):
    event_type: str
    payload: dict
class SimulatePaymentRequest(BaseModel):
    phone: str
    plan: str  # "9" or "49"
    reference_id: Optional[str] = None

class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)
    

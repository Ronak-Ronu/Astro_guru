from typing import Optional
from pathlib import Path

from pydantic import validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # ==============================================
    # APPLICATION CONFIGURATION
    # ==============================================
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1
    RELOAD: bool = False
    
    # ==============================================
    # CLOUDFLARE WORKER CONFIGURATION
    # ==============================================
    WORKER_URL: str
    CF_TOKEN: str
    
    # ==============================================
    # CLOUDFLARE D1 DATABASE CONFIGURATION
    # ==============================================
    CF_ACCOUNT_ID: str
    CF_D1_DATABASE_ID: str
    CF_API_TOKEN: str
    
    # ==============================================
    # WHATSAPP BUSINESS API CONFIGURATION
    # ==============================================
    WA_ACCESS_TOKEN: str
    WA_PHONE_NUMBER_ID: str
    VERIFY_TOKEN: str
    WA_PAYMENT_CONFIGURATION: str
    META_APP_SECRET: str
    TEST_MODE: bool = False

    
    
    # ==============================================
    # LAGO BILLING CONFIGURATION
    # ==============================================
    LAGO_API_URL: str 
    LAGO_API_KEY: str
    LAGO_PLAN_CODE_DAILY: str 
    LAGO_PLAN_CODE_WEEKLY: str 

    @property
    def PAYMENT_PLANS(self) -> dict:
        return {
            "9": {
                "amount": 9,
                "questions": 2,
                "validity": "24 hours",
                "description": "2 more questions (valid 24 hrs)",
                "plan_code": self.LAGO_PLAN_CODE_DAILY,
                "display_price": "₹9"
            },
            "49": {
                "amount": 49,
                "questions": 20,
                "validity": "7 days", 
                "description": "20 questions for 7 days",
                "plan_code": self.LAGO_PLAN_CODE_WEEKLY,
                "display_price": "₹49"
            }
        }
    
    # Plan Quotas Configuration
    @property
    def PLAN_QUOTAS(self) -> dict:
        return {
            self.LAGO_PLAN_CODE_DAILY: {"questions": 2, "days": 1},
            self.LAGO_PLAN_CODE_WEEKLY: {"questions": 20, "days": 7}
        }
    
    # Heavy Tasks Configuration
    @property
    def HEAVY_TASKS(self) -> set:
        return {
            "daily_horoscope",
            "ask_question", 
            "compatibility",
            "cosmic_guidance",
            "generate_chart",
            "view_kundli",
            "chat",
            "horoscope_request"
        }
    # Free tier configuration
    FREE_TIER_QUESTIONS: int = 3
    MESSAGE_TTL: int = 300  # 5 minutes
    MAX_PROCESSED_MESSAGES: int = 1000
    
    # ==============================================
    # SWISS EPHEMERIS CONFIGURATION
    # ==============================================
    SWEPH_EPHE_PATH: str = "./ephe"
    

    # ==============================================
    # DATABASE CONFIGURATION
    # ==============================================
    USE_CHROMA_CLOUD: bool = True  
    CHROMA_API_KEY: str  
    CHROMA_TENANT: str   
    CHROMA_DATABASE: str  
    CHROMA_COLLECTION_NAME: str
    CHROMA_LOCAL_PATH: str = "./chromadb_data"  
    
    # ==============================================
    # EXTERNAL API CONFIGURATION
    # ==============================================
    NASA_API_KEY: Optional[str] = None
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    
    # ==============================================
    # VALIDATORS
    # ==============================================
    @validator('WORKER_URL')
    def validate_worker_url(cls, v):
        if not v:
            raise ValueError('WORKER_URL is required')
        if not v.startswith(('http://', 'https://')):
            raise ValueError('WORKER_URL must start with http:// or https://')
        return v
    
    @validator('CF_TOKEN')
    def validate_cf_token(cls, v):
        if not v:
            raise ValueError('CF_TOKEN is required')
        if len(v) < 10:
            raise ValueError('CF_TOKEN appears to be invalid (too short)')
        return v
    
    @validator('LAGO_API_KEY')
    def validate_lago_api_key(cls, v):
        if not v:
            raise ValueError('LAGO_API_KEY is required')
        return v
    
    @validator('WA_ACCESS_TOKEN')
    def validate_wa_access_token(cls, v):
        if not v:
            raise ValueError('WA_ACCESS_TOKEN is required')
        if len(v) < 50:
            raise ValueError('WA_ACCESS_TOKEN appears to be invalid')
        return v
    
    @validator('SWEPH_EPHE_PATH')
    def validate_ephe_path(cls, v):
        path = Path(v)
        if not path.exists():
            # Create directory if it doesn't exist
            path.mkdir(parents=True, exist_ok=True)
        return str(path)
    
    @validator('CHROMA_LOCAL_PATH')
    def validate_chromadb_path(cls, v):
        path = Path(v)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        return str(path)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "ignore"

settings = Settings()

def validate_settings():
    required_fields = [
        'WORKER_URL', 'CF_TOKEN', 'CF_ACCOUNT_ID', 'CF_D1_DATABASE_ID',
        'CF_API_TOKEN', 'WA_ACCESS_TOKEN', 'WA_PHONE_NUMBER_ID', 'LAGO_API_KEY'
    ]
    
    missing_fields = []
    for field in required_fields:
        value = getattr(settings, field, None)
        if not value:
            missing_fields.append(field)
    
    if missing_fields:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_fields)}")
    
    return True

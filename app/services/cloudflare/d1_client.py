import logging

import requests

logger = logging.getLogger(__name__)
from app.config.settings import settings

def execute_d1_query(sql, params=None):
    url = f"https://api.cloudflare.com/client/v4/accounts/{settings.CF_ACCOUNT_ID}/d1/database/{settings.CF_D1_DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {settings.CF_API_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "sql": sql,
        "params": params or []
    }
    try:
        response = requests.post(url, json=data, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        if not result["success"]:
            raise Exception(f"Query failed: {result['errors']}")
        
        # For SELECT queries
        if "result" in result and result["result"]:
            if "results" in result["result"][0]:
                return result["result"][0]["results"]
        
        # For write operations (INSERT/UPDATE/DELETE)
        return result["result"] if "result" in result else []
    
    except Exception as e:
        logger.error(f"D1 query error: {e}")
        raise


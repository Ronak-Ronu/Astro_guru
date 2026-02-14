# buttons_nlp_improved.py - FIXES INTENT CLASSIFICATION ISSUES

from typing import List
import logging
from app.util.CTA_buttons_NLP.nlp_helpers import build_default_intent_classifier, extract_keywords_rake

logger = logging.getLogger(__name__)

# Build once at import; for production you can serialize and load a trained model
_INTENT_CLF = None
def get_intent_classifier():
    global _INTENT_CLF
    if _INTENT_CLF is None:
        try:
            _INTENT_CLF = build_default_intent_classifier()
            logger.info("Intent classifier initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize intent classifier: {e}")
            _INTENT_CLF = None
    return _INTENT_CLF

INTENT_TO_BUTTONS = {
    "health": ["Diet Tips", "Ask Question", "View Chart"],
    "love": ["Love Advice", "Compatibility", "Ask Question"],
    "career": ["Career Focus", "Ask Question", "Daily Horoscope"],
    "compatibility": ["Ask Question", "Love Advice", "Profile Switch"],
    "compatibility_check_others": ["Profile Switch", "Check Compatibility", "View Chart"],
    "kundali_check": ["Check Kundali", "Profile Switch", "Ask Question"],
    "future": ["Future Insights", "Daily Horoscope", "Ask Question"],
    "daily": ["Switch Profile", "Ask Question", "Lucky Number"],
    "menu": ["Profile Switch", "Ask Question", "Daily Horoscope"],
    "feedback": ["Give Feedback", "Report Issue", "Ask Question"],
    "finance": ["Investment Outlook", "Money Luck", "Ask Question"],
    "general": ["Profile Switch", "Daily Horoscope", "Ask Question"],
}

KEYWORD_RULES = [
    (["diet","nutrition","eat","food","calorie","weight"], ["Diet Tips"]),
    (["exercise","workout","gym","fitness","yoga"], ["Exercise Plan"]),
    (["stress","mental","anxiety","depress","mind"], ["Mental Wellness"]),
    (["promotion","salary","hike","interview","resume","job","work","career"], ["Career Focus"]),
    (["marriage","breakup","affair","partner","love","girlfriend","single","crush","women","girl"], ["Love Advice"]),
    (["invest","investment","stocks","trading","money","finance","wealth"], ["Investment Outlook"]),
    (["lucky","number","luck"], ["Lucky Number"]),
    (["match","compatibility","zodiac"], ["Another Compatibility"]),
    (["future","prediction","forecast","prospects","predict"], ["Future Insights"]),
    (["switch","change","profile","other profile","different profile"], ["Profile Switch"]),
    (["check","kundali","birth chart","natal chart","kundli","chart"], ["Check Kundali"]),
    (["compatibility","match","relationship","partner","love"], ["Check Compatibility"]),
]

def determine_context_buttons(user_id: str, context_manager, current_text: str) -> List[str]:
    logger.info(f"[BUTTONS] Starting context determination for user {user_id}")
    logger.info(f"[BUTTONS] Current text: '{current_text}'")
    
    try:
        # FIRST: Try to classify based on CURRENT MESSAGE ONLY
        context_keywords = []  
        current_intent = None
        if current_text and current_text.strip():
            current_intent = _classify_current_message(current_text.strip())
            logger.info(f"[BUTTONS] Current message intent: {current_intent}")
            
            # If current message has a strong signal, use it directly
            if current_intent and current_intent != "general":
                buttons_from_current = INTENT_TO_BUTTONS.get(current_intent, [])
                if buttons_from_current:
                    logger.info(f"[BUTTONS] Using current message intent '{current_intent}': {buttons_from_current}")
                    return buttons_from_current[:3]
        
        # SECOND: Get conversation context for additional signals
        recent_context = []
        if context_manager:
            try:
                recent_context = context_manager.get_user_context(user_id, limit=5) or []
                logger.info(f"[BUTTONS] Retrieved {len(recent_context)} context messages")
            except Exception as e:
                logger.warning(f"[BUTTONS] Failed to get context: {e}")
                recent_context = []

        # THIRD: Enhanced analysis with WEIGHTED TEXT (current message gets 3x weight)
        history_texts = []
        if current_text and current_text.strip():
            current_clean = current_text.strip().lower()
            history_texts.extend([current_clean] * 6)  # 3x weight for current message
        
        for msg in recent_context:
            if isinstance(msg, dict) and 'content' in msg:
                content = msg['content']
                if isinstance(content, str) and content.strip():
                    history_texts.append(content.strip().lower())
        
        logger.info(f"[BUTTONS] Weighted analysis: {len(history_texts)} text pieces (current message 3x weighted)")
        
        if not history_texts:
            logger.warning("[BUTTONS] No text available for analysis, using current text heuristics")
            return _get_buttons_from_current_text(current_text or "")
        
        # FOURTH: ML Classification with weighted text
        concat_text = " ".join(history_texts)
        logger.info(f"[BUTTONS] Analyzing weighted text: '{concat_text[:100]}...'")
        
        clf = get_intent_classifier()
        if not clf:
            logger.warning("[BUTTONS] Intent classifier not available, using keyword-based approach")
            return _get_buttons_from_keywords_enhanced(current_text, recent_context)
        
        try:
            intent, probs = clf.predict(concat_text)
            logger.info(f"[BUTTONS] ML predicted intent: '{intent}' with probabilities: {probs}")
            
            # Handle low confidence predictions
            if probs[intent] < 0.2:  # Adjust threshold as needed
                logger.warning(f"[BUTTONS] Low confidence for intent '{intent}', using fallback")
                return _get_buttons_from_keywords_enhanced(current_text, recent_context)
            
        except Exception as e:
            logger.error(f"[BUTTONS] Intent prediction failed: {e}")
            return _get_buttons_from_keywords_enhanced(current_text, recent_context)
        
        base_buttons = INTENT_TO_BUTTONS.get(intent, INTENT_TO_BUTTONS["general"]).copy()
        logger.info(f"[BUTTONS] Base buttons for intent '{intent}': {base_buttons}")
        
        # FIFTH: Apply keyword rules to enhance buttons
        try:
            current_keywords = _extract_current_message_keywords(current_text)
            context_keywords = [
                kw for kw in context_keywords 
                if kw not in current_keywords  # Exclude keywords already in current message
            ]    
            if recent_context:
                context_texts = [msg.get('content', '') for msg in recent_context[:2] if isinstance(msg, dict)]
                if context_texts:
                    context_keywords = extract_keywords_rake(context_texts, max_phrases=3)
            
            logger.info(f"[BUTTONS] Current keywords: {current_keywords}")
            logger.info(f"[BUTTONS] Context keywords: {context_keywords}")
            
            all_keywords = " ".join(current_keywords + context_keywords).lower()
            extra_buttons = []
            
            for keywords, button_adds in KEYWORD_RULES:
                current_matches = [kw for kw in keywords if kw in current_text.lower()]
                context_matches = [kw for kw in keywords if kw in all_keywords and kw not in current_text.lower()]
                
                if current_matches:
                    logger.info(f"[BUTTONS] CURRENT message matched keywords {current_matches} -> adding {button_adds}")
                    for btn in button_adds:
                        if btn not in base_buttons and btn not in extra_buttons:
                            extra_buttons.insert(0, btn)
                elif context_matches:
                    logger.info(f"[BUTTONS] Context matched keywords {context_matches} -> adding {button_adds}")
                    for btn in button_adds:
                        if btn not in base_buttons and btn not in extra_buttons:
                            extra_buttons.append(btn)
            
            all_buttons = extra_buttons + base_buttons
        except Exception as e:
            logger.error(f"[BUTTONS] Keyword enhancement failed: {e}")
            all_buttons = base_buttons
        
        seen = set()
        deduped = []
        for btn in all_buttons:
            if btn not in seen:
                seen.add(btn)
                deduped.append(btn)
        
        final_buttons = deduped[:3]
        if len(final_buttons) < 3:
            fallback = ["Ask Question", "Daily Horoscope", "Compatibility"]
            for fb in fallback:
                if fb not in final_buttons:
                    final_buttons.append(fb)
                if len(final_buttons) >= 3:
                    break
        
        logger.info(f"[BUTTONS] Final buttons: {final_buttons}")
        return final_buttons
        
    except Exception as e:
        logger.error(f"[BUTTONS] Critical error in determine_context_buttons: {e}", exc_info=True)
        return ["Ask Question", "Daily Horoscope", "Compatibility"]
    
def _classify_current_message(text: str) -> str:
    """Classify ONLY the current message to get strong signals"""
    text_lower = text.lower()
    
    # Strong keyword indicators for current message
    career_indicators = ["career", "job", "work", "promotion", "salary", "interview", "professional"]
    love_indicators = ["love", "relationship", "partner", "dating", "romance", "marriage", "girlfriend", "boyfriend", "single", "crush"]  
    health_indicators = ["health", "diet", "nutrition", "exercise", "fitness", "wellness"]
    finance_indicators = ["money", "investment", "finance", "financial", "wealth", "income"]
    daily_indicators = ["horoscope", "daily", "today", "today's"]
    compatibility_indicators = ["compatibility", "compatible", "match"]
    future_indicators = ["future", "prediction", "forecast", "what will", "upcoming"]
    
    # Count matches for each category
    scores = {}
    scores["career"] = sum(1 for word in career_indicators if word in text_lower)
    scores["love"] = sum(1 for word in love_indicators if word in text_lower)  
    scores["health"] = sum(1 for word in health_indicators if word in text_lower)
    scores["finance"] = sum(1 for word in finance_indicators if word in text_lower)
    scores["daily"] = sum(1 for word in daily_indicators if word in text_lower)
    scores["compatibility"] = sum(1 for word in compatibility_indicators if word in text_lower)
    scores["future"] = sum(1 for word in future_indicators if word in text_lower)
    
    # Get the highest scoring category
    if any(score > 0 for score in scores.values()):
        top_intent = max(scores, key=scores.get)
        if scores[top_intent] > 0:
            logger.info(f"[CURRENT] '{text}' -> '{top_intent}' (score: {scores[top_intent]})")
            return top_intent
    
    return "general"

def _extract_current_message_keywords(text: str) -> List[str]:
    """Extract keywords from current message only"""
    if not text:
        return []
    
    try:
        keywords = extract_keywords_rake([text], max_phrases=5)
        return keywords
    except Exception as e:
        logger.warning(f"[KEYWORDS] Extraction failed for current message: {e}")
        # Simple fallback
        words = text.lower().split()
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'my', 'what', 'about'}
        return [w for w in words if w not in stop_words and len(w) > 2]

def _get_buttons_from_current_text(text: str) -> List[str]:
    """Fallback method using simple keyword matching on current text"""
    if not text:
        return ["Ask Question", "Daily Horoscope", "Compatibility"]
        
    text_lower = text.lower()
    logger.info(f"[BUTTONS] Using current text fallback for: '{text_lower}'")
    
    # Strong keyword-based button selection
    if any(kw in text_lower for kw in ["career", "job", "work", "promotion", "professional"]):
        return ["Career Focus", "Ask Question", "Daily Horoscope"]
    elif any(kw in text_lower for kw in ["health", "diet", "nutrition", "exercise", "fitness"]):
        return ["Diet Tips", "Exercise Plan", "Mental Wellness"]
    elif any(kw in text_lower for kw in ["love", "relationship", "partner", "marriage", "dating"]):
        return ["Love Advice", "Compatibility", "Ask Question"]
    elif any(kw in text_lower for kw in ["compatibility", "match", "compatible"]):
        return ["Another Compatibility", "Love Advice", "Ask Question"]
    elif any(kw in text_lower for kw in ["future", "prediction", "forecast", "what will"]):
        return ["Future Insights", "Daily Horoscope", "Ask Question"]
    elif any(kw in text_lower for kw in ["money", "finance", "investment", "financial"]):
        return ["Investment Outlook", "Money Luck", "Ask Question"]
    elif any(kw in text_lower for kw in ["horoscope", "today", "daily"]):
        return ["Daily Horoscope", "Lucky Number", "Ask Question"]
    else:
        return ["Ask Question", "Daily Horoscope", "Compatibility"]

def _get_buttons_from_keywords_enhanced(current_text: str, context_messages: List[dict]) -> List[str]:
    """Enhanced keyword-based button selection when ML fails"""
    logger.info(f"[BUTTONS] Using enhanced keyword fallback")
    
    # Prioritize current message
    current_buttons = _get_buttons_from_current_text(current_text)
    
    # If current message gives us a good result, use it
    if current_buttons[0] != "Ask Question":
        logger.info(f"[BUTTONS] Current message provided specific buttons: {current_buttons}")
        return current_buttons
    
    # Otherwise, look at context but with lower priority
    context_texts = []
    for msg in context_messages[:3]:  # Only recent context
        if isinstance(msg, dict) and 'content' in msg:
            context_texts.append(msg['content'].lower())
    
    combined_context = " ".join(context_texts)
    
    button_scores = {}
    
    # Score buttons based on keyword matches in context
    for keywords, button_adds in KEYWORD_RULES:
        matches = sum(1 for kw in keywords if kw in combined_context)
        if matches > 0:
            for btn in button_adds:
                button_scores[btn] = button_scores.get(btn, 0) + matches
    
    if button_scores:
        # Sort buttons by score
        sorted_buttons = sorted(button_scores.items(), key=lambda x: x[1], reverse=True)
        top_buttons = [btn for btn, score in sorted_buttons[:3]]
        
        # Fill remaining slots
        default_buttons = ["Ask Question", "Daily Horoscope", "Compatibility"]
        for db in default_buttons:
            if db not in top_buttons:
                top_buttons.append(db)
            if len(top_buttons) >= 3:
                break
        
        logger.info(f"[BUTTONS] Context-based buttons: {top_buttons[:3]} (scores: {dict(sorted_buttons)})")
        return top_buttons[:3]
    
    # Final fallback
    return ["Ask Question", "Daily Horoscope", "Compatibility"]
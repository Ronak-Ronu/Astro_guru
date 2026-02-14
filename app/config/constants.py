from datetime import datetime
import json
import re
from typing import Counter
import swisseph as swe
import logging
import os
logger = logging.getLogger(__name__)
from app.config.settings import settings

PLAN_QUOTAS = {
    "daily_9": {"questions": 2, "days": 1},
    "weekly_49": {"questions": 20, "days": 7}
}

LANGUAGES = {
    "English": "en",
    "हिन्दी (Devanagari)": "hi",      
    "Hinglish (Roman)": "hi-en", 
}
LANG_BUTTONS = list(LANGUAGES.keys())
SKIP_COMMANDS = ['skip', 'exit', 'cancel', 'stop', 'back', 'menu', 'main menu']

# --- Sign Mapping ---
SIGN_ABBREV_TO_FULL = {
    'Ari': 'Aries', 'Tau': 'Taurus', 'Gem': 'Gemini', 'Can': 'Cancer', 'Leo': 'Leo', 'Vir': 'Virgo',
    'Lib': 'Libra', 'Sco': 'Scorpio', 'Sag': 'Sagittarius', 'Cap': 'Capricorn', 'Aqu': 'Aquarius', 'Pis': 'Pisces',
    'Aries': 'Aries', 'Taurus': 'Taurus', 'Gemini': 'Gemini', 'Cancer': 'Cancer', 'Leo': 'Leo', 'Virgo': 'Virgo',
    'Libra': 'Libra', 'Scorpio': 'Scorpio', 'Sagittarius': 'Sagittarius', 'Capricorn': 'Capricorn',
    'Aquarius': 'Aquarius', 'Pisces': 'Pisces'
}
SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]
PLANET_IDS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mercury": swe.MERCURY,
    "Venus": swe.VENUS,
    "Mars": swe.MARS,
    "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN
}

# City coordinates database
CITY_COORDINATES = {
    # Major Indian cities
    "mumbai": {"lat": 19.0760, "lng": 72.8777, "tz": "Asia/Kolkata"},
    "delhi": {"lat": 28.7041, "lng": 77.1025, "tz": "Asia/Kolkata"},
    "bangalore": {"lat": 12.9716, "lng": 77.5946, "tz": "Asia/Kolkata"},
    "chennai": {"lat": 13.0827, "lng": 80.2707, "tz": "Asia/Kolkata"},
    "kolkata": {"lat": 22.5726, "lng": 88.3639, "tz": "Asia/Kolkata"},
    "hyderabad": {"lat": 17.3850, "lng": 78.4867, "tz": "Asia/Kolkata"},
    "pune": {"lat": 18.5204, "lng": 73.8567, "tz": "Asia/Kolkata"},
    "ahmedabad": {"lat": 23.0225, "lng": 72.5714, "tz": "Asia/Kolkata"},
    "jaipur": {"lat": 26.9124, "lng": 75.7873, "tz": "Asia/Kolkata"},
    "lucknow": {"lat": 26.8467, "lng": 80.9462, "tz": "Asia/Kolkata"},
    "kanpur": {"lat": 26.4499, "lng": 80.3319, "tz": "Asia/Kolkata"},
    "nagpur": {"lat": 21.1458, "lng": 79.0882, "tz": "Asia/Kolkata"},
    "indore": {"lat": 22.7196, "lng": 75.8577, "tz": "Asia/Kolkata"},
    "thane": {"lat": 19.2183, "lng": 72.9781, "tz": "Asia/Kolkata"},
    "bhopal": {"lat": 23.2599, "lng": 77.4126, "tz": "Asia/Kolkata"},
    "visakhapatnam": {"lat": 17.6868, "lng": 83.2185, "tz": "Asia/Kolkata"},
    "pimpri": {"lat": 18.6298, "lng": 73.7997, "tz": "Asia/Kolkata"},
    "patna": {"lat": 25.5941, "lng": 85.1376, "tz": "Asia/Kolkata"},
    "vadodara": {"lat": 22.3072, "lng": 73.1812, "tz": "Asia/Kolkata"},
    "ludhiana": {"lat": 30.9010, "lng": 75.8573, "tz": "Asia/Kolkata"},
    "agra": {"lat": 27.1767, "lng": 78.0081, "tz": "Asia/Kolkata"},
    "nashik": {"lat": 19.9975, "lng": 73.7898, "tz": "Asia/Kolkata"},
    "faridabad": {"lat": 28.4089, "lng": 77.3178, "tz": "Asia/Kolkata"},
    "meerut": {"lat": 28.9845, "lng": 77.7064, "tz": "Asia/Kolkata"},
    "rajkot": {"lat": 22.3039, "lng": 70.8022, "tz": "Asia/Kolkata"},
    "kalyan": {"lat": 19.2437, "lng": 73.1355, "tz": "Asia/Kolkata"},
    "vasai": {"lat": 19.4882, "lng": 72.8061, "tz": "Asia/Kolkata"},
    "varanasi": {"lat": 25.3176, "lng": 82.9739, "tz": "Asia/Kolkata"},
    "srinagar": {"lat": 34.0837, "lng": 74.7973, "tz": "Asia/Kolkata"},
    "aurangabad": {"lat": 19.8762, "lng": 75.3433, "tz": "Asia/Kolkata"},
    "dhanbad": {"lat": 23.7957, "lng": 86.4304, "tz": "Asia/Kolkata"},
    "amritsar": {"lat": 31.6340, "lng": 74.8723, "tz": "Asia/Kolkata"},
    "navi mumbai": {"lat": 19.0330, "lng": 73.0297, "tz": "Asia/Kolkata"},
    "allahabad": {"lat": 25.4358, "lng": 81.8463, "tz": "Asia/Kolkata"},
    "ranchi": {"lat": 23.3441, "lng": 85.3096, "tz": "Asia/Kolkata"},
    "howrah": {"lat": 22.5958, "lng": 88.2636, "tz": "Asia/Kolkata"},
    "coimbatore": {"lat": 11.0168, "lng": 76.9558, "tz": "Asia/Kolkata"},
    "jabalpur": {"lat": 23.1815, "lng": 79.9864, "tz": "Asia/Kolkata"},
    "gwalior": {"lat": 26.2183, "lng": 78.1828, "tz": "Asia/Kolkata"},
    "vijayawada": {"lat": 16.5062, "lng": 80.6480, "tz": "Asia/Kolkata"},
    "jodhpur": {"lat": 26.2389, "lng": 73.0243, "tz": "Asia/Kolkata"},
    "madurai": {"lat": 9.9252, "lng": 78.1198, "tz": "Asia/Kolkata"},
    "raipur": {"lat": 21.2514, "lng": 81.6296, "tz": "Asia/Kolkata"},
    "kota": {"lat": 25.2138, "lng": 75.8648, "tz": "Asia/Kolkata"},
    "chandigarh": {"lat": 30.7333, "lng": 76.7794, "tz": "Asia/Kolkata"},
    "guwahati": {"lat": 26.1445, "lng": 91.7362, "tz": "Asia/Kolkata"},
    "solapur": {"lat": 17.6599, "lng": 75.9064, "tz": "Asia/Kolkata"},
    "hubli": {"lat": 15.3647, "lng": 75.1240, "tz": "Asia/Kolkata"},
    "bareilly": {"lat": 28.3670, "lng": 79.4304, "tz": "Asia/Kolkata"},
    "moradabad": {"lat": 28.8386, "lng": 78.7733, "tz": "Asia/Kolkata"},
    "mysore": {"lat": 12.2958, "lng": 76.6394, "tz": "Asia/Kolkata"},
    "gurgaon": {"lat": 28.4595, "lng": 77.0266, "tz": "Asia/Kolkata"},
    "aligarh": {"lat": 27.8974, "lng": 78.0880, "tz": "Asia/Kolkata"},
    "jalandhar": {"lat": 31.3260, "lng": 75.5762, "tz": "Asia/Kolkata"},
    "tiruchirappalli": {"lat": 10.7905, "lng": 78.7047, "tz": "Asia/Kolkata"},
    "bhubaneswar": {"lat": 20.2961, "lng": 85.8245, "tz": "Asia/Kolkata"},
    "salem": {"lat": 11.6643, "lng": 78.1460, "tz": "Asia/Kolkata"},
    "warangal": {"lat": 17.9689, "lng": 79.5941, "tz": "Asia/Kolkata"},
    "mira": {"lat": 19.2952, "lng": 72.8527, "tz": "Asia/Kolkata"},
    "thiruvananthapuram": {"lat": 8.5241, "lng": 76.9366, "tz": "Asia/Kolkata"},
    "bhiwandi": {"lat": 19.3002, "lng": 73.0636, "tz": "Asia/Kolkata"},
    "saharanpur": {"lat": 29.9680, "lng": 77.5552, "tz": "Asia/Kolkata"},
    "guntur": {"lat": 16.3067, "lng": 80.4365, "tz": "Asia/Kolkata"},
    "amravati": {"lat": 20.9374, "lng": 77.7796, "tz": "Asia/Kolkata"},
    "bikaner": {"lat": 28.0229, "lng": 73.3119, "tz": "Asia/Kolkata"},
    "noida": {"lat": 28.5355, "lng": 77.3910, "tz": "Asia/Kolkata"},
    "jamshedpur": {"lat": 22.8046, "lng": 86.2029, "tz": "Asia/Kolkata"},
    "bhilai": {"lat": 21.1938, "lng": 81.3509, "tz": "Asia/Kolkata"},
    "cuttack": {"lat": 20.4625, "lng": 85.8828, "tz": "Asia/Kolkata"},
    "firozabad": {"lat": 27.1592, "lng": 78.3957, "tz": "Asia/Kolkata"},
    "kochi": {"lat": 9.9312, "lng": 76.2673, "tz": "Asia/Kolkata"},
    "nellore": {"lat": 14.4426, "lng": 79.9865, "tz": "Asia/Kolkata"},
    "bhavnagar": {"lat": 21.7645, "lng": 72.1519, "tz": "Asia/Kolkata"},
    "dehradun": {"lat": 30.3165, "lng": 78.0322, "tz": "Asia/Kolkata"},
    "durgapur": {"lat": 23.5204, "lng": 87.3119, "tz": "Asia/Kolkata"},
    "asansol": {"lat": 23.6739, "lng": 86.9524, "tz": "Asia/Kolkata"},
    "rourkela": {"lat": 22.2604, "lng": 84.8536, "tz": "Asia/Kolkata"},
    "nanded": {"lat": 19.1383, "lng": 77.3210, "tz": "Asia/Kolkata"},
    "kolhapur": {"lat": 16.7050, "lng": 74.2433, "tz": "Asia/Kolkata"},
    "ajmer": {"lat": 26.4499, "lng": 74.6399, "tz": "Asia/Kolkata"},
    "akola": {"lat": 20.7002, "lng": 77.0082, "tz": "Asia/Kolkata"},
    "gulbarga": {"lat": 17.3297, "lng": 76.8343, "tz": "Asia/Kolkata"},
    "jamnagar": {"lat": 22.4707, "lng": 70.0577, "tz": "Asia/Kolkata"},
    "ujjain": {"lat": 23.1765, "lng": 75.7885, "tz": "Asia/Kolkata"},
    "loni": {"lat": 28.7508, "lng": 77.2902, "tz": "Asia/Kolkata"},
    "siliguri": {"lat": 26.7271, "lng": 88.3953, "tz": "Asia/Kolkata"},
    "jhansi": {"lat": 25.4484, "lng": 78.5685, "tz": "Asia/Kolkata"},
    "ulhasnagar": {"lat": 19.2215, "lng": 73.1645, "tz": "Asia/Kolkata"},
    "jammu": {"lat": 32.7266, "lng": 74.8570, "tz": "Asia/Kolkata"},
    "sangli": {"lat": 16.8524, "lng": 74.5815, "tz": "Asia/Kolkata"},
    "mangalore": {"lat": 12.9141, "lng": 74.8560, "tz": "Asia/Kolkata"},
    "erode": {"lat": 11.3410, "lng": 77.7172, "tz": "Asia/Kolkata"},
    "belgaum": {"lat": 15.8497, "lng": 74.4977, "tz": "Asia/Kolkata"},
    "ambattur": {"lat": 13.1143, "lng": 80.1548, "tz": "Asia/Kolkata"},
    "tirunelveli": {"lat": 8.7139, "lng": 77.7567, "tz": "Asia/Kolkata"},
    "malegaon": {"lat": 20.5579, "lng": 74.5287, "tz": "Asia/Kolkata"},
    "gaya": {"lat": 24.7914, "lng": 85.0002, "tz": "Asia/Kolkata"},
    "jalgaon": {"lat": 21.0077, "lng": 75.5626, "tz": "Asia/Kolkata"},
    "udaipur": {"lat": 24.5854, "lng": 73.7125, "tz": "Asia/Kolkata"},
    "maheshtala": {"lat": 22.4994, "lng": 88.2489, "tz": "Asia/Kolkata"}
}


PROMPTS = {
    "name": {
        "en": "✨ Great! What’s your name? Please type your full name so I can personalize your cosmic insights.",
        "hi": "✨ बहुत बढ़िया! आपका नाम क्या है? कृपया पूरा नाम टाइप करें ताकि मैं आपकी कॉस्मिक जानकारी को व्यक्तिगत बना सकूं।",
        "hi-en": "✨ Bahut badhiya! Aapka naam kya hai? Kripya poora naam type karein taaki main aapki cosmic info personalize kar saku."
    },
    "ask_birth_date": {
        "en": "📅 Please enter your *birth date* in one of these formats: DD/MM/YYYY | DD-MM-YYYY | DD.MM.YYYY\nExample: *15/08/1990*",
        "hi": "📅 कृपया अपनी *जन्मतिथि* इन प्रारूपों में दर्ज करें: DD/MM/YYYY | DD-MM-YYYY | DD.MM.YYYY\nउदाहरण: *15/08/1990*",
        "hi-en": "📅 Kripya apni *janam tithi* in formats mein darj karein: DD/MM/YYYY | DD-MM-YYYY | DD.MM.YYYY\nUdaharan: *15/08/1990*"
    },
   "ask_birth_time": {
        "en": "⏰ What time were you born? Examples: *2:30 PM*, *5:30 AM*, *14:30*, or type *unknown* if you’re unsure. This helps me make your cosmic blueprint precise!",
        "hi": "⏰ आपका जन्म समय क्या था? उदाहरण: *2:30 PM*, *5:30 AM*, *14:30*, या अगर आप सुनिश्चित नहीं हैं तो *unknown* टाइप करें। यह आपकी कॉस्मिक प्रोफाइल को सटीक बनाने में मदद करता है!",
        "hi-en": "⏰ Aapka janam samay kya tha? Udaharan: *2:30 PM*, *5:30 AM*, *14:30*, ya agar aap unsure hain to *unknown* type karein. Ye aapki cosmic profile accurate banane mein madad karega!"
    },
    "ask_birth_city": {
        "en": "🌆 Please tell me your *birth city*. You can either type it (e.g., *Bangalore, Mumbai, Delhi, Jodhpur, Erode, etc*) or share your location 📍 for exact accuracy.",
        "hi": "🌆 कृपया अपना *जन्म शहर* बताएं। आप इसे टाइप कर सकते हैं (जैसे: *मुंबई, भारत*) या अधिक सटीकता के लिए लोकेशन 📍 भेज सकते हैं।",
        "hi-en": "🌆 Kripya apna *janam sheher* batayein. Aap type kar sakte hain (Udaharan: *Mumbai, India*) ya accurate ke liye location 📍 bhej sakte hain."
    },
    "profile_complete": {
        "en": "🎉 Your cosmic profile is ready! Ask me anything, or select an option below to explore your universe further ✨",
        "hi": "🎉 आपकी कॉस्मिक प्रोफाइल तैयार है! मुझसे कुछ भी पूछें, या नीचे विकल्प चुनकर अपने ब्रह्मांड की खोज जारी रखें ✨",
        "hi-en": "🎉 Aapki cosmic profile tayaar hai! Mujhse kuch bhi poochhein, ya neeche option choose karke apna brahmand explore karein ✨"
    },
    "birth_date_error": {
        "en": "❌ Oops! That doesn’t look like a valid date. Try formats like: *15/08/1990*, *15-08-1990*, or *15.08.1990* 😊",
        "hi": "❌ ओह! यह मान्य तारीख नहीं लग रही। कृपया इन प्रारूपों में प्रयास करें: *15/08/1990*, *15-08-1990*, या *15.08.1990* 😊",
        "hi-en": "❌ Oho! Ye valid date nahi lag rahi. Kripya try karein: *15/08/1990*, *15-08-1990*, ya *15.08.1990* 😊"
    },
      "birth_time_error": {
        "en": "❌ Hmm, that time format seems off. Try: *2:30 PM*, *14:30*, or *unknown* if unsure.",
        "hi": "❌ लगता है समय प्रारूप सही नहीं है। कोशिश करें: *2:30 PM*, *14:30*, या यदि सुनिश्चित नहीं हैं तो *unknown*।",
        "hi-en": "❌ Lagta hai time format sahi nahi hai. Try karein: *2:30 PM*, *14:30*, ya agar unsure hain to *unknown*."
    },
      "location_error":{
        "en": "📍 Hmm, I couldn’t process that location. Please type your city name instead. Example: *Delhi, India*",
        "hi": "📍 लगता है मैं लोकेशन प्रोसेस नहीं कर सका। कृपया अपने शहर का नाम टाइप करें। उदाहरण: *दिल्ली, भारत*",
        "hi-en": "📍 Lagta hai location process nahi ho saka. Kripya apne sheher ka naam type karein. Udaharan: *Delhi, India*"
    },
    "cosmic_profile_error": {
        "en":"⚠️ There was an issue saving your cosmic profile. Please try 'restart'.",
        "hi":"⚠️ आपकी कॉस्मिक प्रोफाइल सहेजने में समस्या हुई। कृपया 'restart' आजमाएं।",
        "hi-en": "⚠️ Aapki cosmic profile save karne mein samasya aayi. Kripya 'restart' karke koshish karein.",
    },
    "cosmic_data_issue":{
        "en": "There was a problem accessing your natal chart. Type 'restart' to recreate your cosmic profile! 🔄✨",
        "hi": "आपकी जन्म कुंडली तक पहुंचने में समस्या हुई। 'restart' टाइप करें ताकि आप अपनी कॉस्मिक प्रोफाइल फिर से बना सकें! 🔄✨",
        "hi-en": "Aapki janam kundali tak pahunchne mein samasya aayi. 'restart' type karein taaki aap apni cosmic profile phir se bana sakein! 🔄✨",
    },
     "creating_cosmic_profile": {
        "en": "✨ Creating your cosmic profile now... This will take a few seconds! 🚀",
        "hi": "✨ आपकी कॉस्मिक प्रोफाइल बनाई जा रही है... कृपया कुछ सेकंड प्रतीक्षा करें! 🚀",
        "hi-en": "✨ Aapki cosmic profile banayi ja rahi hai... Kripya kuch seconds pratiksha karein! 🚀"
    },
    "daily_horoscope_title": {
        "en": "🌟 *Your Daily Horoscope, {name}* 🌟",
        "hi": "🌟 *आपका दैनिक राशिफल, {name}* 🌟",
        "hi-en": "🌟 *Aapka Daily Rashifal, {name}* 🌟"
    },
      "cosmic_climate": {
        "en": "☀️ *Cosmic Climate*: {summary}",
        "hi": "☀️ *कॉस्मिक जलवायु*: {summary}",
        "hi-en": "☀️ *Cosmic Climate*: {summary}"
    },
    "energy": {
        "en": "⚡ *Energy*: {description}",
        "hi": "⚡ *ऊर्जा*: {description}",
        "hi-en": "⚡ *Energy*: {description}"
    },
    "career": {
        "en": "💼 *Career*: {description}",
        "hi": "💼 *करियर*: {description}",
        "hi-en": "💼 *Career*: {description}"
    },
    "relationships": {
        "en": "❤️ *Relationships*: {description}",
        "hi": "❤️ *संबंध*: {description}",
        "hi-en": "❤️ *Relationships*: {description}"
    },
    "health": {
        "en": "💊 *Health*: {description}",
        "hi": "💊 *स्वास्थ्य*: {description}",
        "hi-en": "💊 *Health*: {description}"
    },
    "planetary_insight": {
        "en": "🪐 *Planetary Insight*: {planet}",
        "hi": "🪐 *ग्रहों की अंतर्दृष्टि*: {planet}",
        "hi-en": "🪐 *Planetary Insight*: {planet}"
    },
    "practical_tips": {
        "en": "💡 *Practical Tip*: {mantra}",
        "hi": "💡 *व्यावहारिक सुझाव*: {mantra}",
        "hi-en": "💡 *Practical Tip*: {mantra}"
    },
    "personal_message_title": {
        "en": "💌 *Personal Message*:",
        "hi": "💌 *व्यक्तिगत संदेश*:",
        "hi-en": "💌 *Personal Message*:"
    },
    "feedback_prompt": {    
        "en": "We value your feedback! Please share your thoughts on this horoscope.",
        "hi": "हम आपकी प्रतिक्रिया की सराहना करते हैं! कृपया इस राशिफल पर अपने विचार साझा करें।",
        "hi-en": "Hum aapki pratikriya ki sarahna karte hain! Kripya is rashifal par apne vichar saanjha karein."
    },  
    "feedback_thanks": {
        "en": "Thank you for your feedback! 🌟",
        "hi": "आपकी प्रतिक्रिया के लिए धन्यवाद! 🌟",
        "hi-en": "Aapki pratikriya ke liye dhanyavaad! 🌟"
    },
    "suggested_question_follow_up":{
        "en":" Building on our conversation - what else would you like to explore? ✨",
        "hi":" हमारी बातचीत पर आधारित - आप और क्या जानना चाहेंगे? ✨",
        "hi-en":" Hamari baatcheet par aadhaarit - aap aur kya jaanana chahenge? ✨"
    },
    "suggested_question_what_else":{
        "en":"What else would you like to know about your cosmic journey? ✨",
        "hi":"आप अपनी कॉस्मिक यात्रा के बारे में और क्या जानना चाहेंगे? ✨",
        "hi-en":"Aap apni cosmic yatra ke baare mein aur kya jaanana chahenge? ✨"
    },
    "feedback_thumbs_up_response":{
        "en":"Thank you for your positive feedback! What did you enjoy the most?",
            "hi":"आपकी सकारात्मक प्रतिक्रिया के लिए धन्यवाद! आपको सबसे ज्यादा क्या पसंद आया?",
            "hi-en":"Aapki sakaratmak pratikriya ke liye dhanyavaad! Aapko sabse zyada kya pasand aaya?",
    },
    "feedback_thumbs_down_response":{
        "en":"We're sorry to hear that. Could you tell us what we can improve?",
        "hi":"हमें खेद है कि आपको यह पसंद नहीं आया। क्या आप हमें बता सकते हैं कि हम क्या सुधार सकते हैं?",
        "hi-en":"Humein khed hai ki aapko yeh pasand nahi aaya. Kya aap humein bata sakte hain ki hum kya sudhaar sakte hain?",
    },
    "conversation_reset": {
    "en": "Okay, I've reset our conversation. What would you like to ask about now?",
    "hi": "ठीक है, मैंने हमारी बातचीत रीसेट कर दी है। अब आप किस बारे में पूछना चाहेंगे?",
    "hi-en": "Theek hai, maine hamari baatcheet reset kar di. Ab aap kiske baare mein poochhna chahenge?"
    },
   "feedback_already_active": {
    "en": "You’re already in a feedback session. Please share your comments.",
    "hi": "आप पहले से ही फीडबैक दे रहे हैं। कृपया अपनी राय साझा करें।",
    "hi-en": "Aap pehle se hi feedback de rahe hain. Kripya apni rai saanjha karein."
    },
    "welcome_privacy_message": {
        "en": """
Hey there! Ready to see what the universe has planned for you?
- We use NASA-verified birth data so your readings are pinpoint accurate
- Want privacy? Just say "Delete my data" anytime to erase your records 

Let's begin...
        """,
        "hi": """
नमस्ते! क्या आप जानना चाहते हैं कि ब्रह्मांड आपके लिए क्या योजना बना रहा है?
- हम NASA-प्रमाणित जन्म डेटा का उपयोग करते हैं ताकि आपकी रीडिंग सटीक हो 
- क्या आपको गोपनीयता चाहिए? कभी भी "मेरे डेटा को हटाएं" कहकर अपने रिकॉर्ड मिटा सकते हैं

चलो शुरू करते हैं... 
        """
        ,
        "hi-en": """
Namaste! Kya aap jaana chahte hain ki Brahmand aapke liye kya yojana bana raha hai?
- Hum NASA-pramanit janm data ka upyog karte hain taaki aapki reading sahi ho
- Kya aapko gopniyata chahiye? Kabhi bhi "Mere data ko hatao" kehkar apne record mita sakte hain

shuru karte hain...
        """
        },
    "privacy_continue_button": {
        "en": "Continue",
        "hi": "जारी रखें", 
        "hi-en": "Continue karein"
    },
  "casual_greet_message": {
    "en": "Hey there! 🌟 I'm your personal astrologer, ready to unlock cosmic wisdom for you! Here's what I can help with:\n\n• *Daily Horoscope* - Get your free daily cosmic forecast\n• *Compatibility* - Check love & relationship harmony with partners\n• *Ask Anything* - Career, love, health - no question too big or small\n• *Switch Profiles* - Manage charts and get astrological guidance and charts for family & friends\n• *Your Data* - Delete anytime for complete privacy\n\nJust type 'Daily' for horoscope, 'Compatibility' for partners, 'Delete my data' to erase you info from our db or ask me anything on your mind! 💫",
    "hi": "नमस्ते! 🌟 मैं आपका वैदिक ज्योतिषी हूं, आपके लिए ब्रह्मांडीय ज्ञान उपलब्ध कराने को तैयार! यहां बताएं कि मैं कैसे मदद कर सकता हूं:\n\n• *रोज का राशिफल* - मुफ्त दैनिक भविष्यवाणी\n• *कम्पैटिबिलिटी* - साथियों के साथ प्यार और तालमेल जांचें\n• *कुछ भी पूछें* - करियर, प्यार, स्वास्थ्य - कोई सवाल छोटा या बड़ा नहीं\n• *प्रोफाइल बदलें* - परिवार/दोस्तों की कुंडली आसानी से प्रबंधित करें\n• *आपका डेटा* - पूरी गोपनीयता के लिए कभी भी हटाएं\n\nबस 'डेली' लिखें राशिफल के लिए, 'कम्पैटिबिलिटी' साथियों के लिए, या मन में आया कोई सवाल पूछें! 💫",
    "hi-en": "Namaste! 🌟 Main aapka personal astrologer hoon, cosmic wisdom dene ko tayyar! Yeh lo main kya kar sakta hoon:\n\n• *Daily Horoscope* - Free daily cosmic forecast\n• *Compatibility* - Pyaar aur rishtey ki harmony check karein\n• *Kuch bhi poochhein* - Career, pyaar, health - koi sawaal chota ya bada nahin\n• *Switch Profiles* - Family/doston ki kundli aasani se manage karein\n• *Aapka Data* - Complete privacy ke liye kabhi bhi delete karein\n\nBas 'Daily' type karein horoscope ke liye, 'Compatibility' partners ke liye, ya koi bhi sawaal poochhein! 💫"
}

}

PAYMENT_PLANS = {
    "9": {
        "amount": 900,
        "questions": 2,
        "validity": "24 hours",
        "description": "2 more questions (valid 24 hrs)",
        "plan_code": settings.LAGO_PLAN_CODE_DAILY,
        "interval":"weekly",
        "display_price": "₹9"
    },
    "49": {
        "amount": 4900,
        "questions": 20,
        "validity": "7 days", 
        "description": "20 questions for 7 days",
        "plan_code": settings.LAGO_PLAN_CODE_WEEKLY,
        "interval":"weekly",
        "display_price": "₹49"
    },
    "custom": {
        "amount": 900,  
        "questions": 2,
        "validity": "24 hours",
        "description": "2 more questions (valid 24 hrs)",
        "plan_code": settings.LAGO_PLAN_CODE_DAILY,  
        "display_price": "₹9"
    }
}

HEAVY_TASKS = {
    "daily_horoscope",
    "ask_question",
    "compatibility",
    "cosmic_guidance",
    "generate_chart",
    "view_kundli",
    "chat",
    "horoscope_request"
}
def detect_special_intent(text: str) -> str:
    try:
        if not text:
            return "unknown_intent"

        t = text.lower().strip()

        lang_triggers = [
            r"change (?:my )?language(?: to)?", 
            r"switch (?:to )?(english|hindi|hinglish)",
            r"set language to",
            r"भाषा बदलो",
            r"हिन्दी (?:में|चाहिए|कर दो)",
            r"english please",
            r"switch language",
            r"i want (?:to )?speak in (english|hindi|hinglish)",
            r"talk (?:to me )?(?:in )?(english|hindi|hinglish)",
            r"use (english|hindi|hinglish)",
            r"go to (english|hindi|hinglish)",
            r"can we continue in (english|hindi|hinglish)",
            r"मुझे (?:अंग्रेजी|हिंदी) चाहिए",
            r"कृपया (?:अंग्रेजी|हिंदी) में",
            r"switch chat to (english|hindi|hinglish)",
            r"(?:change|switch) conversation (?:to )?(english|hindi|hinglish)"
            r"language (?:change|switch|set) to (english|hindi|hinglish)",
            r"feel like speaking in (english|hindi|hinglish)",
        ]

        profile_triggers = [
            r"\bmanage profiles?\b",
            r"\b(profile|profiles) (settings|manage)\b",
            r"\b(profile|profiles) (settings|manage|management|options|menu)\b",
            r"\bi want to switch profiles?\b",
            r"\blet['’]?s switch profiles?\b",
            r"\bswitch profile\b",
            r"\bchange profile\b",
            r"\bselect profile\b",
            r"\bshow profiles?\b",
            r"\b(profile|profiles) (settings|manage)\b",
            r"\bi want to switch profiles?\b",
            r"\blet['’]?s switch profiles?\b",
            r"\bswitch profile\b",
            r"\bswitch to profile\b",
            r"\bswitch profiles\b",
            r"\bchange profile\b",
            r"\bupdate profile\b",
            r"\bselect profile\b",
            r"\bshow profiles?\b",
            r"\bview profiles?\b",
            r"\blist profiles?\b",
            r"\bprofile list\b",
            r"\bchoose profile\b",
            r"\bpick profile\b",
            r"\bi want to change profile\b",
            r"\bi want to switch profile\b",
            r"\bcan you switch profile\b",
            r"\bcan you change profile\b",
            r"\bactivate profile\b",
            r"\bset active profile\b",
            r"\bopen profile list\b",
            r"\bprofile options\b",
            r"\bprofile menu\b",
            r"\bprofile switch\b",
            r"\bbecome another profile\b",
            r"\b(exit|quit|leave|stop|cancel)(?:\s*(?:to)?\s*(main|menu|home|start|hub|dashboard|options|beginning|profil(?:e)? menu)?)?\b"

        ]
        for pattern in profile_triggers:
            if re.search(pattern, t):
                return "manage_profiles"
        profile_creation_triggers = [
            r"\bnew profile\b",
            r"\bcreate profile\b",
            r"\badd profile\b",
            r"\bmake profile\b",
            r"\bregister profile\b",
            r"\bsetup profile\b",
            r"\bstart profile\b",
            r"\bopen new profile\b",
            r"\bbegin new profile\b",
            r"\bnew account\b",
            r"\badd account\b",
            r"\bcreate account\b",
            r"\bstart a new account\b",
            r"\bnew user\b",
            r"\badd user\b",
            r"\bcreate new user\b",
            r"\badd new profile\b",
            r"\bmake new profile\b",
            r"\bsetup new profile\b",
            r"\bstart new profile\b",
            r"\bmake another profile\b",
            r"\badd another profile\b",
            r"\bcreate another profile\b",
            r"\bi want to add a profile\b",
            r"\bi want to create a profile\b",
            r"\bi want to set up a profile\b",
            r"\bcan you create a profile\b",
            r"\bcan you add a profile\b",
    ]

        for pattern in profile_creation_triggers:
            if re.search(pattern, t):
                return "create_profile"
        
        for pattern in lang_triggers:
            if re.search(pattern, t):
                return "change_language"
        greet_patterns = [
            r"^(hi|hello|hey|heyy|heya|yo|hii|sup|wassup|what'?s up|whatsup)$",
            r"^(good (morning|afternoon|evening|night))$",
            r"^(gm|gn)$",
        ]
        for pat in greet_patterns:
            if re.match(pat, t):
                return "casual_hello"
        payment_triggers = [
            r"\bpay\b",
            r"\bpayment\b",
            r"\bupgrade\b",
            r"\bsubscribe\b",
            r"\bbuy\b",
            r"\bpurchase\b",
            r"\bunlock\b",
            r"\bplan\b",
            r"\bpremium\b"
        ]

        for pattern in payment_triggers:
            if re.search(pattern, t):
                return "initiate_payment"
        view_chart_patterns = [
            r"\b(view|see|show|open|display|check|get|give|provide|send|fetch|receive)\s*(me\s*)?(my\s*)?(chart|kundli|kundali|birth chart)\b",
            r"\b(can (i|you) (have|get|see|show|fetch|send|provide|receive)\s*(my\s*)?(chart|kundli|kundali|birth chart))\b",
            r"\b(i want to (see|view|look at|check|get|fetch|receive)\s*(my\s*)?(chart|kundli|kundali|birth chart))\b",
            r"\bbirth chart\b",
            r"\bkundali\b",
            r"\bkundli\b",
        ]

        if any(re.search(pattern, t) for pattern in view_chart_patterns):
            return "view_chart"
        
        if t in {"hi", "hello", "hey", "yo", "sup", "wassup", "what's up", "whatsup", "gm", "gn"}:
            return "casual_hello"
        
        words = t.split()
        if len(words) > 3:
            most_common_word, count = Counter(words).most_common(1)[0]
            if count >= 4 and all(w == most_common_word for w in words):
                return "casual_hello"

        # New check for repeated characters 5+ times (e.g "aaaaaa", "!!!!!!!")
        if re.match(r"^(.)\1{4,}$", t):
            return "casual_hello"

        # New check for messages with many repeated short words or nonsense (like "asdf asdf asdf")
        if len(words) > 2 and len(set(words)) == 1:
            return "casual_hello"
        lucky_number_triggers = [
                r"\blucky number\b",
                r"\bwhat is my lucky number\b",
                r"\blucky number for me\b",
                r"\bshow my lucky number\b",
                r"\bfind my lucky number\b",
                r"\bcalculate my lucky number\b",
                r"\bmy lucky number is\b",
                r"\bgive me my lucky number\b",
                r"\bdo i have a lucky number\b",
                r"\bcan you tell my lucky number\b",
                r"\bpls share my lucky number\b",
                r"\blucky number please\b",
                r"\bwanna know lucky number\b",
                r"\bwhat's my lucky number\b",
                r"\blucky number today\b",
                r"\blucky number\b",
                r"\blucky number now\b",
                r"\blucky number for today\b",
                r"\blucky digit\b",
                r"\blucky number based on birth\b",
                r"\blucky number astrology\b"
        ]
        for pattern in lucky_number_triggers:
            if re.search(pattern, t):
                return "lucky_number"
        if t in ["9", "49"]:
            return "select_payment_plan"
        # Other intents remain the same
        if any(k in t for k in ["delete my data", "delete data", "clear data"]):
            return "delete_data"
        if any(k in t for k in ["restart", "start over", "begin again", "reset"]):
            return "restart"
        if any(k in t for k in ["feedback", "suggestion", "review", "rate"]):
            return "give_feedback"
        if text.strip() in ["👍", "👎", "👍 Thumbs Up", "👎 Thumbs Down"]:
            return "give_feedback"
        if any(kw in t for kw in [
            "check my kundli", "compare kundli", "with my wife", "with my husband",
            "compatibility", "match making", "matchmaking", "kundali milan"
        ]):
            return "start_compatibility"
        return "unknown_intent"

    except Exception as e:
        logger.error(f"Error in detect_special_intent: {e}", exc_info=True)
        return "error"
    
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

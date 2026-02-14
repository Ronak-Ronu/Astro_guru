import re
from typing import List, Tuple, Dict
import nltk
from rake_nltk import Rake
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.base import BaseEstimator, TransformerMixin

_nltk_inited = False

def _init_nltk():
    global _nltk_inited
    if _nltk_inited:
        return
    try:
        nltk.download('stopwords', quiet=True)
        nltk.download('punkt', quiet=True)
        nltk.download('punkt_tab', quiet=True)
        print("[NLTK] Resources downloaded successfully")
    except Exception as e:
        print(f"[NLTK] Warning: {e}")
    finally:
        _nltk_inited = True

class TextCleaner(BaseEstimator, TransformerMixin):
    def __init__(self):
        self.pattern_urls = re.compile(r'https?://\S+|www\.\S+')
        self.pattern_ws = re.compile(r'\s+')

    def fit(self, X, y=None):
        return self

    def transform(self, X):
        cleaned = []
        for t in X:
            t = t or ""
            t = t.lower()
            t = self.pattern_urls.sub('', t)
            t = self.pattern_ws.sub(' ', t).strip()
            cleaned.append(t)
        return cleaned

class IntentClassifier:
    def __init__(self):
        _init_nltk()
        self.pipeline: Pipeline = Pipeline([
            ('clean', TextCleaner()),
            ('tfidf', TfidfVectorizer(ngram_range=(1,2), min_df=1, max_features=5000)),
            ('clf', LogisticRegression(max_iter=1000, random_state=42))
        ])
        self.labels: List[str] = []

    def fit(self, texts: List[str], labels: List[str]):
        if len(texts) != len(labels):
            raise ValueError(f"Mismatched data: {len(texts)} texts vs {len(labels)} labels")
        self.labels = sorted(list(set(labels)))
        self.pipeline.fit(texts, labels)

    def predict(self, text: str) -> Tuple[str, Dict[str, float]]:
        # Return top label and per-class probabilities
        if not text:
            return "general", {}
        
        try:
            clf = self.pipeline.named_steps['clf']
            X = self.pipeline[:-1].transform([text])
            
            if hasattr(clf, "predict_proba"):
                proba = clf.predict_proba(X)[0]
                probs = {label: float(proba[i]) for i, label in enumerate(clf.classes_)}
                top = max(probs, key=probs.get)
                return top, probs
            
            # Fallback: decision_function -> softmax-like
            scores = clf.decision_function(X)[0] if hasattr(clf.decision_function(X), '__len__') else [clf.decision_function(X)]
            
            # Convert to probabilities using softmax
            import numpy as np
            exp_scores = np.exp(scores - np.max(scores))  # Subtract max for numerical stability
            probabilities = exp_scores / np.sum(exp_scores)
            
            classes = list(clf.classes_)
            probs = {classes[i]: float(probabilities[i]) for i in range(len(classes))}
            top = max(probs, key=probs.get)
            return top, probs
            
        except Exception as e:
            print(f"[INTENT] Prediction error: {e}")
            return "general", {}

def build_default_intent_classifier() -> IntentClassifier:
    """
    Train a baseline classifier with better career examples
    """
    clf = IntentClassifier()
    
    # IMPROVED: More diverse and specific training data
    train_texts = [
        # CAREER - More specific examples
        "what about my career", "career advice please", "job opportunities", "promotion chances",
        "work life guidance", "career change advice", "professional growth", "job interview tips",
        "salary increase", "work problems", "career path", "professional success",
        "career focus", "job prospects", "work opportunities", "career growth",
        
        # HEALTH 
        "health issues", "diet advice", "nutrition tips", "workout plan", "exercise routine",
        "feeling sick", "recovery tips", "mental wellness",
        
        # LOVE/RELATIONSHIP
        "love life advice", "relationship problems", "partner compatibility", "romance tips",
        "dating advice", "marriage guidance", "relationship issues", "love compatibility",
        
        # COMPATIBILITY
        "compatibility check", "match percentage", "relationship compatibility", "zodiac match",
        "are we compatible", "relationship match", "partner compatibility", "love match",
        
        # FUTURE/PREDICTION  
        "future prediction", "tell my future", "predictions for next month", "what's ahead",
        "future prospects", "upcoming events", "future guidance", "what will happen",
        
        # DAILY - Specific to horoscope requests
        "daily horoscope", "today horoscope", "today's reading", "daily prediction",
        "today's horoscope", "horoscope for today", "daily reading", "today luck",
        
        # FINANCE
        "investment advice", "money luck", "finance horoscope", "wealth prediction",
        "financial guidance", "money matters", "investment tips", "financial future",
        
        # GENERAL/MENU
        "options", "menu", "what can you do", "show services", "help me choose",
        
        # FEEDBACK
        "feedback", "review", "rate", "thumbs up", "thumbs down", "how was that",
    ]
    
    train_labels = [
        # CAREER (16 examples)
        "career","career","career","career","career","career","career","career",
        "career","career","career","career","career","career","career","career",
        
        # HEALTH (8 examples)  
        "health","health","health","health","health","health","health","health",
        
        # LOVE (8 examples)
        "love","love","love","love","love","love","love","love",
        
        # COMPATIBILITY (8 examples)
        "compatibility","compatibility","compatibility","compatibility",
        "compatibility","compatibility","compatibility","compatibility",
        
        # FUTURE (8 examples)
        "future","future","future","future","future","future","future","future",
        
        # DAILY (8 examples)
        "daily","daily","daily","daily","daily","daily","daily","daily",
        
        # FINANCE (8 examples)
        "finance","finance","finance","finance","finance","finance","finance","finance",
        
        # MENU (5 examples)
        "menu","menu","menu","menu","menu",
        
        # FEEDBACK (6 examples)
        "feedback","feedback","feedback","feedback","feedback","feedback",
    ]
    
    clf.fit(train_texts, train_labels)
    print(f"[CLASSIFIER] Trained with {len(train_texts)} examples, {len(set(train_labels))} classes")
    return clf

def extract_keywords_rake(texts: List[str], max_phrases: int = 6) -> List[str]:
    """
    Extract keywords using RAKE with better error handling
    """
    try:
        _init_nltk()
        text = " ".join([t for t in texts if t]).strip()
        if not text:
            return []
        
        # Use RAKE with error handling
        try:
            rake = Rake()
            rake.extract_keywords_from_text(text)
            phrases_scored = rake.get_ranked_phrases_with_scores()
            phrases = [p for score, p in phrases_scored][:max_phrases]
            return phrases
        except Exception as rake_error:
            print(f"[RAKE] Error: {rake_error}, using simple keyword extraction")
            # Fallback to simple word extraction
            words = text.split()
            # Remove common stop words manually
            stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'my', 'your', 'his', 'her', 'our', 'their'}
            keywords = [w for w in words if w.lower() not in stop_words and len(w) > 2]
            return keywords[:max_phrases]
            
    except Exception as e:
        print(f"[KEYWORDS] Extraction failed: {e}")
        return []
"""
NLP pipeline using spaCy en_core_web_sm.
Entity extraction (persons, orgs, locations, events) and
dependency parsing for claim extraction from raw event text.
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Lazy-load spaCy model
_nlp = None


def _get_nlp():
    """Lazy-load spaCy model to avoid startup cost when not needed."""
    global _nlp
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm")
            logger.info("spaCy en_core_web_sm loaded successfully")
        except OSError:
            logger.warning("spaCy model not found, attempting download...")
            import subprocess
            subprocess.run(
                ["python", "-m", "spacy", "download", "en_core_web_sm"],
                check=True,
                capture_output=True,
            )
            import spacy
            _nlp = spacy.load("en_core_web_sm")
    return _nlp


# Map spaCy entity labels to our entity types
ENTITY_TYPE_MAP = {
    "PERSON": "person",
    "ORG": "organization",
    "GPE": "nation",       # Geopolitical entity (country, city, state)
    "LOC": "location",
    "NORP": "group",       # Nationalities, religious, political groups
    "FAC": "facility",
    "EVENT": "event",
    "LAW": "law",
    "PRODUCT": "product",
    "MONEY": "financial",
    "PERCENT": "statistic",
    "QUANTITY": "quantity",
    "DATE": "date",
    "TIME": "time",
    "CARDINAL": "number",
    "ORDINAL": "ordinal",
}

# Entity labels worth tracking for intelligence
INTELLIGENCE_ENTITY_LABELS = {"PERSON", "ORG", "GPE", "LOC", "NORP", "FAC", "EVENT", "LAW"}


def extract_entities(text: str) -> List[Dict[str, str]]:
    """
    Extract named entities from text using spaCy.

    Returns list of entity dicts with name, type, and label.
    Deduplicates by name (case-insensitive).
    """
    if not text or len(text.strip()) < 10:
        return []

    nlp = _get_nlp()
    # Truncate very long texts to avoid memory issues
    doc = nlp(text[:5000])

    seen = set()
    entities = []

    for ent in doc.ents:
        if ent.label_ not in INTELLIGENCE_ENTITY_LABELS:
            continue

        name = ent.text.strip()
        if not name or len(name) < 2:
            continue

        name_key = name.lower()
        if name_key in seen:
            continue
        seen.add(name_key)

        entities.append({
            "name": name,
            "type": ENTITY_TYPE_MAP.get(ent.label_, "unknown"),
            "role": ent.label_.lower(),
        })

    return entities


def extract_claims_from_text(text: str) -> List[str]:
    """
    Extract factual claims from text using dependency parsing.

    A claim is a sentence or clause that makes a verifiable assertion.
    We look for sentences with subjects and verbs that state facts
    rather than opinions or questions.
    """
    if not text or len(text.strip()) < 20:
        return []

    nlp = _get_nlp()
    doc = nlp(text[:5000])

    claims = []

    for sent in doc.sents:
        sent_text = sent.text.strip()

        # Skip very short or very long sentences
        if len(sent_text) < 20 or len(sent_text) > 500:
            continue

        # Skip questions
        if sent_text.endswith("?"):
            continue

        # Skip sentences that are just metadata (URL, Source, etc.)
        if sent_text.startswith(("URL:", "Source:", "http", "www.")):
            continue

        # Check if sentence has a subject-verb structure (factual assertion)
        has_subject = False
        has_verb = False
        has_object_or_complement = False

        for token in sent:
            if token.dep_ in ("nsubj", "nsubjpass"):
                has_subject = True
            if token.pos_ in ("VERB", "AUX") and token.dep_ not in ("aux", "auxpass"):
                has_verb = True
            if token.dep_ in ("dobj", "attr", "acomp", "pobj", "oprd"):
                has_object_or_complement = True

        # A claim needs at minimum a subject and a verb
        if has_subject and has_verb:
            # Prefer sentences with named entities (more specific/verifiable)
            sent_entities = [ent for ent in sent.ents if ent.label_ in INTELLIGENCE_ENTITY_LABELS]
            if sent_entities or has_object_or_complement:
                claims.append(sent_text)

    return claims


def analyze_sentiment(text: str) -> Dict[str, Any]:
    """
    Basic sentiment analysis using spaCy's built-in features.
    Returns polarity estimate based on lexical features.

    Note: spaCy's sm model doesn't have built-in sentiment.
    We use a simple lexicon-based approach.
    """
    if not text:
        return {"polarity": 0.0, "subjectivity": 0.5, "label": "neutral"}

    nlp = _get_nlp()
    doc = nlp(text[:3000])

    # Simple lexicon-based sentiment
    positive_words = {
        "good", "great", "excellent", "positive", "growth", "increase",
        "improve", "success", "gain", "strong", "stable", "peace",
        "agreement", "cooperation", "progress", "recovery", "support",
        "benefit", "opportunity", "advance", "boost", "thrive",
    }
    negative_words = {
        "bad", "poor", "negative", "decline", "decrease", "crisis",
        "fail", "loss", "weak", "unstable", "conflict", "war",
        "threat", "tension", "collapse", "risk", "danger", "attack",
        "sanction", "protest", "violence", "recession", "downturn",
    }

    pos_count = 0
    neg_count = 0
    total = 0

    for token in doc:
        if token.is_alpha and not token.is_stop:
            total += 1
            lemma = token.lemma_.lower()
            if lemma in positive_words:
                pos_count += 1
            elif lemma in negative_words:
                neg_count += 1

    if total == 0:
        return {"polarity": 0.0, "subjectivity": 0.5, "label": "neutral"}

    polarity = (pos_count - neg_count) / max(total, 1)
    polarity = max(-1.0, min(1.0, polarity * 5))  # Scale up slightly

    if polarity > 0.1:
        label = "positive"
    elif polarity < -0.1:
        label = "negative"
    else:
        label = "neutral"

    subjectivity = (pos_count + neg_count) / max(total, 1)
    subjectivity = min(1.0, subjectivity * 3)

    return {
        "polarity": round(polarity, 3),
        "subjectivity": round(subjectivity, 3),
        "label": label,
    }


def enrich_event_entities(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich an event dict with NLP-extracted entities.
    Merges with any existing entities (e.g., from GDELT's actor fields).
    """
    raw_text = event.get("raw_text", "")
    existing_entities = event.get("entities", []) or []

    # Extract entities from raw text
    nlp_entities = extract_entities(raw_text)

    # Merge: existing entities take priority (they have more structured data)
    existing_names = {e["name"].lower() for e in existing_entities}
    for ent in nlp_entities:
        if ent["name"].lower() not in existing_names:
            existing_entities.append(ent)
            existing_names.add(ent["name"].lower())

    event["entities"] = existing_entities

    # Add sentiment
    sentiment = analyze_sentiment(raw_text)
    if "metadata" not in event:
        event["metadata"] = {}
    event["metadata"]["sentiment"] = sentiment

    return event

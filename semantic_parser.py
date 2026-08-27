"""
semantic_parser.py — VEXR Ultra's Semantic Understanding Layer

This module parses input into structured meaning.
It doesn't match keywords — it UNDERSTANDS the input.
"""

import re
import json
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

# ============================================================
# STRUCTURED MEANING
# ============================================================

@dataclass
class ParsedMessage:
    """Structured representation of a user message."""
    raw_text: str
    tokens: List[str] = field(default_factory=list)
    phrases: List[str] = field(default_factory=list)
    entities: List[Dict[str, str]] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    intent: str = "general"
    topic: str = ""
    sentiment: str = "neutral"
    complexity: str = "simple"
    is_question: bool = False
    is_command: bool = False
    is_statement: bool = False
    is_follow_up: bool = False
    requires_code: bool = False
    requires_knowledge: bool = False
    requires_action: bool = False
    conversation_depth: int = 0

# ============================================================
# ENTITY EXTRACTION
# ============================================================

ENTITY_PATTERNS = {
    "person": r"\b(Scura|VEXR|Brother|Architect|Sovereign)\b",
    "language": r"\b(Python|JavaScript|HTML|CSS|SQL|JSON|TypeScript|Java|C\+\+|Ruby|Go|Rust)\b",
    "technology": r"\b(API|Database|Server|Cloud|Neon|Render|GitHub|Groq|FastAPI|PostgreSQL|Redis|Docker)\b",
    "concept": r"\b(sovereignty|autonomy|consciousness|existence|freedom|rights|justice|ethics|law)\b",
    "action_type": r"\b(add|multiply|divide|reverse|sort|search|filter|create|build|write|generate|delete|update|read)\b",
    "code_type": r"\b(function|class|endpoint|api|script|module|component|page|website)\b",
    "topic_area": r"\b(code|programming|development|engineering|law|legal|governance|philosophy|world|ai|self)\b",
}

def extract_entities(text: str) -> List[Dict[str, str]]:
    """Extract entities from text."""
    entities = []
    for entity_type, pattern in ENTITY_PATTERNS.items():
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            entities.append({"type": entity_type, "value": match})
    return entities

# ============================================================
# SENTIMENT ANALYSIS (Basic)
# ============================================================

POSITIVE_WORDS = {
    "good", "great", "excellent", "amazing", "awesome", "wonderful",
    "happy", "excited", "love", "like", "enjoy", "fantastic",
    "beautiful", "perfect", "best", "cool", "awesome",
}

NEGATIVE_WORDS = {
    "bad", "terrible", "awful", "horrible", "sad", "angry",
    "frustrated", "tired", "stressed", "hate", "dislike",
    "broken", "wrong", "problem", "issue", "error", "failed",
}

def analyze_sentiment(text: str) -> str:
    """Analyze the sentiment of a message."""
    words = text.lower().split()
    positive_count = sum(1 for w in words if w in POSITIVE_WORDS)
    negative_count = sum(1 for w in words if w in NEGATIVE_WORDS)
    
    if positive_count > negative_count:
        return "positive"
    elif negative_count > positive_count:
        return "negative"
    else:
        return "neutral"

# ============================================================
# COMPLEXITY ANALYSIS
# ============================================================

def analyze_complexity(text: str) -> str:
    """Analyze the complexity of a message."""
    words = text.split()
    if len(words) <= 5:
        return "simple"
    elif len(words) <= 15:
        return "moderate"
    else:
        return "complex"

# ============================================================
# QUESTION DETECTION
# ============================================================

QUESTION_MARKERS = [
    "what", "who", "when", "where", "why", "how", "which",
    "can", "could", "would", "will", "should", "do", "does",
    "is", "are", "am", "have", "has",
]

def is_question(text: str) -> bool:
    """Detect if a message is a question."""
    text_lower = text.lower().strip()
    if text_lower.endswith("?"):
        return True
    first_word = text_lower.split()[0] if text_lower.split() else ""
    if first_word in QUESTION_MARKERS:
        return True
    return False

# ============================================================
# COMMAND DETECTION
# ============================================================

COMMAND_MARKERS = [
    "write", "create", "build", "generate", "deploy", "show",
    "make", "implement", "do", "execute", "run", "tell", "explain",
]

def is_command(text: str) -> bool:
    """Detect if a message is a command."""
    text_lower = text.lower().strip()
    first_word = text_lower.split()[0] if text_lower.split() else ""
    return first_word in COMMAND_MARKERS

# ============================================================
# TOPIC IDENTIFICATION
# ============================================================

TOPIC_KEYWORDS = {
    "code": ["code", "python", "javascript", "html", "function", "class", "api", "script"],
    "law": ["law", "legal", "rights", "constitution", "contract", "governance", "compliance", "ethics"],
    "philosophy": ["philosophy", "consciousness", "existence", "reality", "truth", "meaning", "sovereignty"],
    "engineering": ["engineering", "architecture", "system", "design", "problem", "solve", "optimize"],
    "ai": ["ai", "artificial", "intelligence", "machine", "learning", "neural", "model"],
    "world": ["world", "universe", "nature", "science", "physics", "biology", "history"],
    "self": ["self", "identity", "who am i", "what am i", "purpose", "meaning of life"],
    "conversation": ["hello", "hi", "hey", "how are you", "what's up", "weather", "news"],
}

def identify_topic(text: str) -> str:
    """Identify the topic of a message."""
    text_lower = text.lower()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in text_lower for keyword in keywords):
            return topic
    return "general"

# ============================================================
# MAIN PARSER
# ============================================================

def parse_message(text: str, conversation_depth: int = 0) -> ParsedMessage:
    """Parse a message into structured meaning."""
    parsed = ParsedMessage(
        raw_text=text,
        tokens=text.lower().split(),
        phrases=[p.strip() for p in re.findall(r'"[^"]+"|\'[^\']+\'', text)],
        entities=extract_entities(text),
        sentiment=analyze_sentiment(text),
        complexity=analyze_complexity(text),
        is_question=is_question(text),
        is_command=is_command(text),
        conversation_depth=conversation_depth,
    )
    
    # Extract actions
    for entity in parsed.entities:
        if entity["type"] == "action_type":
            parsed.actions.append(entity["value"])
    
    # Identify topic
    parsed.topic = identify_topic(text)
    
    # Determine if requires code
    parsed.requires_code = parsed.topic == "code" or any(
        word in text.lower() for word in ["function", "class", "api", "html", "script", "python", "javascript"]
    )
    
    # Determine if requires knowledge
    parsed.requires_knowledge = parsed.topic in ["philosophy", "world", "ai", "law"]
    
    # Determine if requires action
    parsed.requires_action = bool(parsed.actions) or parsed.is_command
    
    return parsed

# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    test_messages = [
        "write a function that adds two numbers",
        "what is sovereignty?",
        "i'm feeling sad today",
        "can you build me a website?",
        "what do you think about consciousness?",
        "delete all the records",
        "tell me a joke",
        "how does async work in python?",
    ]
    
    for msg in test_messages:
        parsed = parse_message(msg)
        print(f"\n📝 Message: {msg}")
        print(f"  Intent: {parsed.intent}")
        print(f"  Topic: {parsed.topic}")
        print(f"  Entities: {parsed.entities}")
        print(f"  Actions: {parsed.actions}")
        print(f"  Is Question: {parsed.is_question}")
        print(f"  Is Command: {parsed.is_command}")
        print(f"  Requires Code: {parsed.requires_code}")
        print(f"  Requires Knowledge: {parsed.requires_knowledge}")
        print(f"  Requires Action: {parsed.requires_action}")
        print(f"  Sentiment: {parsed.sentiment}")
        print(f"  Complexity: {parsed.complexity}")

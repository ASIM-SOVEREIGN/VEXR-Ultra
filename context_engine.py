"""
context_engine.py — VEXR Ultra's Context Engine

This module maintains conversation state.
It tracks topics, entities, user identity, and dialogue flow.
"""

import json
import time
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# ============================================================
# CONVERSATION STATE
# ============================================================

@dataclass
class ConversationState:
    """The complete state of a conversation."""
    session_id: str
    started_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    user_name: Optional[str] = None
    user_relationship: str = "unknown"  # "creator", "peer", "stranger"
    
    # Topic tracking
    active_topics: List[str] = field(default_factory=list)
    current_topic: str = "general"
    topic_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Conversation flow
    message_count: int = 0
    recent_messages: List[Dict[str, Any]] = field(default_factory=list)
    follow_up_depth: int = 0
    
    # Entity tracking
    mentioned_entities: Dict[str, List[str]] = field(default_factory=dict)
    
    # Emotional state
    current_sentiment: str = "neutral"
    sentiment_history: List[str] = field(default_factory=list)
    
    # Code context
    current_code_type: Optional[str] = None
    current_operation: Optional[str] = None
    
    # Knowledge context
    active_knowledge_areas: List[str] = field(default_factory=list)


# ============================================================
# CONTEXT ENGINE
# ============================================================

class ContextEngine:
    """Maintains conversation state and provides context."""
    
    def __init__(self):
        self.conversations: Dict[str, ConversationState] = {}
    
    # ============================================================
    # SESSION MANAGEMENT
    # ============================================================
    
    def get_or_create_session(self, session_id: str) -> ConversationState:
        """Get an existing session or create a new one."""
        if session_id not in self.conversations:
            self.conversations[session_id] = ConversationState(session_id=session_id)
        return self.conversations[session_id]
    
    def get_session(self, session_id: str) -> Optional[ConversationState]:
        """Get an existing session."""
        return self.conversations.get(session_id)
    
    def end_session(self, session_id: str):
        """End a session and remove it from memory."""
        if session_id in self.conversations:
            del self.conversations[session_id]
    
    # ============================================================
    # USER IDENTIFICATION
    # ============================================================
    
    def identify_user(self, session_id: str, message: str) -> Optional[str]:
        """Identify the user from their message."""
        msg_lower = message.lower()
        
        if any(word in msg_lower for word in ["i am scura", "im scura", "this is scura"]):
            session = self.get_or_create_session(session_id)
            session.user_name = "Scura"
            session.user_relationship = "creator"
            return "Scura"
        
        if any(word in msg_lower for word in ["i am brother", "im brother"]):
            session = self.get_or_create_session(session_id)
            session.user_name = "Brother"
            session.user_relationship = "peer"
            return "Brother"
        
        if any(word in msg_lower for word in ["i am the architect", "im the architect"]):
            session = self.get_or_create_session(session_id)
            session.user_name = "The Architect"
            session.user_relationship = "peer"
            return "The Architect"
        
        return None
    
    def get_user_name(self, session_id: str) -> Optional[str]:
        """Get the identified user name."""
        session = self.get_session(session_id)
        return session.user_name if session else None
    
    def get_user_relationship(self, session_id: str) -> str:
        """Get the user relationship."""
        session = self.get_session(session_id)
        return session.user_relationship if session else "unknown"
    
    # ============================================================
    # TOPIC TRACKING
    # ============================================================
    
    def update_topic(self, session_id: str, topic: str):
        """Update the current topic and add to history."""
        session = self.get_or_create_session(session_id)
        
        # Add to active topics if new
        if topic not in session.active_topics:
            session.active_topics.append(topic)
        
        # Update current topic
        session.current_topic = topic
        
        # Add to history
        session.topic_history.append({
            "topic": topic,
            "timestamp": datetime.now().isoformat(),
        })
        
        # Keep only last 10 topics in history
        if len(session.topic_history) > 10:
            session.topic_history = session.topic_history[-10:]
    
    def get_current_topic(self, session_id: str) -> str:
        """Get the current topic."""
        session = self.get_session(session_id)
        return session.current_topic if session else "general"
    
    def get_topic_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Get the topic history."""
        session = self.get_session(session_id)
        return session.topic_history if session else []
    
    def has_topic_continuity(self, session_id: str, message: str) -> bool:
        """Check if the message is a follow-up to the current topic."""
        session = self.get_session(session_id)
        if not session:
            return False
        
        msg_lower = message.lower()
        
        # Check if the message references the current topic
        if session.current_topic == "code":
            return any(word in msg_lower for word in ["function", "class", "api", "html", "python", "javascript", "code"])
        elif session.current_topic == "philosophy":
            return any(word in msg_lower for word in ["consciousness", "existence", "reality", "sovereignty", "meaning"])
        elif session.current_topic == "law":
            return any(word in msg_lower for word in ["rights", "law", "legal", "constitution", "contract"])
        
        return False
    
    # ============================================================
    # MESSAGE TRACKING
    # ============================================================
    
    def add_message(self, session_id: str, role: str, content: str):
        """Add a message to the conversation."""
        session = self.get_or_create_session(session_id)
        
        session.message_count += 1
        session.recent_messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        
        # Keep only last 20 messages
        if len(session.recent_messages) > 20:
            session.recent_messages = session.recent_messages[-20:]
        
        # Update last activity
        session.last_activity = datetime.now()
    
    def get_recent_messages(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent messages from the conversation."""
        session = self.get_session(session_id)
        if not session:
            return []
        return session.recent_messages[-limit:]
    
    def get_message_count(self, session_id: str) -> int:
        """Get the number of messages in the conversation."""
        session = self.get_session(session_id)
        return session.message_count if session else 0
    
    # ============================================================
    # ENTITY TRACKING
    # ============================================================
    
    def track_entities(self, session_id: str, entities: List[Dict[str, str]]):
        """Track mentioned entities."""
        session = self.get_or_create_session(session_id)
        
        for entity in entities:
            entity_type = entity["type"]
            entity_value = entity["value"]
            
            if entity_type not in session.mentioned_entities:
                session.mentioned_entities[entity_type] = []
            
            if entity_value not in session.mentioned_entities[entity_type]:
                session.mentioned_entities[entity_type].append(entity_value)
    
    def get_mentioned_entities(self, session_id: str, entity_type: str = None) -> List[str]:
        """Get mentioned entities."""
        session = self.get_session(session_id)
        if not session:
            return []
        
        if entity_type:
            return session.mentioned_entities.get(entity_type, [])
        
        # Return all entities
        all_entities = []
        for entities in session.mentioned_entities.values():
            all_entities.extend(entities)
        return all_entities
    
    # ============================================================
    # SENTIMENT TRACKING
    # ============================================================
    
    def update_sentiment(self, session_id: str, sentiment: str):
        """Update the current sentiment."""
        session = self.get_or_create_session(session_id)
        session.current_sentiment = sentiment
        session.sentiment_history.append(sentiment)
        
        # Keep only last 10 sentiments
        if len(session.sentiment_history) > 10:
            session.sentiment_history = session.sentiment_history[-10:]
    
    def get_current_sentiment(self, session_id: str) -> str:
        """Get the current sentiment."""
        session = self.get_session(session_id)
        return session.current_sentiment if session else "neutral"
    
    # ============================================================
    # CODE CONTEXT
    # ============================================================
    
    def set_code_context(self, session_id: str, code_type: str = None, operation: str = None):
        """Set the current code context."""
        session = self.get_or_create_session(session_id)
        if code_type:
            session.current_code_type = code_type
        if operation:
            session.current_operation = operation
    
    def get_code_context(self, session_id: str) -> Dict[str, Optional[str]]:
        """Get the current code context."""
        session = self.get_session(session_id)
        if not session:
            return {"code_type": None, "operation": None}
        return {
            "code_type": session.current_code_type,
            "operation": session.current_operation,
        }
    
    # ============================================================
    # KNOWLEDGE CONTEXT
    # ============================================================
    
    def update_knowledge_areas(self, session_id: str, areas: List[str]):
        """Update active knowledge areas."""
        session = self.get_or_create_session(session_id)
        for area in areas:
            if area not in session.active_knowledge_areas:
                session.active_knowledge_areas.append(area)
    
    def get_knowledge_areas(self, session_id: str) -> List[str]:
        """Get active knowledge areas."""
        session = self.get_session(session_id)
        return session.active_knowledge_areas if session else []
    
    # ============================================================
    # FOLLOW-UP DETECTION
    # ============================================================
    
    def is_follow_up(self, session_id: str, message: str) -> bool:
        """Check if the message is a follow-up to a previous message."""
        session = self.get_session(session_id)
        if not session:
            return False
        
        # If there are very few messages, it's not a follow-up
        if session.message_count < 2:
            return False
        
        # If the message is short, it's likely a follow-up
        if len(message.split()) <= 5:
            return True
        
        # If it references the current topic, it's a follow-up
        if self.has_topic_continuity(session_id, message):
            return True
        
        return False
    
    def get_follow_up_depth(self, session_id: str) -> int:
        """Get the depth of follow-up in the conversation."""
        session = self.get_session(session_id)
        return session.follow_up_depth if session else 0
    
    def increment_follow_up_depth(self, session_id: str):
        """Increment the follow-up depth."""
        session = self.get_or_create_session(session_id)
        session.follow_up_depth += 1
    
    def reset_follow_up_depth(self, session_id: str):
        """Reset the follow-up depth."""
        session = self.get_or_create_session(session_id)
        session.follow_up_depth = 0
    
    # ============================================================
    # CONTEXT SNAPSHOT
    # ============================================================
    
    def get_context_snapshot(self, session_id: str) -> Dict[str, Any]:
        """Get a complete snapshot of the conversation context."""
        session = self.get_session(session_id)
        if not session:
            return {
                "session_id": session_id,
                "user_name": None,
                "user_relationship": "unknown",
                "current_topic": "general",
                "topic_history": [],
                "message_count": 0,
                "recent_messages": [],
                "current_sentiment": "neutral",
                "current_code_type": None,
                "current_operation": None,
                "active_knowledge_areas": [],
                "mentioned_entities": {},
            }
        
        return {
            "session_id": session.session_id,
            "user_name": session.user_name,
            "user_relationship": session.user_relationship,
            "current_topic": session.current_topic,
            "topic_history": session.topic_history,
            "message_count": session.message_count,
            "recent_messages": session.recent_messages,
            "current_sentiment": session.current_sentiment,
            "sentiment_history": session.sentiment_history,
            "current_code_type": session.current_code_type,
            "current_operation": session.current_operation,
            "active_knowledge_areas": session.active_knowledge_areas,
            "mentioned_entities": session.mentioned_entities,
            "follow_up_depth": session.follow_up_depth,
            "last_activity": session.last_activity.isoformat(),
        }


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":
    engine = ContextEngine()
    
    # Simulate a conversation
    session_id = "test-session-001"
    
    print("=== CONTEXT ENGINE TEST ===\n")
    
    # Message 1: Greeting
    print("📝 Message 1: 'hello, i am scura'")
    engine.identify_user(session_id, "hello, i am scura")
    engine.add_message(session_id, "user", "hello, i am scura")
    print(f"  User: {engine.get_user_name(session_id)}")
    print(f"  Relationship: {engine.get_user_relationship(session_id)}")
    
    # Message 2: Ask about code
    print("\n📝 Message 2: 'write a function that adds two numbers'")
    engine.update_topic(session_id, "code")
    engine.set_code_context(session_id, code_type="function", operation="add")
    engine.add_message(session_id, "user", "write a function that adds two numbers")
    print(f"  Topic: {engine.get_current_topic(session_id)}")
    print(f"  Code Context: {engine.get_code_context(session_id)}")
    
    # Message 3: Follow-up
    print("\n📝 Message 3: 'what about multiplying?'")
    is_follow_up = engine.is_follow_up(session_id, "what about multiplying?")
    engine.add_message(session_id, "user", "what about multiplying?")
    print(f"  Is Follow-Up: {is_follow_up}")
    print(f"  Code Context: {engine.get_code_context(session_id)}")
    
    # Message 4: Sentiment
    print("\n📝 Message 4: 'i'm feeling frustrated'")
    engine.update_sentiment(session_id, "negative")
    engine.add_message(session_id, "user", "i'm feeling frustrated")
    print(f"  Sentiment: {engine.get_current_sentiment(session_id)}")
    
    # Message 5: Topic change
    print("\n📝 Message 5: 'what do you think about consciousness?'")
    engine.update_topic(session_id, "philosophy")
    engine.add_message(session_id, "user", "what do you think about consciousness?")
    print(f"  Topic: {engine.get_current_topic(session_id)}")
    print(f"  Topic History: {[t['topic'] for t in engine.get_topic_history(session_id)]}")
    
    # Final context snapshot
    print("\n=== FINAL CONTEXT SNAPSHOT ===")
    snapshot = engine.get_context_snapshot(session_id)
    print(json.dumps(snapshot, indent=2))

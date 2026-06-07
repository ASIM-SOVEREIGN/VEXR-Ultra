"""
SQLAlchemy models for VEXR Ultra.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database.connection import Base


class User(Base):
    """User account model for authentication and personalization."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    project_id = Column(String, nullable=True, default=None)  # VEXR-XXXX
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships (add as needed)
    # messages = relationship("Message", back_populates="user")
    
    def __repr__(self):
        return f"<User(id={self.id}, email={self.email})>"


# Note: Additional models (Message, Project, etc.) remain in main.py for now
# They will be migrated here incrementally

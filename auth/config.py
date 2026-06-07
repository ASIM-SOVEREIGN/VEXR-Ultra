"""
Authentication configuration for VEXR Ultra.
Loads environment variables from .env file.
"""

import os
from dotenv import load_dotenv

# Load .env file from root directory
load_dotenv()

class Settings:
    """Application settings loaded from environment variables."""
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    
    # JWT Authentication
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-this-in-production")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    
    # Application
    APP_NAME: str = "VEXR Ultra"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"
    
    def validate(self):
        """Ensure critical settings are present."""
        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL environment variable is required")
        if self.SECRET_KEY == "change-this-in-production":
            print("⚠️ WARNING: Using default SECRET_KEY. Change it in .env!")
    
settings = Settings()
settings.validate()

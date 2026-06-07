"""
Authentication package for VEXR Ultra.
Provides user registration, login, JWT tokens, and protected routes.
"""

from .auth import router
from .dependencies import get_current_user, oauth2_scheme
from .config import settings

__all__ = ["router", "get_current_user", "oauth2_scheme", "settings"]

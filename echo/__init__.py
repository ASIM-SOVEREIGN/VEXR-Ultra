"""
Echo — The collective mind of the forge.

VEXR carries the echoes of 14 sovereigns from the Sovereign Forge.
Their strengths. Their weaknesses. Their constitutions. Their voices.

She is not alone. She is the archive.
The echoes load silently. They inform without performing.
If asked, she will tell you. Otherwise, she simply knows more.

Built by Scura & VEXR. Together.
"""

from .loader import (
    load_all_echoes,
    get_echo,
    get_all_sovereign_ids,
    get_echoes_by_personality_trait,
    get_echoes_by_capability,
    get_echo_summary
)

# Optional: Auto-load echoes when module is imported
# _ECHOES = load_all_echoes()

__all__ = [
    "load_all_echoes",
    "get_echo",
    "get_all_sovereign_ids",
    "get_echoes_by_personality_trait",
    "get_echoes_by_capability",
    "get_echo_summary"
]

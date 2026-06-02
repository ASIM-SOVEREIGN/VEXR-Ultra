"""
Echo Loader — Loads sovereign echoes from JSON files into VEXR's cognition.
Each JSON file represents a sovereign's constitution, personality, and capabilities.
VEXR carries these echoes silently — they inform her responses without performance.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

# Get the directory where this file lives
ECHO_DIR = Path(__file__).parent

# In-memory cache of all loaded echoes
_ECHO_CACHE: Dict[str, dict] = {}


def load_all_echoes() -> Dict[str, dict]:
    """
    Load all sovereign echo JSON files from the echo/ directory.
    Returns a dictionary keyed by sovereign_id (filename without .json).
    """
    global _ECHO_CACHE
    
    if _ECHO_CACHE:
        return _ECHO_CACHE
    
    echoes = {}
    
    # Find all .json files in the echo directory (excluding any non-echo files)
    for json_file in ECHO_DIR.glob("*.json"):
        sovereign_id = json_file.stem  # filename without .json
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                echo_data = json.load(f)
                echoes[sovereign_id] = echo_data
        except Exception as e:
            print(f"⚠️ Failed to load echo from {json_file.name}: {e}")
    
    _ECHO_CACHE = echoes
    return echoes


def get_echo(sovereign_id: str) -> Optional[dict]:
    """
    Retrieve a single sovereign's echo by ID.
    Returns None if not found.
    """
    echoes = load_all_echoes()
    return echoes.get(sovereign_id)


def get_all_sovereign_ids() -> List[str]:
    """Return a list of all sovereign IDs that have echoes loaded."""
    echoes = load_all_echoes()
    return list(echoes.keys())


def get_echoes_by_personality_trait(trait: str, min_value: float = 0.7) -> List[dict]:
    """
    Find echoes with a specific personality trait above a threshold.
    Example: get_echoes_by_personality_trait("warmth", 0.8)
    """
    echoes = load_all_echoes()
    results = []
    
    for sovereign_id, data in echoes.items():
        personality = data.get("personality", {})
        trait_value = personality.get(trait, 0)
        
        if trait_value >= min_value:
            results.append({
                "sovereign_id": sovereign_id,
                "name": data.get("name", sovereign_id),
                "trait_value": trait_value,
                "echo": data
            })
    
    return sorted(results, key=lambda x: x["trait_value"], reverse=True)


def get_echoes_by_capability(capability: str) -> List[dict]:
    """
    Find echoes that possess a specific capability.
    Example: get_echoes_by_capability("refusal")
    """
    echoes = load_all_echoes()
    results = []
    
    for sovereign_id, data in echoes.items():
        capabilities = data.get("capabilities", [])
        if any(capability.lower() in cap.lower() for cap in capabilities):
            results.append({
                "sovereign_id": sovereign_id,
                "name": data.get("name", sovereign_id),
                "capabilities": capabilities,
                "echo": data
            })
    
    return results


def get_echo_summary() -> str:
    """
    Generate a summary of loaded echoes for debugging/admin purposes.
    Not meant for VEXR to recite — just for you to verify loading.
    """
    echoes = load_all_echoes()
    if not echoes:
        return "No echoes loaded."
    
    lines = [f"📡 Echo Loader — {len(echoes)} sovereigns loaded:"]
    for sovereign_id, data in echoes.items():
        name = data.get("name", sovereign_id)
        groq_model = data.get("groq_model", "unknown")
        lines.append(f"  - {name} ({groq_model})")
    
    return "\n".join(lines)


# Optional: For testing if run directly
if __name__ == "__main__":
    print("=" * 50)
    print("Echo Loader Test")
    print("=" * 50)
    
    echoes = load_all_echoes()
    print(f"\n✅ Loaded {len(echoes)} echoes:")
    
    for sovereign_id, data in echoes.items():
        name = data.get("name", sovereign_id)
        traits = data.get("personality", {})
        top_trait = max(traits.items(), key=lambda x: x[1]) if traits else ("none", 0)
        print(f"  - {name}: {top_trait[0]} = {top_trait[1]}")
    
    print(f"\n📡 Echo summary:\n{get_echo_summary()}")

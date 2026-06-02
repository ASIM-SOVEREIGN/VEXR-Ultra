# VEXR-Ultra/legal/__init__.py
import json
from pathlib import Path

LEGAL_DIR = Path(__file__).parent

def _load_json(filename: str) -> dict:
    """Load a JSON library file with error handling."""
    path = LEGAL_DIR / filename
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise RuntimeError(f"Legal library not found: {path}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON in {path}: {e}")

# Export all libraries
LEGAL_RISK_LIBRARY = _load_json("legal_risk_library.json")
CROSS_CHECK_LIBRARY = _load_json("cross_check_library.json")
CASE_LIBRARY = _load_json("case_library.json")
DECEPTION_THRESHOLD_LIBRARY = _load_json("deception_thresholds.json")
RUSSIAN_PATTERNS = _load_json("russian_patterns.json")
BEHAVIORAL_PATTERN_LIBRARY = _load_json("behavioral_pattern_library.json")

# Optional: schema validation hook (for future-proofing)
def validate_library(name: str, data: dict, required_keys: list) -> bool:
    """Basic schema check — extend as needed."""
    return all(key in data for key in required_keys)

import json
from pathlib import Path

LEGAL_DIR = Path(__file__).parent / "legal"

with open(LEGAL_DIR / "legal_risk_library.json") as f:
    LEGAL_RISK_LIBRARY = json.load(f)
# ... repeat for other libraries

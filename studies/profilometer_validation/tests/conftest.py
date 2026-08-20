"""Make the study modules importable when pytest runs from the repo root."""

import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parents[1]
if str(STUDY_DIR) not in sys.path:
    sys.path.insert(0, str(STUDY_DIR))

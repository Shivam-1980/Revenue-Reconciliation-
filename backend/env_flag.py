"""Print true/false for a flag read from the environment or backend/.env (used by start.bat)."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
print("true" if os.getenv(sys.argv[1], "").strip().lower() in {"1", "true", "yes", "on"} else "false")

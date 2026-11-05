"""Load backend/.env (database, secrets) before any module reads the environment.

Variables already set in the real environment take precedence over the file.
"""
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is a pinned dependency; tolerate its absence in tooling
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

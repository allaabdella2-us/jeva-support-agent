"""
SETTINGS FILE

Loads backend/.env into the environment. Import this before
anything reads a setting (support_db reads SUPPORT_DB_PATH and
groq_llm reads GROQ_MODEL when they are imported).

Variables already set in your shell win over the file.
"""
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().with_name(".env")
load_dotenv(ENV_FILE)

"""Shared fixtures. LLM tests load keys from .env.local when run outside Docker."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[1] / ".env.local")

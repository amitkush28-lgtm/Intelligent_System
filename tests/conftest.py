"""
Pytest configuration and shared fixtures.

Sets PYTHONPATH and provides mock settings so tests can import
shared/ and service modules without a live database or Redis.
"""

import os
import sys

# Ensure monorepo root is on sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Set minimal env vars before any imports touch settings
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("FRED_API_KEY", "test-key")
os.environ.setdefault("NEWSDATA_API_KEY", "test-key")
os.environ.setdefault("TWELVE_DATA_API_KEY", "test-key")
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("ENVIRONMENT", "testing")

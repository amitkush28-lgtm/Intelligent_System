"""
Centralized configuration loaded from environment variables.
All services import from here — single source of truth.
"""

import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/intelligence"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    
    # LLM API Keys
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    
    # Data Source API Keys
    FRED_API_KEY: str = ""
    NEWSDATA_API_KEY: str = ""
    TWELVE_DATA_API_KEY: str = ""
    
    # API Configuration
    API_KEY: str = "changeme"  # Simple auth for Phase 1
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    
    # Service URLs (Railway private networking)
    API_URL: str = "http://api:8000"
    
    # LLM Model Configuration
    CLAUDE_SONNET_MODEL: str = "claude-sonnet-4-20250514"
    CLAUDE_HAIKU_MODEL: str = "claude-haiku-4-5-20251001"
    GPT4O_MODEL: str = "gpt-4o"
    
    # Operational
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"
    
    # Confidence capping
    MIN_EVIDENCE_INTEGRITY: float = 0.50
    CONFIDENCE_CAP_MULTIPLIER: float = 0.40  # max pp change = integrity * multiplier * 100
    
    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()

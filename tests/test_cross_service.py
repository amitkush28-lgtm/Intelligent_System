"""
Test cross-service contracts: Redis queue names, env var documentation,
shared model consistency, and Dockerfile correctness.
"""

import os
import re
import pytest
from pathlib import Path

ROOT = Path(__file__).parent.parent


class TestRedisQueueConsistency:
    """
    Verify Redis queue names match between publishers and consumers.

    Expected flow:
      ingestion_complete:    ingestion → agents
      analysis_complete:     agents → feedback
      verification_needed:   ingestion → verification
      verification_complete: verification → agents
      debate_trigger:        feedback → agents
    """

    def _search_files(self, pattern: str, directory: str) -> list:
        """Search Python files in directory for string pattern."""
        matches = []
        service_dir = ROOT / "services" / directory
        for pyfile in service_dir.rglob("*.py"):
            content = pyfile.read_text()
            if pattern in content:
                matches.append(str(pyfile.relative_to(ROOT)))
        return matches

    def test_ingestion_complete_published_by_ingestion(self):
        matches = self._search_files('"ingestion_complete"', "ingestion")
        assert len(matches) > 0, "ingestion must publish 'ingestion_complete'"

    def test_ingestion_complete_consumed_by_agents(self):
        matches = self._search_files('"ingestion_complete"', "agents")
        assert len(matches) > 0, "agents must consume 'ingestion_complete'"

    def test_analysis_complete_published_by_agents(self):
        matches = self._search_files('"analysis_complete"', "agents")
        assert len(matches) > 0, "agents must publish 'analysis_complete'"

    def test_analysis_complete_consumed_by_feedback(self):
        matches = self._search_files('"analysis_complete"', "feedback")
        assert len(matches) > 0, "feedback must consume 'analysis_complete'"

    def test_verification_needed_published_by_ingestion(self):
        matches = self._search_files('"verification_needed"', "ingestion")
        assert len(matches) > 0, "ingestion must publish 'verification_needed'"

    def test_verification_needed_consumed_by_verification(self):
        matches = self._search_files('"verification_needed"', "verification")
        assert len(matches) > 0, "verification must consume 'verification_needed'"

    def test_verification_complete_published_by_verification(self):
        matches = self._search_files('"verification_complete"', "verification")
        assert len(matches) > 0, "verification must publish 'verification_complete'"

    def test_verification_complete_consumed_by_agents(self):
        matches = self._search_files('"verification_complete"', "agents")
        assert len(matches) > 0, "agents must consume 'verification_complete'"

    def test_debate_trigger_published_by_feedback(self):
        matches = self._search_files('"debate_trigger"', "feedback")
        assert len(matches) > 0, "feedback must publish 'debate_trigger'"


class TestEnvironmentVariableDocumentation:
    """Verify every env var used in code is documented in .env.example."""

    @pytest.fixture(scope="class")
    def env_example_content(self):
        return (ROOT / ".env.example").read_text()

    REQUIRED_VARS = [
        "DATABASE_URL",
        "REDIS_URL",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "FRED_API_KEY",
        "NEWSDATA_API_KEY",
        "TWELVE_DATA_API_KEY",
        "API_KEY",
        "LOG_LEVEL",
        "ENVIRONMENT",
        "NEXT_PUBLIC_API_URL",
        "NEXT_PUBLIC_API_KEY",
    ]

    def test_all_vars_documented(self, env_example_content):
        for var in self.REQUIRED_VARS:
            assert var in env_example_content, (
                f"Environment variable {var} is used in code "
                f"but not documented in .env.example"
            )


class TestDockerfileConsistency:
    """Verify Dockerfiles are correctly structured."""

    PYTHON_SERVICES = ["api", "ingestion", "verification", "agents", "feedback", "signals"]

    def test_all_python_services_have_dockerfiles(self):
        for svc in self.PYTHON_SERVICES:
            df = ROOT / "services" / svc / "Dockerfile"
            assert df.exists(), f"Missing Dockerfile for {svc}"

    def test_frontend_has_dockerfile(self):
        assert (ROOT / "services" / "frontend" / "Dockerfile").exists()

    def test_python_services_copy_shared(self):
        for svc in self.PYTHON_SERVICES:
            content = (ROOT / "services" / svc / "Dockerfile").read_text()
            assert "COPY shared/" in content, (
                f"{svc} Dockerfile must COPY shared/ directory"
            )

    def test_python_services_copy_init(self):
        for svc in self.PYTHON_SERVICES:
            content = (ROOT / "services" / svc / "Dockerfile").read_text()
            assert "services/__init__.py" in content, (
                f"{svc} Dockerfile must COPY services/__init__.py"
            )

    def test_python_services_set_pythonpath(self):
        for svc in self.PYTHON_SERVICES:
            content = (ROOT / "services" / svc / "Dockerfile").read_text()
            assert "PYTHONPATH=/app" in content, (
                f"{svc} Dockerfile must set PYTHONPATH=/app"
            )

    def test_api_copies_migrations(self):
        content = (ROOT / "services" / "api" / "Dockerfile").read_text()
        assert "migrations/" in content, "API Dockerfile must copy migrations"
        assert "alembic.ini" in content, "API Dockerfile must copy alembic.ini"

    def test_ingestion_downloads_spacy(self):
        content = (ROOT / "services" / "ingestion" / "Dockerfile").read_text()
        assert "spacy download" in content, "Ingestion Dockerfile must download spaCy model"

    def test_frontend_standalone_output(self):
        config = (ROOT / "services" / "frontend" / "next.config.js").read_text()
        assert "standalone" in config, "next.config.js must set output: 'standalone'"


class TestDockerComposeConsistency:
    """Verify docker-compose.yml is complete and correct."""

    @pytest.fixture(scope="class")
    def compose_content(self):
        return (ROOT / "docker-compose.yml").read_text()

    EXPECTED_SERVICES = [
        "postgres", "redis",
        "api", "frontend", "ingestion",
        "verification", "agents", "feedback", "signals",
    ]

    def test_all_services_listed(self, compose_content):
        for svc in self.EXPECTED_SERVICES:
            pattern = rf"^\s+{svc}:"
            assert re.search(pattern, compose_content, re.MULTILINE), (
                f"Service '{svc}' not found in docker-compose.yml"
            )

    def test_frontend_has_api_key(self, compose_content):
        assert "NEXT_PUBLIC_API_KEY" in compose_content, (
            "Frontend service must have NEXT_PUBLIC_API_KEY env var"
        )

    def test_frontend_has_api_url(self, compose_content):
        assert "NEXT_PUBLIC_API_URL" in compose_content, (
            "Frontend service must have NEXT_PUBLIC_API_URL env var"
        )

    def test_build_context_is_root(self, compose_content):
        """All services must use monorepo root as build context."""
        # Every 'context:' line should be '.'
        contexts = re.findall(r"context:\s*(.+)", compose_content)
        for ctx in contexts:
            assert ctx.strip() == ".", f"Build context must be '.' (monorepo root), got '{ctx.strip()}'"


class TestRailwayToml:
    """Verify railway.toml configuration."""

    @pytest.fixture(scope="class")
    def toml_content(self):
        return (ROOT / "railway.toml").read_text()

    def test_all_services_listed(self, toml_content):
        expected = ["api", "frontend", "ingestion", "verification", "agents", "feedback", "signals"]
        for svc in expected:
            assert f'name = "{svc}"' in toml_content, (
                f"Service '{svc}' not found in railway.toml"
            )

    def test_cron_schedules(self, toml_content):
        assert '0 */4 * * *' in toml_content, "Ingestion cron should be every 4 hours"
        assert '0 6 * * *' in toml_content, "Signals cron should be daily at 06:00 UTC"


class TestSharedModelUsage:
    """Verify that all model classes used in services actually exist in shared/models.py."""

    def test_all_imported_models_exist(self):
        from shared import models
        model_names = {
            name for name in dir(models)
            if not name.startswith("_") and hasattr(getattr(models, name), "__tablename__")
        }
        expected = {
            "Prediction", "ConfidenceTrail", "Note", "Event",
            "Actor", "Relationship",
            "Claim", "SourceReliability",
            "CalibrationScore", "AgentPrompt", "Debate",
            "BaseRateClass", "WeakSignal", "DecisionMapping",
        }
        assert expected.issubset(model_names), (
            f"Missing models: {expected - model_names}"
        )

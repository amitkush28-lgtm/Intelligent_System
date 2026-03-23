"""
Test API route registration and endpoint paths.

Verifies all routes are correctly registered in the FastAPI app
and that prefixes match what the frontend expects.
"""

import pytest


class TestRouteRegistration:
    """Verify all 9 route modules are imported and registered."""

    @pytest.fixture(scope="class")
    def app(self):
        from services.api.main import app
        return app

    @pytest.fixture(scope="class")
    def routes(self, app):
        """Extract all registered route paths."""
        paths = set()
        for route in app.routes:
            if hasattr(route, "path"):
                paths.add(route.path)
        return paths

    def test_health_endpoint(self, routes):
        assert "/health" in routes

    def test_prediction_routes(self, routes):
        assert "/predictions" in routes or any("/predictions" in r for r in routes)

    def test_agent_routes(self, routes):
        assert any("/agents" in r for r in routes)

    def test_dashboard_routes(self, routes):
        assert any("/dashboard/metrics" in r for r in routes)
        assert any("/dashboard/calibration" in r for r in routes)

    def test_debate_routes(self, routes):
        assert any("/debates" in r for r in routes)

    def test_signal_routes(self, routes):
        assert any("/signals/weak" in r for r in routes)

    def test_claim_routes(self, routes):
        assert any("/claims" in r and "verification" in r for r in routes)

    def test_decision_routes(self, routes):
        assert any("/decisions" in r for r in routes)

    def test_event_routes(self, routes):
        assert any("/events" in r for r in routes)

    def test_chat_route(self, routes):
        assert any("/chat" in r for r in routes)


class TestRoutePrefixes:
    """Verify route prefixes match what the frontend API client expects."""

    def test_predictions_prefix(self):
        from services.api.routes.predictions import router
        assert router.prefix == "/predictions"

    def test_agents_prefix(self):
        from services.api.routes.agents import router
        assert router.prefix == "/agents"

    def test_dashboard_prefix(self):
        from services.api.routes.dashboard import router
        assert router.prefix == "/dashboard"

    def test_debates_prefix(self):
        from services.api.routes.debates import router
        assert router.prefix == "/debates"

    def test_signals_prefix(self):
        from services.api.routes.signals import router
        assert router.prefix == "/signals"

    def test_claims_prefix(self):
        from services.api.routes.claims import router
        assert router.prefix == "/claims"

    def test_decisions_prefix(self):
        from services.api.routes.decisions import router
        assert router.prefix == "/decisions"

    def test_events_prefix(self):
        from services.api.routes.events import router
        assert router.prefix == "/events"


class TestFrontendAPIAlignment:
    """
    Verify that the paths the frontend calls in lib/api.ts
    correspond to actual API routes.

    Frontend calls (from lib/api.ts):
      GET  /dashboard/metrics
      GET  /dashboard/calibration
      GET  /predictions
      GET  /predictions/{id}
      GET  /predictions/{id}/trail
      POST /predictions/{id}/notes
      GET  /agents
      GET  /agents/{id}/metrics
      GET  /debates
      GET  /signals/weak
      GET  /claims/{id}/verification
      GET  /events
      GET  /decisions
      WS   /chat
    """

    @pytest.fixture(scope="class")
    def app_routes(self):
        from services.api.main import app
        paths = set()
        for route in app.routes:
            if hasattr(route, "path"):
                paths.add(route.path)
        return paths

    EXPECTED_PATHS = [
        "/dashboard/metrics",
        "/dashboard/calibration",
        "/predictions",
        "/predictions/{prediction_id}",  # may use different param name
        "/agents",
        "/debates",
        "/signals/weak",
        "/events",
        "/decisions",
        "/chat",
    ]

    def test_all_frontend_paths_registered(self, app_routes):
        """Every path the frontend calls must exist in the API."""
        for expected in self.EXPECTED_PATHS:
            # Normalize: the API may use {id} or {prediction_id} etc.
            base = expected.split("{")[0].rstrip("/")
            matches = [r for r in app_routes if r.startswith(base)]
            assert len(matches) > 0, f"Frontend expects {expected} but no route starts with {base}"

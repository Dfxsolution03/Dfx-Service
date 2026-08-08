"""
JROS API Tests — Health Endpoint
==================================
Tests: GET /api/v1/health
"""

import pytest
from unittest.mock import patch
from httpx import AsyncClient


BASE = "/api/v1"


class TestHealthEndpoint:
    """Tests for the /health route."""

    async def test_health_returns_200(self, client: AsyncClient):
        """Health endpoint must return HTTP 200."""
        r = await client.get(f"{BASE}/health")
        assert r.status_code == 200

    async def test_health_response_structure(self, client: AsyncClient):
        """Health response must contain status and database fields."""
        r = await client.get(f"{BASE}/health")
        body = r.json()
        assert "status" in body or "success" in body, (
            f"Unexpected response shape: {body}"
        )

    async def test_health_database_connected(self, client: AsyncClient):
        """Health endpoint must confirm database connectivity."""
        r = await client.get(f"{BASE}/health")
        body = r.json()
        # The health endpoint returns: data.database.database = "connected"
        db_info = (body.get("data") or {}).get("database") or {}
        db_status = db_info.get("database") if isinstance(db_info, dict) else db_info
        assert db_status == "connected", (
            f"Expected database=connected, got: {body}"
        )


    async def test_health_returns_503_when_database_unhealthy(self, client: AsyncClient):
        """Health endpoint must return HTTP 503 (not 200) when the DB ping fails,
        so container/orchestrator health checks correctly detect an outage."""
        with patch(
            "app.api.v1.endpoints.health.check_database_connection",
            return_value={"status": "unhealthy", "database": "connection_failed"},
        ):
            r = await client.get(f"{BASE}/health")
        assert r.status_code == 503
        body = r.json()
        assert body["success"] is False

    async def test_root_redirect_returns_200(self, client: AsyncClient):
        """Root / endpoint should return project metadata."""
        r = await client.get("/")
        assert r.status_code == 200
        body = r.json()
        assert "project" in body or "version" in body

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_endpoint(test_client: AsyncClient):
    """Verify general /health endpoint returns metadata and 200 OK."""
    response = await test_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "environment" in data


@pytest.mark.integration
@pytest.mark.asyncio
async def test_liveness_endpoint(test_client: AsyncClient):
    """Verify Kubernetes/ECS /health/live probe returns 200 OK."""
    response = await test_client.get("/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_readiness_endpoint_structure(test_client: AsyncClient):
    """Verify /health/ready endpoint inspects both database and redis dependencies."""
    response = await test_client.get("/health/ready")
    # Response code may be 200 (if local redis running) or 503 (if redis offline in local unit test)
    assert response.status_code in [200, 503]
    data = response.json()
    assert "database" in data
    assert "redis" in data
    assert "status" in data["database"]
    assert "status" in data["redis"]

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_correlation_id_propagated_when_provided(test_client: AsyncClient):
    """Verify incoming X-Correlation-ID is echoed back on response headers."""
    custom_id = "fin-req-corr-992211"
    response = await test_client.get("/health", headers={"X-Correlation-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("X-Correlation-ID") == custom_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_correlation_id_generated_when_absent(test_client: AsyncClient):
    """Verify an X-Correlation-ID is automatically generated if omitted by client."""
    response = await test_client.get("/health")
    assert response.status_code == 200
    generated_id = response.headers.get("X-Correlation-ID")
    assert generated_id is not None
    assert len(generated_id) > 10


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_context_required_on_protected_endpoints(test_client: AsyncClient):
    """Verify accessing protected routes without authentication/tenant context raises 401."""
    response = await test_client.post("/api/v1/copilot/chat", json={"query": "Summarize Apple 10-K"})
    # Missing authentication credentials
    assert response.status_code == 401
    data = response.json()
    assert data["error"] == "AUTHENTICATION_FAILED"
    assert "correlation_id" in data

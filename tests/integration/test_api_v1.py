import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_copilot_chat_endpoint_with_tenant(test_client: AsyncClient):
    """Verify copilot chat route with tenant context returns valid response."""
    response = await test_client.post(
        "/api/v1/copilot/chat",
        headers={"X-Tenant-ID": "tenant-test-uuid-123"},
        json={"query": "Analyze Apple Q3 10-Q revenue and margin performance", "tickers": ["AAPL"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert "thread_id" in data
    assert data["cached"] is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_research_search_endpoint(test_client: AsyncClient):
    """Verify financial filing search route returns valid response format."""
    response = await test_client.post(
        "/api/v1/research/search",
        headers={"X-Tenant-ID": "tenant-test-uuid-123"},
        json={"query": "capital expenditures artificial intelligence", "top_k": 5},
    )
    assert response.status_code == 200
    data = response.json()
    assert "total_hits" in data
    assert "results" in data


@pytest.mark.integration
@pytest.mark.asyncio
async def test_risk_var_endpoint(test_client: AsyncClient):
    """Verify quantitative VaR calculation route computes metrics."""
    response = await test_client.post(
        "/api/v1/risk/var",
        headers={"X-Tenant-ID": "tenant-test-uuid-123"},
        json={
            "positions": [
                {"ticker": "AAPL", "market_value": 5000000.0, "weight": 0.5},
                {"ticker": "MSFT", "market_value": 5000000.0, "weight": 0.5},
            ]
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_market_value"] == 10000000.0
    assert data["var_daily_pct"] > 0
    assert data["var_amount_usd"] > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hitl_tasks_endpoint(test_client: AsyncClient):
    """Verify HITL tasks listing endpoint returns list."""
    response = await test_client.get("/api/v1/hitl/tasks", headers={"X-Tenant-ID": "tenant-test-uuid-123"})
    assert response.status_code == 200
    assert isinstance(response.json(), list)

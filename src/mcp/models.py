from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

# ==============================================================================
# Security & MCP Infrastructure Models
# ==============================================================================

class ToolSecurityContext(BaseModel):
    """Authenticated context passed into every MCP tool invocation."""
    tenant_id: str = Field(..., description="Authenticated tenant ID")
    user_id: str = Field(..., description="Authenticated user ID")
    roles: list[str] = Field(default_factory=list, description="Assigned enterprise RBAC roles")
    permissions: list[str] = Field(default_factory=list, description="Granted granular permissions")
    agent_type: str | None = Field(default=None, description="Calling agent type (e.g. 'research_agent')")
    request_id: str = Field(..., description="Tracing request correlation ID")


class ToolDefinition(BaseModel):
    """Tool metadata and schema registered with MCP Gateway."""
    name: str
    description: str
    category: str  # "market", "research", "portfolio"
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    required_permission: str
    allowed_roles: list[str] = Field(default_factory=lambda: ["ANALYST", "RISK_MANAGER", "ADVISOR", "ADMIN"])


class ToolResult(BaseModel):
    """Standardized result envelope returned by MCP tools."""
    tool_name: str
    status: str  # "SUCCESS", "FAILED"
    data: dict[str, Any] | list[Any] | None = None
    execution_time_ms: float
    error: str | None = None


# ==============================================================================
# 1. Market Data Server Schemas
# ==============================================================================

class GetStockPriceInput(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10, description="Equities ticker symbol (e.g. AAPL)")
    as_of_date: date | None = Field(default=None, description="Optional pricing date")


class StockPriceOutput(BaseModel):
    ticker: str
    price: float
    currency: str = "USD"
    timestamp: datetime
    source: str = "MARKET_FEED_REALTIME"


class HistoricalPricePoint(BaseModel):
    date: str
    close: float
    volume: int


class GetHistoricalPriceInput(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    start_date: str = Field(..., description="ISO 8601 start date (YYYY-MM-DD)")
    end_date: str = Field(..., description="ISO 8601 end date (YYYY-MM-DD)")
    interval: str = Field(default="1d", pattern="^(1d|1wk|1mo)$")


class HistoricalPriceOutput(BaseModel):
    ticker: str
    prices: list[HistoricalPricePoint]
    count: int


class GetMarketCapInput(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)


class MarketCapOutput(BaseModel):
    ticker: str
    market_cap_usd: float
    shares_outstanding: int
    enterprise_value_usd: float


class GetVolatilityInput(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    lookback_days: int = Field(default=30, ge=1, le=365)


class VolatilityOutput(BaseModel):
    ticker: str
    annualized_volatility: float
    lookback_days: int
    implied_volatility: float | None = None


# ==============================================================================
# 2. Research Server Schemas
# ==============================================================================

class SearchResearchInput(BaseModel):
    query: str = Field(..., min_length=2, max_length=500, description="Research query or keywords")
    limit: int = Field(default=5, ge=1, le=50)
    category: str = Field(default="all")


class ResearchReportItem(BaseModel):
    report_id: str
    title: str
    ticker: str | None = None
    author: str
    published_date: str
    summary: str


class SearchResearchOutput(BaseModel):
    results: list[ResearchReportItem]
    total_found: int


class GetCompanyReportInput(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    fiscal_year: int = Field(..., ge=2000, le=2050)


class CompanyReportOutput(BaseModel):
    ticker: str
    fiscal_year: int
    report_type: str = "ANNUAL_10K"
    executive_summary: str
    financial_highlights: dict[str, Any]


class SearchEarningsInput(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    quarter: str = Field(..., pattern="^(Q1|Q2|Q3|Q4)$")
    year: int = Field(..., ge=2000, le=2050)


class EarningsOutput(BaseModel):
    ticker: str
    quarter: str
    year: int
    eps_actual: float
    eps_estimate: float
    revenue_billions: float
    management_guidance: str
    key_quotes: list[str]


# ==============================================================================
# 3. Portfolio Server Schemas
# ==============================================================================

class GetPortfolioInput(BaseModel):
    portfolio_id: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)


class PortfolioOutput(BaseModel):
    portfolio_id: str
    tenant_id: str
    portfolio_name: str
    total_aum: float
    currency: str = "USD"
    holdings_count: int


class GetPositionInput(BaseModel):
    portfolio_id: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)
    ticker: str = Field(..., min_length=1, max_length=10)


class PositionOutput(BaseModel):
    portfolio_id: str
    tenant_id: str
    ticker: str
    shares: float
    market_value: float
    weight_percentage: float
    unrealized_pnl: float


class CalculateExposureInput(BaseModel):
    portfolio_id: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)
    asset_class: str = Field(default="all")


class ExposureOutput(BaseModel):
    portfolio_id: str
    tenant_id: str
    equity_exposure: float
    fixed_income_exposure: float
    cash_exposure: float
    net_leverage: float


class CalculateSectorExposureInput(BaseModel):
    portfolio_id: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)


class SectorExposureOutput(BaseModel):
    portfolio_id: str
    tenant_id: str
    sector_breakdown: dict[str, float]
    top_sector: str

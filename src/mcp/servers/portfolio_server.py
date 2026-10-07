from typing import Any

from ...domain.exceptions import TenantIsolationViolationException
from ..models import (
    CalculateExposureInput,
    CalculateSectorExposureInput,
    ExposureOutput,
    GetPortfolioInput,
    GetPositionInput,
    PortfolioOutput,
    PositionOutput,
    SectorExposureOutput,
    ToolDefinition,
    ToolSecurityContext,
)
from .base import BaseMCPServer


class PortfolioServer(BaseMCPServer):
    """
    Portfolio MCP Server.
    Provides institutional portfolio diagnostics, position valuations, asset-class exposures,
    and sector concentration analysis strictly scoped to tenant boundaries.
    """

    def __init__(self):
        super().__init__(server_name="portfolio_server")

    def _register_tools(self) -> None:
        # 1. get_portfolio
        self.register_tool(
            definition=ToolDefinition(
                name="get_portfolio",
                description="Retrieves portfolio summary, total AUM, and holdings count for a tenant.",
                category="portfolio",
                input_model=GetPortfolioInput,
                output_model=PortfolioOutput,
                required_permission="tools:execute:portfolio",
                allowed_roles=["ANALYST", "RISK_MANAGER", "ADVISOR", "ADMIN"],
            ),
            handler=self._handle_get_portfolio,
        )

        # 2. get_position
        self.register_tool(
            definition=ToolDefinition(
                name="get_position",
                description="Retrieves single asset position shares, market value, and portfolio weight.",
                category="portfolio",
                input_model=GetPositionInput,
                output_model=PositionOutput,
                required_permission="tools:execute:portfolio",
                allowed_roles=["ANALYST", "RISK_MANAGER", "ADVISOR", "ADMIN"],
            ),
            handler=self._handle_get_position,
        )

        # 3. calculate_exposure
        self.register_tool(
            definition=ToolDefinition(
                name="calculate_exposure",
                description="Calculates asset-class net exposures (equities, fixed income, cash) and portfolio leverage.",
                category="portfolio",
                input_model=CalculateExposureInput,
                output_model=ExposureOutput,
                required_permission="tools:execute:portfolio",
                allowed_roles=["ANALYST", "RISK_MANAGER", "ADVISOR", "ADMIN"],
            ),
            handler=self._handle_calculate_exposure,
        )

        # 4. calculate_sector_exposure
        self.register_tool(
            definition=ToolDefinition(
                name="calculate_sector_exposure",
                description="Calculates sector allocation breakdown and identifies concentration risks.",
                category="portfolio",
                input_model=CalculateSectorExposureInput,
                output_model=SectorExposureOutput,
                required_permission="tools:execute:portfolio",
                allowed_roles=["ANALYST", "RISK_MANAGER", "ADVISOR", "ADMIN"],
            ),
            handler=self._handle_calculate_sector_exposure,
        )

    def _verify_tenant(self, args: dict[str, Any], context: ToolSecurityContext) -> None:
        """Enforces tenant isolation boundary at the portfolio server layer."""
        if args["tenant_id"] != context.tenant_id:
            raise TenantIsolationViolationException(
                f"Portfolio isolation error: Caller tenant '{context.tenant_id}' cannot query portfolio of '{args['tenant_id']}'."
            )

    async def _handle_get_portfolio(self, args: dict[str, Any], context: ToolSecurityContext) -> dict[str, Any]:
        self._verify_tenant(args, context)
        pid = args["portfolio_id"]
        tid = args["tenant_id"]

        return {
            "portfolio_id": pid,
            "tenant_id": tid,
            "portfolio_name": f"{tid.title()} Flagship Global Growth",
            "total_aum": 142_500_000.0,
            "currency": "USD",
            "holdings_count": 48,
        }

    async def _handle_get_position(self, args: dict[str, Any], context: ToolSecurityContext) -> dict[str, Any]:
        self._verify_tenant(args, context)
        pid = args["portfolio_id"]
        tid = args["tenant_id"]
        ticker = args["ticker"].upper()

        return {
            "portfolio_id": pid,
            "tenant_id": tid,
            "ticker": ticker,
            "shares": 25000.0,
            "market_value": 5_612_500.0,
            "weight_percentage": 3.94,
            "unrealized_pnl": 842_000.0,
        }

    async def _handle_calculate_exposure(self, args: dict[str, Any], context: ToolSecurityContext) -> dict[str, Any]:
        self._verify_tenant(args, context)
        pid = args["portfolio_id"]
        tid = args["tenant_id"]

        return {
            "portfolio_id": pid,
            "tenant_id": tid,
            "equity_exposure": 82.5,
            "fixed_income_exposure": 12.0,
            "cash_exposure": 5.5,
            "net_leverage": 1.0,
        }

    async def _handle_calculate_sector_exposure(self, args: dict[str, Any], context: ToolSecurityContext) -> dict[str, Any]:
        self._verify_tenant(args, context)
        pid = args["portfolio_id"]
        tid = args["tenant_id"]

        return {
            "portfolio_id": pid,
            "tenant_id": tid,
            "sector_breakdown": {
                "Information Technology": 34.2,
                "Financials": 18.5,
                "Healthcare": 14.8,
                "Consumer Discretionary": 12.1,
                "Industrials": 8.4,
                "Cash & Equivalents": 5.5,
                "Energy": 4.2,
                "Other": 2.3,
            },
            "top_sector": "Information Technology",
        }

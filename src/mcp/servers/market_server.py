from datetime import datetime
from typing import Any

from ..models import (
    GetHistoricalPriceInput,
    GetMarketCapInput,
    GetStockPriceInput,
    GetVolatilityInput,
    HistoricalPriceOutput,
    HistoricalPricePoint,
    MarketCapOutput,
    StockPriceOutput,
    ToolDefinition,
    ToolSecurityContext,
    VolatilityOutput,
)
from .base import BaseMCPServer


class MarketDataServer(BaseMCPServer):
    """
    Market Data MCP Server.
    Provides equities pricing, historical trade series, market capitalization,
    and annualized volatility metrics.
    """

    KNOWN_PRICES: dict[str, float] = {
        "AAPL": 224.50,
        "MSFT": 448.20,
        "NVDA": 138.75,
        "AMZN": 186.40,
        "GOOGL": 178.90,
        "META": 585.30,
        "TSLA": 254.10,
        "JPM": 218.60,
        "GS": 492.10,
        "BLK": 885.00,
    }

    def __init__(self):
        super().__init__(server_name="market_data_server")

    def _register_tools(self) -> None:
        # 1. get_stock_price
        self.register_tool(
            definition=ToolDefinition(
                name="get_stock_price",
                description="Retrieves current market price and quote metadata for a public ticker symbol.",
                category="market",
                input_model=GetStockPriceInput,
                output_model=StockPriceOutput,
                required_permission="tools:execute:market",
                allowed_roles=["ANALYST", "RISK_MANAGER", "ADVISOR", "ADMIN", "READ_ONLY_USER"],
            ),
            handler=self._handle_get_stock_price,
        )

        # 2. get_historical_price
        self.register_tool(
            definition=ToolDefinition(
                name="get_historical_price",
                description="Retrieves historical daily trade bars and volume between date boundaries.",
                category="market",
                input_model=GetHistoricalPriceInput,
                output_model=HistoricalPriceOutput,
                required_permission="tools:execute:market",
                allowed_roles=["ANALYST", "RISK_MANAGER", "ADVISOR", "ADMIN"],
            ),
            handler=self._handle_get_historical_price,
        )

        # 3. get_market_cap
        self.register_tool(
            definition=ToolDefinition(
                name="get_market_cap",
                description="Retrieves equity market capitalization and enterprise value.",
                category="market",
                input_model=GetMarketCapInput,
                output_model=MarketCapOutput,
                required_permission="tools:execute:market",
                allowed_roles=["ANALYST", "RISK_MANAGER", "ADVISOR", "ADMIN"],
            ),
            handler=self._handle_get_market_cap,
        )

        # 4. get_volatility
        self.register_tool(
            definition=ToolDefinition(
                name="get_volatility",
                description="Computes annualized historical trading volatility and implied options volatility.",
                category="market",
                input_model=GetVolatilityInput,
                output_model=VolatilityOutput,
                required_permission="tools:execute:market",
                allowed_roles=["ANALYST", "RISK_MANAGER", "ADMIN"],
            ),
            handler=self._handle_get_volatility,
        )

    async def _handle_get_stock_price(self, args: dict[str, Any], context: ToolSecurityContext) -> dict[str, Any]:
        ticker = args["ticker"].upper()
        price = self.KNOWN_PRICES.get(ticker, 150.0)
        return {
            "ticker": ticker,
            "price": price,
            "currency": "USD",
            "timestamp": datetime.utcnow().isoformat(),
            "source": "MARKET_FEED_REALTIME",
        }

    async def _handle_get_historical_price(self, args: dict[str, Any], context: ToolSecurityContext) -> dict[str, Any]:
        ticker = args["ticker"].upper()
        base = self.KNOWN_PRICES.get(ticker, 150.0)
        # Generate 5 representative trading points
        points = [
            HistoricalPricePoint(date="2026-09-01", close=round(base * 0.96, 2), volume=42000000),
            HistoricalPricePoint(date="2026-09-08", close=round(base * 0.98, 2), volume=38500000),
            HistoricalPricePoint(date="2026-09-15", close=round(base * 1.01, 2), volume=51200000),
            HistoricalPricePoint(date="2026-09-22", close=round(base * 0.99, 2), volume=36400000),
            HistoricalPricePoint(date="2026-09-29", close=round(base, 2), volume=44100000),
        ]
        return {
            "ticker": ticker,
            "prices": [p.model_dump() for p in points],
            "count": len(points),
        }

    async def _handle_get_market_cap(self, args: dict[str, Any], context: ToolSecurityContext) -> dict[str, Any]:
        ticker = args["ticker"].upper()
        price = self.KNOWN_PRICES.get(ticker, 150.0)
        # Approximate institutional share count (15B shares for mega-caps)
        shares = 15_400_000_000 if ticker in ["AAPL", "MSFT", "NVDA"] else 3_200_000_000
        mcap = round(price * shares, 2)
        ev = round(mcap * 1.04, 2)
        return {
            "ticker": ticker,
            "market_cap_usd": mcap,
            "shares_outstanding": shares,
            "enterprise_value_usd": ev,
        }

    async def _handle_get_volatility(self, args: dict[str, Any], context: ToolSecurityContext) -> dict[str, Any]:
        ticker = args["ticker"].upper()
        lookback = args.get("lookback_days", 30)
        # Deterministic stylized annualized volatility
        vol_seed = (hash(ticker) % 15) + 16  # 16% to 31%
        ann_vol = round(vol_seed / 100.0, 4)
        implied_vol = round(ann_vol * 1.05, 4)
        return {
            "ticker": ticker,
            "annualized_volatility": ann_vol,
            "lookback_days": lookback,
            "implied_volatility": implied_vol,
        }

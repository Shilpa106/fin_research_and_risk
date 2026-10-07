from typing import Any

from ..models import (
    CompanyReportOutput,
    EarningsOutput,
    GetCompanyReportInput,
    ResearchReportItem,
    SearchEarningsInput,
    SearchResearchInput,
    SearchResearchOutput,
    ToolDefinition,
    ToolSecurityContext,
)
from .base import BaseMCPServer


class ResearchServer(BaseMCPServer):
    """
    Research MCP Server.
    Provides fundamental equity research, SEC company reports, and earnings call transcripts.
    """

    def __init__(self):
        super().__init__(server_name="research_server")

    def _register_tools(self) -> None:
        # 1. search_research
        self.register_tool(
            definition=ToolDefinition(
                name="search_research",
                description="Searches institutional equity research notes, macro analyses, and valuation models.",
                category="research",
                input_model=SearchResearchInput,
                output_model=SearchResearchOutput,
                required_permission="tools:execute:research",
                allowed_roles=["ANALYST", "RISK_MANAGER", "ADVISOR", "ADMIN", "READ_ONLY_USER"],
            ),
            handler=self._handle_search_research,
        )

        # 2. get_company_report
        self.register_tool(
            definition=ToolDefinition(
                name="get_company_report",
                description="Retrieves structured 10-K company annual report data and financial highlights.",
                category="research",
                input_model=GetCompanyReportInput,
                output_model=CompanyReportOutput,
                required_permission="tools:execute:research",
                allowed_roles=["ANALYST", "RISK_MANAGER", "ADVISOR", "ADMIN"],
            ),
            handler=self._handle_get_company_report,
        )

        # 3. search_earnings
        self.register_tool(
            definition=ToolDefinition(
                name="search_earnings",
                description="Searches quarterly earnings transcripts, actual vs estimate EPS, and management guidance.",
                category="research",
                input_model=SearchEarningsInput,
                output_model=EarningsOutput,
                required_permission="tools:execute:research",
                allowed_roles=["ANALYST", "RISK_MANAGER", "ADVISOR", "ADMIN"],
            ),
            handler=self._handle_search_earnings,
        )

    async def _handle_search_research(self, args: dict[str, Any], context: ToolSecurityContext) -> dict[str, Any]:
        query = args["query"]
        limit = args.get("limit", 5)

        items = [
            ResearchReportItem(
                report_id="rep-sec-2026-01",
                title=f"Institutional Equity Outlook: {query.title()}",
                ticker="AAPL" if "apple" in query.lower() or "aapl" in query.lower() else "MSFT",
                author="Global Equity Strategy Group",
                published_date="2026-09-15",
                summary="Overweight recommendation based on recurring software services expansion and operating leverage.",
            ),
            ResearchReportItem(
                report_id="rep-macro-2026-02",
                title="Monetary Policy & Capital Expenditure Cycles",
                ticker=None,
                author="Macroeconomic Insights",
                published_date="2026-08-30",
                summary="Enterprise artificial intelligence infrastructure spending expected to sustain 18% YoY growth.",
            ),
        ]
        return {
            "results": [item.model_dump() for item in items[:limit]],
            "total_found": len(items),
        }

    async def _handle_get_company_report(self, args: dict[str, Any], context: ToolSecurityContext) -> dict[str, Any]:
        ticker = args["ticker"].upper()
        year = args["fiscal_year"]

        return {
            "ticker": ticker,
            "fiscal_year": year,
            "report_type": "ANNUAL_10K",
            "executive_summary": (
                f"{ticker} reported record operating performance for FY{year}. "
                "Gross profit margins expanded 140 basis points, supported by premium hardware mix and cloud subscriptions."
            ),
            "financial_highlights": {
                "total_revenue": "$383.2B",
                "operating_income": "$114.3B",
                "net_margin": "26.4%",
                "free_cash_flow": "$98.5B",
                "dividend_payout_ratio": "15.2%",
            },
        }

    async def _handle_search_earnings(self, args: dict[str, Any], context: ToolSecurityContext) -> dict[str, Any]:
        ticker = args["ticker"].upper()
        quarter = args["quarter"]
        year = args["year"]

        return {
            "ticker": ticker,
            "quarter": quarter,
            "year": year,
            "eps_actual": 1.48,
            "eps_estimate": 1.42,
            "revenue_billions": 85.8,
            "management_guidance": "Management expects mid-single-digit revenue growth in the upcoming fiscal quarter.",
            "key_quotes": [
                "We remain focused on operational efficiency while accelerating strategic investments in core technology.",
                "Gross margins reached the upper end of our guidance range at 46.2%.",
            ],
        }

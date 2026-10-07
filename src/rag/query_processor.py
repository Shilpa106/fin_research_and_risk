import enum
import re
from dataclasses import dataclass, field

from ..domain.entities import DocumentType


class QueryIntent(str, enum.Enum):
    """Classified intent driving search scoring weights and filtering."""
    FINANCIAL_FACTUAL = "FINANCIAL_FACTUAL"
    RISK_ANALYSIS = "RISK_ANALYSIS"
    POLICY_COMPLIANCE = "POLICY_COMPLIANCE"
    EARNINGS_TRANSCRIPT = "EARNINGS_TRANSCRIPT"
    COMPARATIVE_ANALYSIS = "COMPARATIVE_ANALYSIS"


@dataclass
class ProcessedQuery:
    """Normalized, classified, and rewritten user search query."""
    raw_query: str
    normalized_query: str
    rewritten_query: str
    intent: QueryIntent
    detected_tickers: list[str] = field(default_factory=list)
    detected_fiscal_years: list[int] = field(default_factory=list)
    detected_doc_types: list[DocumentType] = field(default_factory=list)
    requires_rewriting: bool = False


class QueryProcessor:
    """
    Normalizes query strings, classifies intent, extracts financial entity filters,
    and executes query rewriting for hybrid search expansion.
    """

    TICKER_MAP = {
        "apple": "AAPL",
        "microsoft": "MSFT",
        "nvidia": "NVDA",
        "amazon": "AMZN",
        "google": "GOOGL",
        "alphabet": "GOOGL",
        "meta": "META",
        "tesla": "TSLA",
        "jpmorgan": "JPM",
        "goldman": "GS",
        "blackrock": "BLK",
        "berkshire": "BRK",
        "broadcom": "AVGO",
        "amd": "AMD",
        "intel": "INTC",
        "oracle": "ORCL",
        "salesforce": "CRM",
        "morgan stanley": "MS",
        "citigroup": "C",
        "bank of america": "BAC",
        "wells fargo": "WFC",
    }

    EXCLUDED_ACRONYMS = {
        "A", "I", "AN", "THE", "AND", "OR", "IN", "ON", "AT", "TO", "FOR", "OF", "WITH",
        "BY", "VS", "IS", "AS", "BE", "DO", "SO", "NO", "NOT", "ALL", "BUT", "OUT", "NEW",
        "CAN", "HAS", "HAD", "WAS", "ARE", "TOP", "LOW", "HIGH", "NET", "GROSS", "DEBT",
        "CASH", "BOND", "RATE", "FUND", "RISK", "BETA", "ALPHA", "EPS", "PE", "PER",
        "EBITDA", "EBIT", "ROE", "ROA", "ROIC", "CAGR", "DCF", "NAV", "GDP", "CPI", "FED",
        "SEC", "IRS", "CEO", "CFO", "COO", "CTO", "CIO", "CRO", "IPO", "LBO", "ESG", "VAR",
        "FX", "YOY", "QOQ", "MTD", "YTD", "QTD", "USD", "EUR", "GBP", "JPY", "CAD", "AUD",
        "CHF", "CNY", "INR", "GAAP", "IFRS", "FY", "Q1", "Q2", "Q3", "Q4", "AI", "IT",
        "US", "UK", "EU", "RAG", "LLM", "API", "RBAC", "AWS", "S3", "SQL", "SP", "SPX",
        "DJIA", "ETF", "ETFS", "IRR", "WACC", "TAM", "SAM", "SOM", "ARR", "MRR", "KPI",
        "KPIS", "OK", "INFO", "DOC", "PDF", "CSV", "HTML", "TXT", "MD&A", "NDCG", "MAP",
        "AUC", "ROC", "ITEM", "NOTE", "PART", "PAGE",
    }

    INTENT_KEYWORDS = {
        QueryIntent.RISK_ANALYSIS: [
            "var", "value at risk", "stress test", "scenario", "volatility",
            "drawdown", "credit risk", "liquidity", "tail risk", "exposure",
        ],
        QueryIntent.POLICY_COMPLIANCE: [
            "policy", "guideline", "limit", "mandate", "concentration", "restriction",
            "compliance", "esg", "prohibited", "rule", "clause",
        ],
        QueryIntent.EARNINGS_TRANSCRIPT: [
            "call", "transcript", "ceo", "cfo", "said", "q&a", "prepared remarks",
            "guidance", "executive", "conference call",
        ],
        QueryIntent.COMPARATIVE_ANALYSIS: [
            "compare", "versus", "vs", "difference", "benchmark", "relative to",
        ],
    }

    def normalize(self, query: str) -> str:
        """Removes extraneous characters, normalizes whitespace, and lowercases query."""
        cleaned = re.sub(r"\s+", " ", query.strip())
        return cleaned

    def classify_intent(self, query: str) -> QueryIntent:
        """Classifies user intent based on financial vocabulary patterns."""
        lower = query.lower()
        for intent, keywords in self.INTENT_KEYWORDS.items():
            if any(k in lower for k in keywords):
                return intent
        return QueryIntent.FINANCIAL_FACTUAL

    def extract_entities(self, query: str) -> tuple[list[str], list[int], list[DocumentType]]:
        """Extracts ticker symbols, fiscal years, and target document types from query text."""
        tickers: list[str] = []
        years: list[int] = []
        doc_types: list[DocumentType] = []

        lower = query.lower()

        # Check known company names
        for company, ticker in self.TICKER_MAP.items():
            if re.search(rf"\b{re.escape(company)}\b", lower) and ticker not in tickers:
                tickers.append(ticker)

        # Check cashtags ($AAPL, $MSFT, etc.)
        cashtags = re.findall(r"\$([A-Za-z]{1,5})\b", query)
        for ct in cashtags:
            ctu = ct.upper()
            if ctu not in tickers and ctu not in self.EXCLUDED_ACRONYMS:
                tickers.append(ctu)

        # Check direct known ticker symbols
        for ticker in set(self.TICKER_MAP.values()):
            if re.search(rf"\b{ticker}\b", query) and ticker not in tickers:
                tickers.append(ticker)

        # Check 4-digit years (2020-2030)
        year_matches = re.findall(r"\b(202[0-9]|2030)\b", query)
        for y in year_matches:
            yi = int(y)
            if yi not in years:
                years.append(yi)

        # Check doc types
        if "10-k" in lower or "10k" in lower or "annual" in lower:
            doc_types.append(DocumentType.SEC_10K)
        if "10-q" in lower or "10q" in lower or "quarterly" in lower:
            doc_types.append(DocumentType.SEC_10Q)
        if "transcript" in lower or "call" in lower:
            doc_types.append(DocumentType.EARNINGS_TRANSCRIPT)
        if "policy" in lower:
            doc_types.append(DocumentType.RISK_POLICY)

        return tickers, years, doc_types

    def rewrite_query(
        self,
        query: str,
        intent: QueryIntent,
        tickers: list[str],
        years: list[int],
    ) -> str:
        """Expands query with financial synonyms and contextual entities when beneficial."""
        rewritten = query
        expansions = []

        if tickers:
            expansions.append(f"Ticker: {', '.join(tickers)}")
        if years:
            expansions.append(f"Fiscal Year: {', '.join(str(y) for y in years)}")

        if intent == QueryIntent.RISK_ANALYSIS and "var" in query.lower() and "value at risk" not in query.lower():
            expansions.append("Value at Risk (VaR) distribution")
        elif intent == QueryIntent.EARNINGS_TRANSCRIPT and "capex" in query.lower():
            expansions.append("Capital Expenditures AI Infrastructure")

        if expansions:
            rewritten = f"{query} | {', '.join(expansions)}"

        return rewritten

    def process(self, query: str) -> ProcessedQuery:
        """Executes full normalization, intent classification, and rewriting pipeline."""
        normalized = self.normalize(query)
        intent = self.classify_intent(normalized)
        tickers, years, doc_types = self.extract_entities(query)

        # Determine if rewriting is needed
        requires_rewriting = bool(tickers or years or intent != QueryIntent.FINANCIAL_FACTUAL)
        rewritten = self.rewrite_query(normalized, intent, tickers, years) if requires_rewriting else normalized

        return ProcessedQuery(
            raw_query=query,
            normalized_query=normalized,
            rewritten_query=rewritten,
            intent=intent,
            detected_tickers=tickers,
            detected_fiscal_years=years,
            detected_doc_types=doc_types,
            requires_rewriting=requires_rewriting,
        )

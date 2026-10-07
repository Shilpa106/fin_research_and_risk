from datetime import datetime

import pytest

from src.domain.entities import DocumentType
from src.domain.exceptions import TenantIsolationViolationException
from src.evaluation.retrieval_metrics import RetrievalEvaluator
from src.rag.chunking import (
    CompositeChunker,
    FinancialChunk,
    PolicySectionChunker,
    RecursiveProseChunker,
    SectionAwareReportChunker,
    SpeakerAwareTranscriptChunker,
    TableAwareFinancialChunker,
)
from src.rag.citations import CitationTracker
from src.rag.embeddings import DeterministicEmbeddingProvider
from src.rag.opensearch_client import OpenSearchHybridStore
from src.rag.query_processor import QueryIntent, QueryProcessor
from src.rag.retrieval_service import RetrievalService


@pytest.fixture
def store():
    return OpenSearchHybridStore()


@pytest.fixture
def embedding_provider():
    return DeterministicEmbeddingProvider()


@pytest.fixture
def retrieval_service(store, embedding_provider):
    return RetrievalService(store=store, embedding_provider=embedding_provider)


# ==============================================================================
# 1. Tenant Isolation in Retrieval Tests
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_retrieval_tenant_isolation_boundary(retrieval_service: RetrievalService):
    """
    Critical requirement: A user from Tenant A must NEVER retrieve or access Tenant B data,
    even when executing identical semantic or keyword queries.
    """
    tenant_a = "tenant-hedgefund-alpha"
    tenant_b = "tenant-pension-beta"

    # Index proprietary research note for Tenant A
    chunk_a = FinancialChunk(
        chunk_id="chunk-alpha-001",
        document_id="doc-alpha-sec-10k",
        document_version=1,
        tenant_id=tenant_a,
        content="Alpha Fund confidential positioning: Overweight Semiconductor equities, short long-duration Treasuries.",
        page=1,
        section="Investment Strategy",
        source="Alpha_Macro_Strategy.pdf",
        timestamp=datetime.utcnow(),
        permissions=["ANALYST", "ADMIN"],
        metadata={"ticker": "NVDA", "fiscal_year": 2026},
    )
    await retrieval_service.index_chunks(tenant_id=tenant_a, chunks=[chunk_a])

    # Index proprietary policy for Tenant B
    chunk_b = FinancialChunk(
        chunk_id="chunk-beta-001",
        document_id="doc-beta-policy",
        document_version=1,
        tenant_id=tenant_b,
        content="Beta Pension mandated ESG criteria: Prohibit investments in fossil fuel exploration.",
        page=1,
        section="Mandate",
        source="Beta_ESG_Policy.pdf",
        timestamp=datetime.utcnow(),
        permissions=["ANALYST", "ADMIN"],
        metadata={"fiscal_year": 2026},
    )
    await retrieval_service.index_chunks(tenant_id=tenant_b, chunks=[chunk_b])

    # 1. Tenant B searches for "Alpha Fund confidential positioning" -> Must NEVER return Tenant A's chunk
    res_b = await retrieval_service.retrieve(
        tenant_id=tenant_b,
        query="Alpha Fund confidential positioning semiconductor equities",
        top_k=5,
    )
    assert all(h.chunk.tenant_id == tenant_b for h in res_b.hits)
    assert all("Alpha Fund" not in h.chunk.content for h in res_b.hits)
    assert "Alpha Fund" not in res_b.context.context_text

    # 2. Tenant A searches for "Beta Pension mandated ESG criteria" -> Must NEVER return Tenant B's chunk
    res_a = await retrieval_service.retrieve(
        tenant_id=tenant_a,
        query="Beta Pension mandated ESG criteria fossil fuel",
        top_k=5,
    )
    assert all(h.chunk.tenant_id == tenant_a for h in res_a.hits)
    assert all("Beta Pension" not in h.chunk.content for h in res_a.hits)
    assert "Beta Pension" not in res_a.context.context_text

    # 3. Tenant A searches for their own data -> Returns chunk
    res_a_own = await retrieval_service.retrieve(
        tenant_id=tenant_a,
        query="Semiconductor equities Treasuries positioning",
        top_k=5,
    )
    assert len(res_a_own.hits) >= 1
    assert "Alpha Fund confidential positioning" in res_a_own.context.context_text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retrieval_indexing_tenant_mismatch_rejected(retrieval_service: RetrievalService):
    """Attempting to index chunks into the wrong tenant boundary raises TenantIsolationViolationException."""
    mismatched_chunk = FinancialChunk(
        chunk_id="chunk-bad-001",
        document_id="doc-bad",
        document_version=1,
        tenant_id="tenant-actual-owner",
        content="Confidential financial statements",
        page=1,
        section="Financials",
        source="filing.pdf",
        timestamp=datetime.utcnow(),
    )
    with pytest.raises(TenantIsolationViolationException):
        await retrieval_service.index_chunks(tenant_id="tenant-attacker", chunks=[mismatched_chunk])


# ==============================================================================
# 2. Document-Level RBAC Permissions Filtering
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_document_level_permissions_filtering(retrieval_service: RetrievalService):
    """Confirms that chunks with restricted roles are filtered out if caller lacks permissions."""
    tenant_id = "tenant-goldman-am"

    public_chunk = FinancialChunk(
        chunk_id="chk-pub",
        document_id="doc-research",
        document_version=1,
        tenant_id=tenant_id,
        content="S&P 500 consensus EPS growth projection is 11.2% for FY2026.",
        page=1,
        section="Overview",
        source="Global_Equity.pdf",
        timestamp=datetime.utcnow(),
        permissions=["READ_ONLY_USER", "ANALYST", "RISK_MANAGER", "ADMIN"],
    )
    restricted_chunk = FinancialChunk(
        chunk_id="chk-priv",
        document_id="doc-research",
        document_version=1,
        tenant_id=tenant_id,
        content="Confidential proprietary quantitative factor weights for Market Neutral portfolio.",
        page=2,
        section="Quant Models",
        source="Global_Equity.pdf",
        timestamp=datetime.utcnow(),
        permissions=["RISK_MANAGER", "ADMIN"],  # Restricted!
    )
    await retrieval_service.index_chunks(tenant_id=tenant_id, chunks=[public_chunk, restricted_chunk])

    # 1. READ_ONLY_USER searches -> only gets public chunk
    res_readonly = await retrieval_service.retrieve(
        tenant_id=tenant_id,
        query="quantitative factor weights EPS growth",
        user_permissions=["READ_ONLY_USER"],
        top_k=5,
    )
    assert len(res_readonly.hits) == 1
    assert res_readonly.hits[0].chunk.chunk_id == "chk-pub"

    # 2. RISK_MANAGER searches -> gets both public and restricted chunks
    res_risk = await retrieval_service.retrieve(
        tenant_id=tenant_id,
        query="quantitative factor weights EPS growth",
        user_permissions=["RISK_MANAGER"],
        top_k=5,
    )
    assert len(res_risk.hits) == 2


# ==============================================================================
# 3. Domain-Specific Chunking Strategies
# ==============================================================================

def test_chunking_strategies_retention():
    """Verify all 5 domain chunking strategies retain mandatory metadata."""
    doc_id = "doc-apple-2026"
    version = 2
    tenant = "tenant-fidelity"
    source = "AAPL_10K.pdf"

    # 1. Recursive Prose
    prose = "First paragraph discussing macro conditions.\n\nSecond paragraph evaluating currency risk."
    p_chunker = RecursiveProseChunker(target_tokens=50, overlap_tokens=10)
    p_chunks = p_chunker.chunk(prose, doc_id, version, tenant, source)
    assert len(p_chunks) >= 1
    assert p_chunks[0].document_id == doc_id
    assert p_chunks[0].document_version == version
    assert p_chunks[0].tenant_id == tenant
    assert p_chunks[0].chunk_id.startswith(doc_id)

    # 2. Section-Aware Report
    report = (
        "Item 1. Business\nApple designs, manufactures and markets smartphones.\n\n"
        "Item 1A. Risk Factors\nGlobal trade conflicts and semiconductor supply disruptions.\n\n"
        "Item 7. Management's Discussion\nNet sales increased 8 percent to record highs."
    )
    r_chunker = SectionAwareReportChunker()
    r_chunks = r_chunker.chunk(report, doc_id, version, tenant, source)
    assert len(r_chunks) >= 3
    sections_found = {c.section for c in r_chunks}
    assert any("Item 1A" in s or "Risk" in s for s in sections_found)

    # 3. Speaker-Aware Transcript
    transcript = (
        "Tim Cook - CEO: Good afternoon everyone and welcome to our Q3 earnings call.\n"
        "Luca Maestri - CFO: Gross margins reached 46.2 percent, at the high end of our guidance.\n"
        "Toni Sacconaghi (Sanford Bernstein): Tim, could you comment on China sales momentum?"
    )
    spk_chunker = SpeakerAwareTranscriptChunker()
    spk_chunks = spk_chunker.chunk(transcript, doc_id, version, tenant, source)
    assert len(spk_chunks) >= 3
    assert any("Tim Cook" in c.section for c in spk_chunks)
    assert any("Luca Maestri" in c.section for c in spk_chunks)

    # 4. Table-Aware Financial Chunker
    table_text = (
        "Consolidated Balance Sheet | 2025 | 2026\n"
        "Cash and Cash Equivalents | $29,965 | $32,150\n"
        "Marketable Securities | $31,590 | $35,200\n"
        "Inventories | $6,331 | $6,120\n"
        "Total Current Assets | $143,566 | $152,480"
    )
    tbl_chunker = TableAwareFinancialChunker()
    tbl_chunks = tbl_chunker.chunk(table_text, doc_id, version, tenant, source, rows_per_chunk=2)
    assert len(tbl_chunks) >= 2
    # Verify table header is retained on sub-chunks
    assert "Consolidated Balance Sheet" in tbl_chunks[1].content

    # 5. Policy Section Chunker
    policy_text = (
        "Section 4.1 Liquidity Risk Policy\nAll funds must maintain at least 15% in Tier 1 liquid assets.\n\n"
        "Section 4.2 Concentration Limits\nNo single issuer exposure shall exceed 5% of net portfolio asset value."
    )
    pol_chunker = PolicySectionChunker()
    pol_chunks = pol_chunker.chunk(policy_text, doc_id, version, tenant, source)
    assert len(pol_chunks) == 2
    assert "Section 4.1" in pol_chunks[0].content
    assert "Section 4.2" in pol_chunks[1].content

    # 6. Composite Chunker dispatch
    comp = CompositeChunker()
    dispatched = comp.chunk_document(transcript, DocumentType.EARNINGS_TRANSCRIPT, doc_id, version, tenant, source)
    assert len(dispatched) >= 3


# ==============================================================================
# 4. Query Normalization, Intent Classification & Rewriting
# ==============================================================================

def test_query_processor_flow():
    """Verify normalization, intent detection, entity extraction, and query rewriting."""
    processor = QueryProcessor()

    # Query 1: Risk Analysis
    q1 = "   What is the 10-day VaR and portfolio drawdown risk for MSFT in 2026?  "
    res1 = processor.process(q1)
    assert res1.intent == QueryIntent.RISK_ANALYSIS
    assert "MSFT" in res1.detected_tickers
    assert 2026 in res1.detected_fiscal_years
    assert "Value at Risk" in res1.rewritten_query

    # Query 2: Earnings Transcript
    q2 = "What did the CEO say in the apple transcript call regarding AI capex?"
    res2 = processor.process(q2)
    assert res2.intent == QueryIntent.EARNINGS_TRANSCRIPT
    assert "AAPL" in res2.detected_tickers
    assert "Capital Expenditures" in res2.rewritten_query

    # Query 3: Policy Compliance
    q3 = "What are the concentration policy limits for high yield credit?"
    res3 = processor.process(q3)
    assert res3.intent == QueryIntent.POLICY_COMPLIANCE


# ==============================================================================
# 5. Traceable Citation Engine & Context Construction
# ==============================================================================

@pytest.mark.integration
@pytest.mark.asyncio
async def test_traceable_citation_generation(retrieval_service: RetrievalService):
    """Verifies that retrieved chunks produce numbered citations and verifies claim traceability."""
    tenant_id = "tenant-morgan-stanley"

    chunk = FinancialChunk(
        chunk_id="c_msft_01",
        document_id="doc_msft_10k",
        document_version=1,
        tenant_id=tenant_id,
        content="Microsoft Azure revenue grew 29% YoY in Q4 2026, reaching $75.4B in annualized run rate.",
        page=42,
        section="Cloud Segment MD&A",
        source="MSFT_FY2026_10K.pdf",
        timestamp=datetime.utcnow(),
        metadata={"ticker": "MSFT", "fiscal_year": 2026},
    )
    await retrieval_service.index_chunks(tenant_id, [chunk])

    res = await retrieval_service.retrieve(
        tenant_id=tenant_id,
        query="What was Microsoft Azure revenue growth in 2026?",
        top_k=3,
    )

    # 1. Verify Citation structure
    assert len(res.citations) == 1
    cit = res.citations[0]
    assert cit.citation_index == 1
    assert cit.document_id == "doc_msft_10k"
    assert cit.source == "MSFT_FY2026_10K.pdf"
    assert cit.page == 42
    assert cit.section == "Cloud Segment MD&A"

    # 2. Verify Context formatting
    assert "[1] Source: MSFT_FY2026_10K.pdf | Page: 42" in res.context.context_text

    # 3. Verify Claim Citation Validator
    tracker = CitationTracker()
    valid_claim = "Azure revenue grew 29% YoY reaching $75.4B [1]."
    verification = tracker.verify_claim_citations(valid_claim, res.citations)
    assert verification["is_grounded"] is True
    assert verification["cited_indices"] == [1]

    # Hallucinated citation anchor
    hallucinated_claim = "Azure operating margin expanded by 340 bps [5]."
    hallu_verif = tracker.verify_claim_citations(hallucinated_claim, res.citations)
    assert hallu_verif["is_grounded"] is False
    assert 5 in hallu_verif["hallucinated_indices"]


# ==============================================================================
# 6. Retrieval Evaluation Metrics Hooks
# ==============================================================================

def test_retrieval_evaluator_metrics():
    """Verify Recall@K, Precision@K, MRR, NDCG@K, Context Precision, and Context Recall calculations."""
    retrieved = ["chunk_1", "chunk_2", "chunk_3", "chunk_4", "chunk_5"]
    relevant = ["chunk_1", "chunk_3"]
    ground_truth = ["Azure grew 29%", "Annualized run rate $75.4B"]
    context_text = "Microsoft reported Azure grew 29% in the cloud segment with an annualized run rate $75.4B."

    metrics = RetrievalEvaluator.calculate_metrics(
        retrieved_chunk_ids=retrieved,
        relevant_chunk_ids=relevant,
        retrieved_context_text=context_text,
        ground_truth_statements=ground_truth,
        k=5,
    )

    # Recall@5: 2 found out of 2 relevant -> 1.0
    assert metrics.recall_at_k == 1.0
    # Precision@5: 2 relevant in top 5 -> 0.4
    assert metrics.precision_at_k == 0.4
    # MRR: first relevant is at rank 1 -> 1.0
    assert metrics.mrr == 1.0
    # NDCG@5 > 0.8
    assert metrics.ndcg_at_k > 0.8
    # Context Precision > 0.5
    assert metrics.context_precision > 0.5
    # Context Recall covers both statements -> 1.0
    assert metrics.context_recall == 1.0

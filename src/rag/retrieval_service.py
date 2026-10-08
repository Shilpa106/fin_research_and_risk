import time
from dataclasses import dataclass, field
from typing import Any

from ..domain.exceptions import TenantIsolationViolationException
from ..interfaces.embedding import EmbeddingProvider
from ..observability.metrics import metrics_registry
from ..observability.tracing import SpanKind, default_tracer
from .chunking import FinancialChunk
from .citations import AssembledContext, Citation, CitationTracker
from .embeddings import get_embedding_provider
from .opensearch_client import OpenSearchHybridStore, SearchHit
from .post_processor import ChunkDeduplicator, ContextCompressor, CrossEncoderReranker, RerankerInterface
from .query_processor import ProcessedQuery, QueryProcessor


@dataclass
class RetrievalResult:
    """Consolidated end-to-end output of the hybrid RAG retrieval pipeline."""
    query: str
    processed_query: ProcessedQuery
    context: AssembledContext
    citations: list[Citation]
    hits: list[SearchHit]
    latency_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


class RetrievalService:
    """
    Dedicated enterprise hybrid RAG retrieval engine.
    Executes the full pipeline:
    Query -> Normalization -> Intent -> Rewriting -> Filtering -> Vector + BM25 Search
    -> Fusion -> Rerank -> Deduplicate -> Context Compression -> Context Construction -> Citations.
    """

    def __init__(
        self,
        store: OpenSearchHybridStore | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        reranker: RerankerInterface | None = None,
        query_processor: QueryProcessor | None = None,
        deduplicator: ChunkDeduplicator | None = None,
        compressor: ContextCompressor | None = None,
        citation_tracker: CitationTracker | None = None,
    ):
        self.store = store or OpenSearchHybridStore()
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.reranker = reranker or CrossEncoderReranker()
        self.query_processor = query_processor or QueryProcessor()
        self.deduplicator = deduplicator or ChunkDeduplicator()
        self.compressor = compressor or ContextCompressor(max_context_tokens=2500)
        self.citation_tracker = citation_tracker or CitationTracker()

    async def index_chunks(self, tenant_id: str, chunks: list[FinancialChunk]) -> int:
        """
        Generates vector embeddings (if absent) and indexes chunks into OpenSearch hybrid store.
        Strictly verifies that all chunks belong to tenant_id.
        """
        for chunk in chunks:
            if chunk.tenant_id != tenant_id:
                raise TenantIsolationViolationException(
                    f"Retrieval indexing breach: chunk tenant '{chunk.tenant_id}' does not match '{tenant_id}'"
                )

        # Batch embed chunks if vectors not already attached
        unembedded = [c for c in chunks if c.embedding is None]
        if unembedded:
            texts = [c.content for c in unembedded]
            embeddings = await self.embedding_provider.embed_documents(texts)
            for c, emb in zip(unembedded, embeddings, strict=False):
                c.embedding = emb

        return self.store.index_chunks(tenant_id, chunks)

    async def retrieve(
        self,
        tenant_id: str,
        query: str,
        user_permissions: list[str] | None = None,
        top_k: int = 5,
        alpha: float = 0.6,
        override_tickers: list[str] | None = None,
        override_doc_types: list[str] | None = None,
        override_fiscal_years: list[int] | None = None,
    ) -> RetrievalResult:
        """
        Executes the end-to-end multi-stage retrieval pipeline strictly scoped to tenant_id.
        """
        start_time = time.perf_counter()

        # Step 1 & 2 & 3: Normalization, Intent Classification, Query Rewriting
        processed: ProcessedQuery = self.query_processor.process(query)

        # Step 4: Metadata filtering preparation
        tickers = override_tickers or processed.detected_tickers or None
        fiscal_years = override_fiscal_years or processed.detected_fiscal_years or None
        doc_types = override_doc_types or ([dt.value for dt in processed.detected_doc_types] if processed.detected_doc_types else None)

        # Generate dense vector for rewritten query
        query_vector = await self.embedding_provider.embed_query(processed.rewritten_query)

        # Step 5, 6, 7: Vector Retrieval + BM25 Retrieval + Result Fusion
        retrieval_start = time.perf_counter()
        with default_tracer.start_as_current_span(
            "rag.hybrid_search",
            kind=SpanKind.INTERNAL,
            attributes={"rag.query": processed.rewritten_query, "rag.tenant_id": tenant_id, "rag.top_k": top_k},
        ):
            fused_hits: list[SearchHit] = self.store.hybrid_search(
                tenant_id=tenant_id,
                query_text=processed.rewritten_query,
                query_vector=query_vector,
                top_k=top_k * 3,  # Over-fetch for reranking and deduplication
                alpha=alpha,
                tickers=tickers,
                doc_types=doc_types,
                fiscal_years=fiscal_years,
                user_permissions=user_permissions,
            )
        retrieval_dur = time.perf_counter() - retrieval_start

        # Step 8: Reranking
        rerank_start = time.perf_counter()
        with default_tracer.start_as_current_span(
            "rag.reranker",
            kind=SpanKind.INTERNAL,
            attributes={"rag.candidate_count": len(fused_hits)},
        ):
            reranked_hits: list[SearchHit] = await self.reranker.rerank(
                query=processed.rewritten_query,
                hits=fused_hits,
                top_k=top_k * 2,
            )
        rerank_dur = time.perf_counter() - rerank_start

        # Step 9: Deduplication
        deduped_hits: list[SearchHit] = self.deduplicator.deduplicate(reranked_hits, threshold=0.85)

        # Step 10: Context Compression
        compressed_hits: list[SearchHit] = self.compressor.compress(
            query=processed.normalized_query,
            hits=deduped_hits[:top_k],
        )

        # Step 11 & 12: Context Construction & Traceable Citation Anchoring
        context: AssembledContext = self.citation_tracker.build_context(compressed_hits)

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        # Record RAG Observability Golden Signals
        metrics_registry.record_rag_retrieval(
            retrieval_latency_seconds=retrieval_dur,
            reranker_latency_seconds=rerank_dur,
            recall_at_k=1.0 if compressed_hits else 0.0,
            cache_hit=False,
        )

        return RetrievalResult(
            query=query,
            processed_query=processed,
            context=context,
            citations=context.citations,
            hits=compressed_hits,
            latency_ms=round(latency_ms, 2),
            metadata={
                "tenant_id": tenant_id,
                "intent": processed.intent.value,
                "tickers_filtered": tickers,
                "doc_types_filtered": doc_types,
                "fiscal_years_filtered": fiscal_years,
                "candidate_count": len(fused_hits),
                "final_chunk_count": len(compressed_hits),
            },
        )

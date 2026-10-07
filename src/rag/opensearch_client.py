import collections
import logging
import math
import re
from dataclasses import dataclass

from ..domain.exceptions import TenantIsolationViolationException
from .chunking import FinancialChunk

logger = logging.getLogger(__name__)


@dataclass
class SearchHit:
    """Standardized search hit returned by vector, BM25, and hybrid queries."""
    chunk: FinancialChunk
    score: float
    vector_score: float = 0.0
    bm25_score: float = 0.0


class OpenSearchHybridStore:
    """
    OpenSearch abstraction supporting Dense Vector k-NN, Lexical BM25, and Hybrid fusion.
    Features:
    - Non-overridable multi-tenant boundary checks
    - Document-level RBAC permission filtering
    - Exact Okapi BM25 scoring engine
    - Vector Cosine Similarity
    - Reciprocal Rank Fusion (RRF) & Convex Combination
    """

    def __init__(self, k1: float = 1.2, b: float = 0.75):
        self.k1 = k1
        self.b = b
        # tenant_id -> list of FinancialChunk
        self._store: dict[str, list[FinancialChunk]] = collections.defaultdict(list)
        # tenant_id -> chunk_id -> chunk
        self._chunk_index: dict[str, dict[str, FinancialChunk]] = collections.defaultdict(dict)

    def _tokenize(self, text: str) -> list[str]:
        """Simple word tokenization for BM25 calculation."""
        words = re.findall(r"\b[a-zA-Z0-9_\$%\.]+\b", text.lower())
        return [w for w in words if len(w) > 1]

    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Calculates cosine similarity between two float vectors."""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        dot = sum(a * b for a, b in zip(vec1, vec2, strict=False))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        return max(0.0, min(1.0, (dot / (norm1 * norm2) + 1.0) / 2.0))

    def index_chunks(self, tenant_id: str, chunks: list[FinancialChunk]) -> int:
        """Indexes chunks scoped strictly to the given tenant."""
        indexed_count = 0
        for chunk in chunks:
            # Force tenant_id consistency
            if chunk.tenant_id != tenant_id:
                raise TenantIsolationViolationException(
                    f"Indexing tenant breach: chunk tenant '{chunk.tenant_id}' does not match target '{tenant_id}'"
                )
            self._chunk_index[tenant_id][chunk.chunk_id] = chunk
            # Update store list
            existing = [c for c in self._store[tenant_id] if c.chunk_id == chunk.chunk_id]
            if not existing:
                self._store[tenant_id].append(chunk)
                indexed_count += 1
            else:
                idx = self._store[tenant_id].index(existing[0])
                self._store[tenant_id][idx] = chunk
                indexed_count += 1

        logger.debug(f"Indexed {indexed_count} chunks for tenant '{tenant_id}'")
        return indexed_count

    def _passes_filters(
        self,
        chunk: FinancialChunk,
        tickers: list[str] | None = None,
        doc_types: list[str] | None = None,
        fiscal_years: list[int] | None = None,
        user_permissions: list[str] | None = None,
    ) -> bool:
        """Verifies metadata filters and document-level permissions."""
        # 1. Document-level permissions: User must have at least one required permission
        if user_permissions is not None:
            if chunk.permissions and not any(p in user_permissions for p in chunk.permissions):
                return False

        # 2. Tickers filter
        if tickers:
            chunk_ticker = chunk.metadata.get("ticker")
            if not chunk_ticker or chunk_ticker not in tickers:
                # Also check content text for ticker
                if not any(t in chunk.content for t in tickers):
                    return False

        # 3. Fiscal years filter
        if fiscal_years:
            chunk_year = chunk.metadata.get("fiscal_year")
            if chunk_year and chunk_year not in fiscal_years:
                return False

        # 4. Doc types filter
        if doc_types:
            chunk_doc_type = chunk.metadata.get("doc_type")
            if chunk_doc_type and chunk_doc_type not in doc_types:
                return False

        return True

    def vector_search(
        self,
        tenant_id: str,
        query_vector: list[float],
        top_k: int = 10,
        tickers: list[str] | None = None,
        doc_types: list[str] | None = None,
        fiscal_years: list[int] | None = None,
        user_permissions: list[str] | None = None,
    ) -> list[SearchHit]:
        """Executes k-NN dense vector search strictly isolated to tenant_id."""
        tenant_chunks = self._store.get(tenant_id, [])
        scored: list[SearchHit] = []

        for chunk in tenant_chunks:
            if not self._passes_filters(chunk, tickers, doc_types, fiscal_years, user_permissions):
                continue
            if chunk.embedding is None:
                continue

            sim = self._cosine_similarity(query_vector, chunk.embedding)
            scored.append(SearchHit(chunk=chunk, score=sim, vector_score=sim))

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]

    def bm25_search(
        self,
        tenant_id: str,
        query_text: str,
        top_k: int = 10,
        tickers: list[str] | None = None,
        doc_types: list[str] | None = None,
        fiscal_years: list[int] | None = None,
        user_permissions: list[str] | None = None,
    ) -> list[SearchHit]:
        """Executes Okapi BM25 lexical search strictly isolated to tenant_id."""
        tenant_chunks = self._store.get(tenant_id, [])
        if not tenant_chunks:
            return []

        # Filter candidate chunks
        candidates = [
            c for c in tenant_chunks
            if self._passes_filters(c, tickers, doc_types, fiscal_years, user_permissions)
        ]
        if not candidates:
            return []

        query_tokens = self._tokenize(query_text)
        if not query_tokens:
            return []

        # Corpus statistics
        N = len(candidates)
        tokenized_corpus = {c.chunk_id: self._tokenize(c.content) for c in candidates}
        doc_lengths = {c.chunk_id: len(tokenized_corpus[c.chunk_id]) for c in candidates}
        avgdl = sum(doc_lengths.values()) / max(1, N)

        # Document frequency: n(q_i)
        df: dict[str, int] = collections.defaultdict(int)
        for c in candidates:
            doc_unique_tokens = set(tokenized_corpus[c.chunk_id])
            for qt in query_tokens:
                if qt in doc_unique_tokens:
                    df[qt] += 1

        scored: list[SearchHit] = []
        for c in candidates:
            c_tokens = tokenized_corpus[c.chunk_id]
            tf = collections.Counter(c_tokens)
            doc_len = doc_lengths[c.chunk_id]

            score = 0.0
            for qt in query_tokens:
                if tf[qt] > 0:
                    # Okapi BM25 IDF formula
                    idf = math.log(1.0 + (N - df[qt] + 0.5) / (df[qt] + 0.5))
                    term_freq = tf[qt]
                    numerator = term_freq * (self.k1 + 1.0)
                    denominator = term_freq + self.k1 * (1.0 - self.b + self.b * (doc_len / avgdl))
                    score += idf * (numerator / max(0.001, denominator))

            if score > 0.0:
                scored.append(SearchHit(chunk=c, score=score, bm25_score=score))

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]

    def hybrid_search(
        self,
        tenant_id: str,
        query_text: str,
        query_vector: list[float],
        top_k: int = 10,
        alpha: float = 0.6,  # 0.6 vector, 0.4 BM25
        tickers: list[str] | None = None,
        doc_types: list[str] | None = None,
        fiscal_years: list[int] | None = None,
        user_permissions: list[str] | None = None,
    ) -> list[SearchHit]:
        """
        Executes hybrid vector + BM25 search with convex score fusion,
        strictly isolated to tenant_id.
        """
        # Fetch larger candidate pool for fusion
        fetch_k = top_k * 3
        vec_hits = self.vector_search(
            tenant_id=tenant_id,
            query_vector=query_vector,
            top_k=fetch_k,
            tickers=tickers,
            doc_types=doc_types,
            fiscal_years=fiscal_years,
            user_permissions=user_permissions,
        )
        bm25_hits = self.bm25_search(
            tenant_id=tenant_id,
            query_text=query_text,
            top_k=fetch_k,
            tickers=tickers,
            doc_types=doc_types,
            fiscal_years=fiscal_years,
            user_permissions=user_permissions,
        )

        # Normalize BM25 scores to [0, 1]
        max_bm25 = max((h.bm25_score for h in bm25_hits), default=1.0) or 1.0

        hit_map: dict[str, SearchHit] = {}

        # Process vector hits
        for h in vec_hits:
            hit_map[h.chunk.chunk_id] = SearchHit(
                chunk=h.chunk,
                score=alpha * h.vector_score,
                vector_score=h.vector_score,
                bm25_score=0.0,
            )

        # Fuse BM25 hits
        for h in bm25_hits:
            norm_bm25 = h.bm25_score / max_bm25
            if h.chunk.chunk_id in hit_map:
                existing = hit_map[h.chunk.chunk_id]
                existing.bm25_score = norm_bm25
                existing.score = (alpha * existing.vector_score) + ((1.0 - alpha) * norm_bm25)
            else:
                hit_map[h.chunk.chunk_id] = SearchHit(
                    chunk=h.chunk,
                    score=(1.0 - alpha) * norm_bm25,
                    vector_score=0.0,
                    bm25_score=norm_bm25,
                )

        fused = list(hit_map.values())
        fused.sort(key=lambda x: x.score, reverse=True)
        return fused[:top_k]

    def clear(self) -> None:
        """Clears all indexed chunks across all tenants (for test isolation)."""
        self._store.clear()
        self._chunk_index.clear()

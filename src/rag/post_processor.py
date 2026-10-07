import re
from typing import Protocol, runtime_checkable

from .opensearch_client import SearchHit


@runtime_checkable
class RerankerInterface(Protocol):
    """Protocol for neural/cross-encoder reranking of retrieved candidate chunks."""

    async def rerank(self, query: str, hits: list[SearchHit], top_k: int = 5) -> list[SearchHit]:
        """Reranks candidate search hits and returns top_k highest relevance results."""
        ...


class CrossEncoderReranker(RerankerInterface):
    """
    Reranks candidate hits using lexical-semantic term alignment and entity boosting.
    Simulates high-precision neural reranker models (Cohere Rerank / BGE Reranker).
    """

    def __init__(self, exact_match_boost: float = 0.25):
        self.exact_match_boost = exact_match_boost

    async def rerank(self, query: str, hits: list[SearchHit], top_k: int = 5) -> list[SearchHit]:
        if not hits:
            return []

        query_terms = set(re.findall(r"\b[a-zA-Z0-9_\$%\.]+\b", query.lower()))
        reranked: list[SearchHit] = []

        for hit in hits:
            content_lower = hit.chunk.content.lower()
            content_terms = set(re.findall(r"\b[a-zA-Z0-9_\$%\.]+\b", content_lower))

            # Calculate term overlap ratio
            overlap = len(query_terms.intersection(content_terms)) / max(1, len(query_terms))

            # Check for financial numbers and percentages mentioned in query
            query_numbers = re.findall(r"\b\d+(?:\.\d+)?%?\b", query)
            number_match_bonus = 0.0
            for num in query_numbers:
                if num in hit.chunk.content:
                    number_match_bonus += 0.15

            # Combined reranking score
            new_score = (hit.score * 0.6) + (overlap * 0.3) + min(0.3, number_match_bonus)
            reranked.append(
                SearchHit(
                    chunk=hit.chunk,
                    score=round(new_score, 4),
                    vector_score=hit.vector_score,
                    bm25_score=hit.bm25_score,
                )
            )

        reranked.sort(key=lambda x: x.score, reverse=True)
        return reranked[:top_k]


class ReciprocalRankFusion:
    """Applies Reciprocal Rank Fusion (RRF) across multiple search hit candidate lists."""

    @staticmethod
    def fuse(ranking_lists: list[list[SearchHit]], k: int = 60, top_k: int = 10) -> list[SearchHit]:
        rrf_scores: dict[str, float] = {}
        hit_map: dict[str, SearchHit] = {}

        for rank_list in ranking_lists:
            for rank_idx, hit in enumerate(rank_list):
                chunk_id = hit.chunk.chunk_id
                hit_map[chunk_id] = hit
                score = 1.0 / (k + rank_idx + 1)
                rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + score

        fused_hits: list[SearchHit] = []
        for chunk_id, total_score in rrf_scores.items():
            base_hit = hit_map[chunk_id]
            fused_hits.append(
                SearchHit(
                    chunk=base_hit.chunk,
                    score=round(total_score, 5),
                    vector_score=base_hit.vector_score,
                    bm25_score=base_hit.bm25_score,
                )
            )

        fused_hits.sort(key=lambda x: x.score, reverse=True)
        return fused_hits[:top_k]


class ChunkDeduplicator:
    """Eliminates redundant or near-duplicate chunks from adjacent pages or revisions."""

    @staticmethod
    def _jaccard_similarity(text1: str, text2: str) -> float:
        set1 = set(text1.lower().split())
        set2 = set(text2.lower().split())
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        return intersection / max(1, union)

    def deduplicate(self, hits: list[SearchHit], threshold: float = 0.80) -> list[SearchHit]:
        unique_hits: list[SearchHit] = []

        for hit in hits:
            is_dup = False
            for existing in unique_hits:
                # Check same document or consecutive chunks
                if existing.chunk.document_id == hit.chunk.document_id:
                    sim = self._jaccard_similarity(existing.chunk.content, hit.chunk.content)
                    if sim >= threshold:
                        is_dup = True
                        break
            if not is_dup:
                unique_hits.append(hit)

        return unique_hits


class ContextCompressor:
    """Compresses retrieved chunks to maximize relevance density within token limits."""

    def __init__(self, max_context_tokens: int = 2500):
        self.max_context_tokens = max_context_tokens

    def compress(self, query: str, hits: list[SearchHit]) -> list[SearchHit]:
        total_tokens = 0
        compressed_hits: list[SearchHit] = []

        query_terms = set(query.lower().split())

        for hit in hits:
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", hit.chunk.content) if s.strip()]
            relevant_sentences: list[str] = []

            for sent in sentences:
                sent_terms = set(sent.lower().split())
                # If sentence shares terms or has numbers, keep it
                if sent_terms.intersection(query_terms) or re.search(r"\d", sent):
                    relevant_sentences.append(sent)

            if not relevant_sentences:
                relevant_sentences = sentences[:3]  # Keep first 3 sentences as fallback

            compressed_text = " ".join(relevant_sentences)
            token_est = max(1, len(compressed_text) // 4)

            if total_tokens + token_est <= self.max_context_tokens:
                compressed_chunk = hit.chunk
                compressed_chunk.content = compressed_text
                compressed_hits.append(
                    SearchHit(
                        chunk=compressed_chunk,
                        score=hit.score,
                        vector_score=hit.vector_score,
                        bm25_score=hit.bm25_score,
                    )
                )
                total_tokens += token_est
            else:
                break

        return compressed_hits or hits[:2]

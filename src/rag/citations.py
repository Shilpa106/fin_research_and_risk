import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .opensearch_client import SearchHit


@dataclass
class Citation:
    """Traceable evidence citation anchor linking generated claims to ground truth sources."""
    citation_index: int
    chunk_id: str
    document_id: str
    document_version: int
    source: str
    page: int
    section: str
    snippet: str
    relevance_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AssembledContext:
    """Prompt context constructed from retrieved chunks with numbered citation anchors."""
    context_text: str
    citations: list[Citation] = field(default_factory=list)
    chunk_count: int = 0
    total_tokens: int = 0


class CitationTracker:
    """
    Manages citation anchor assignment, prompt context formatting,
    and verification of generated claims against retrieved evidence.
    """

    def build_context(self, hits: list[SearchHit]) -> AssembledContext:
        """
        Assembles retrieved hits into an anchored prompt context.
        Each chunk is assigned a numbered reference [1], [2], ...
        """
        citations: list[Citation] = []
        context_blocks: list[str] = []

        for idx, hit in enumerate(hits, start=1):
            chunk = hit.chunk
            snippet = chunk.content[:150].replace("\n", " ").strip() + "..."

            cit = Citation(
                citation_index=idx,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document_version=chunk.document_version,
                source=chunk.source,
                page=chunk.page,
                section=chunk.section,
                snippet=snippet,
                relevance_score=round(hit.score, 4),
            )
            citations.append(cit)

            header = f"[{idx}] Source: {chunk.source} | Page: {chunk.page} | Section: {chunk.section} (Doc: {chunk.document_id[:8]})"
            block = f"{header}\n{chunk.content}"
            context_blocks.append(block)

        full_context = "\n\n---\n\n".join(context_blocks)
        total_tokens = max(1, len(full_context) // 4)

        return AssembledContext(
            context_text=full_context,
            citations=citations,
            chunk_count=len(hits),
            total_tokens=total_tokens,
        )

    def verify_claim_citations(
        self,
        generated_response: str,
        citations: list[Citation],
    ) -> dict[str, Any]:
        """
        Validates that references ([1], [2]) in generated text map to valid citations.
        Detects ungrounded claims or hallucinated citation numbers.
        """
        found_refs = {int(r) for r in re.findall(r"\[(\d+)\]", generated_response)}
        valid_indices = {c.citation_index for c in citations}

        hallucinated_refs = list(found_refs - valid_indices)
        validly_cited_refs = list(found_refs.intersection(valid_indices))

        # Check for uncited financial metrics (e.g. $14.2B, 18.5%)
        metric_matches = re.findall(r"(\$\d+(?:\.\d+)?\s*(?:B|M|billion|million)?|\d+(?:\.\d+)?%)", generated_response)

        is_grounded = len(hallucinated_refs) == 0 and len(validly_cited_refs) > 0

        return {
            "is_grounded": is_grounded,
            "cited_indices": sorted(validly_cited_refs),
            "hallucinated_indices": sorted(hallucinated_refs),
            "total_citations_provided": len(citations),
            "financial_metrics_found": metric_matches[:5],
            "traceable_citations": [c.to_dict() for c in citations if c.citation_index in validly_cited_refs],
        }

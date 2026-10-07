from abc import ABC, abstractmethod
from typing import Any


class RetrievalServiceInterface(ABC):
    """
    Contract for scalable hybrid retrieval (OpenSearch 1B+ chunks / local in-memory fallback).
    Enforces strict multi-tenant boundary checks.
    """

    @abstractmethod
    def hybrid_search(
        self,
        tenant_id: str,
        query_text: str,
        query_vector: list[float],
        top_k: int = 10,
        alpha: float = 0.6,
        tickers: list[str] | None = None,
        doc_types: list[str] | None = None,
        fiscal_years: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Executes hybrid (dense vector + lexical BM25) search isolated to tenant_id.
        """
        pass

    @abstractmethod
    def bulk_index_chunks(self, tenant_id: str, chunks: list[dict[str, Any]]) -> int:
        """
        Bulk indexes chunks with routing key.
        """
        pass

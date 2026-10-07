import math
from dataclasses import asdict, dataclass


@dataclass
class RetrievalEvaluationMetrics:
    """Quantitative benchmark evaluation metrics for hybrid RAG retrieval."""
    k: int
    recall_at_k: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float
    context_precision: float
    context_recall: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


class RetrievalEvaluator:
    """
    Standardized benchmark evaluator for RAG retrieval systems.
    Calculates Recall@K, Precision@K, Mean Reciprocal Rank (MRR),
    Normalized Discounted Cumulative Gain (NDCG@K), Context Precision, and Context Recall.
    """

    @staticmethod
    def calculate_metrics(
        retrieved_chunk_ids: list[str],
        relevant_chunk_ids: list[str],
        retrieved_context_text: str = "",
        ground_truth_statements: list[str] | None = None,
        k: int = 5,
    ) -> RetrievalEvaluationMetrics:
        """
        Computes standard retrieval evaluation metrics.
        - retrieved_chunk_ids: list of chunk IDs returned by retrieval engine in rank order.
        - relevant_chunk_ids: ground-truth list of relevant chunk IDs.
        - retrieved_context_text: assembled context string.
        - ground_truth_statements: key factual claims that must be present in retrieved context.
        """
        top_k_retrieved = retrieved_chunk_ids[:k]
        relevant_set = set(relevant_chunk_ids)

        if not relevant_set:
            return RetrievalEvaluationMetrics(
                k=k,
                recall_at_k=1.0 if not top_k_retrieved else 0.0,
                precision_at_k=1.0 if not top_k_retrieved else 0.0,
                mrr=1.0,
                ndcg_at_k=1.0,
                context_precision=1.0,
                context_recall=1.0,
            )

        # 1. Recall@K
        hits_in_top_k = sum(1 for cid in top_k_retrieved if cid in relevant_set)
        recall_at_k = hits_in_top_k / len(relevant_set)

        # 2. Precision@K
        precision_at_k = hits_in_top_k / max(1, len(top_k_retrieved))

        # 3. MRR (Mean Reciprocal Rank)
        mrr = 0.0
        for rank, cid in enumerate(retrieved_chunk_ids, start=1):
            if cid in relevant_set:
                mrr = 1.0 / rank
                break

        # 4. NDCG@K
        dcg = 0.0
        for rank, cid in enumerate(top_k_retrieved, start=1):
            rel = 1.0 if cid in relevant_set else 0.0
            dcg += rel / math.log2(rank + 1)

        # Ideal DCG
        idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant_set), k) + 1))
        ndcg = (dcg / idcg) if idcg > 0.0 else 0.0

        # 5. Context Precision (weighted precision by rank)
        cum_hits = 0
        precision_sum = 0.0
        for rank, cid in enumerate(top_k_retrieved, start=1):
            if cid in relevant_set:
                cum_hits += 1
                precision_sum += cum_hits / rank
        context_precision = (precision_sum / max(1, hits_in_top_k)) if hits_in_top_k > 0 else 0.0

        # 6. Context Recall (fraction of ground truth statements found in text)
        statements = ground_truth_statements or []
        if statements:
            covered = sum(1 for s in statements if s.lower() in retrieved_context_text.lower())
            context_recall = covered / len(statements)
        else:
            context_recall = recall_at_k

        return RetrievalEvaluationMetrics(
            k=k,
            recall_at_k=round(min(1.0, recall_at_k), 4),
            precision_at_k=round(min(1.0, precision_at_k), 4),
            mrr=round(min(1.0, mrr), 4),
            ndcg_at_k=round(min(1.0, ndcg), 4),
            context_precision=round(min(1.0, context_precision), 4),
            context_recall=round(min(1.0, context_recall), 4),
        )

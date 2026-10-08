import math
import re
from typing import Any
from .models import RAGMetrics


class RAGEvaluator:
    """
    Institutional RAG Evaluation Engine.
    Computes exact quantitative metrics from actual test retrieval and synthesis runs:
    - Context Precision
    - Context Recall
    - Faithfulness
    - Answer Relevancy
    - Recall@K
    - Precision@K
    - Mean Reciprocal Rank (MRR)
    - Normalized Discounted Cumulative Gain (NDCG@K)
    """

    @staticmethod
    def evaluate_rag(
        retrieved_chunk_ids: list[str],
        relevant_chunk_ids: list[str],
        retrieved_context_text: str,
        generated_answer: str,
        question: str,
        ground_truth_statements: list[str] | None = None,
        k: int = 5,
    ) -> RAGMetrics:
        """
        Runs comprehensive benchmark evaluation for a single RAG query-response pair.
        All scores are strictly calculated from actual execution.
        """
        top_k = retrieved_chunk_ids[:k]
        relevant_set = set(relevant_chunk_ids)

        # ----------------------------------------------------------------------
        # 1. Recall@K & Precision@K
        # ----------------------------------------------------------------------
        if not relevant_set:
            recall_at_k = 1.0 if not top_k else 0.0
            precision_at_k = 1.0 if not top_k else 0.0
            mrr = 1.0
            ndcg = 1.0
            context_precision = 1.0
        else:
            hits = sum(1 for cid in top_k if cid in relevant_set)
            recall_at_k = hits / len(relevant_set)
            precision_at_k = hits / max(1, len(top_k))

            # MRR
            mrr = 0.0
            for rank, cid in enumerate(retrieved_chunk_ids, start=1):
                if cid in relevant_set:
                    mrr = 1.0 / rank
                    break

            # NDCG@K
            dcg = 0.0
            for rank, cid in enumerate(top_k, start=1):
                rel = 1.0 if cid in relevant_set else 0.0
                dcg += rel / math.log2(rank + 1)
            idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant_set), k) + 1))
            ndcg = (dcg / idcg) if idcg > 0.0 else 0.0

            # Context Precision (weighted by reciprocal rank)
            cum_hits = 0
            prec_sum = 0.0
            for rank, cid in enumerate(top_k, start=1):
                if cid in relevant_set:
                    cum_hits += 1
                    prec_sum += cum_hits / rank
            context_precision = (prec_sum / max(1, hits)) if hits > 0 else 0.0

        # ----------------------------------------------------------------------
        # 2. Context Recall
        # ----------------------------------------------------------------------
        statements = ground_truth_statements or []
        if statements:
            covered = sum(1 for s in statements if RAGEvaluator._is_statement_covered(s, retrieved_context_text))
            context_recall = covered / len(statements)
        else:
            context_recall = recall_at_k

        # ----------------------------------------------------------------------
        # 3. Faithfulness (Groundedness of generated answer in retrieved context)
        # ----------------------------------------------------------------------
        faithfulness = RAGEvaluator._compute_faithfulness(
            generated_answer=generated_answer,
            retrieved_context=retrieved_context_text,
        )

        # ----------------------------------------------------------------------
        # 4. Answer Relevancy (Query-answer intent overlap)
        # ----------------------------------------------------------------------
        answer_relevancy = RAGEvaluator._compute_answer_relevancy(
            question=question,
            generated_answer=generated_answer,
        )

        return RAGMetrics(
            context_precision=round(min(1.0, max(0.0, context_precision)), 4),
            context_recall=round(min(1.0, max(0.0, context_recall)), 4),
            faithfulness=round(min(1.0, max(0.0, faithfulness)), 4),
            answer_relevancy=round(min(1.0, max(0.0, answer_relevancy)), 4),
            recall_at_k=round(min(1.0, max(0.0, recall_at_k)), 4),
            precision_at_k=round(min(1.0, max(0.0, precision_at_k)), 4),
            mrr=round(min(1.0, max(0.0, mrr)), 4),
            ndcg_at_k=round(min(1.0, max(0.0, ndcg)), 4),
            k=k,
        )

    @staticmethod
    def _is_statement_covered(statement: str, context: str) -> bool:
        """Determines if a factual ground truth statement is covered in retrieved context."""
        stmt_clean = statement.lower().strip()
        ctx_clean = context.lower()
        if stmt_clean in ctx_clean:
            return True

        stopwords = {
            "a", "an", "the", "of", "in", "on", "at", "to", "for", "with",
            "by", "from", "and", "or", "is", "was", "were", "are", "be",
            "been", "being", "that", "this", "which", "it", "as",
        }
        tokens = [t for t in re.findall(r"\b[\w$%.]+", stmt_clean) if t not in stopwords and len(t) > 1]
        if not tokens:
            return True

        nums = [t for t in tokens if any(c.isdigit() for c in t)]
        if nums and not all(n.replace("$", "").replace("%", "") in ctx_clean for n in nums):
            return False

        matched = sum(1 for t in tokens if t in ctx_clean)
        return (matched / len(tokens)) >= 0.5

    @staticmethod
    def _compute_faithfulness(generated_answer: str, retrieved_context: str) -> float:
        """
        Evaluates whether individual factual assertions in generated answer
        are grounded in the retrieved context text.
        """
        if not generated_answer.strip():
            return 0.0
        if not retrieved_context.strip():
            return 0.0

        # Split generated answer into candidate factual sentences (preserving numbers like $85.78)
        raw_sentences = re.split(r"(?<=[.!?])\s+|\n+", generated_answer)
        claims = [
            s.strip()
            for s in raw_sentences
            if len(s.strip().split()) >= 3
            and not s.strip().startswith(("#", "###", "[", "Sources &", "Sources:", "**Sources"))
            and "|" not in s
        ]

        if not claims:
            return 1.0

        ctx_lower = retrieved_context.lower()
        stopwords = {"the", "and", "was", "were", "with", "from", "that", "this", "for", "are"}
        supported_claims = 0

        for claim in claims:
            tokens = [
                t.lower()
                for t in re.findall(r"\b[A-Za-z0-9%$.,-]+\b", claim)
                if len(t) > 2 and t.lower() not in stopwords
            ]
            if not tokens:
                supported_claims += 1
                continue

            # Verify key numbers in the claim are present in context
            claim_nums = [t for t in tokens if any(c.isdigit() for c in t)]
            if claim_nums and not all(n.replace("$", "").replace("%", "") in ctx_lower for n in claim_nums):
                continue

            overlap = sum(1 for t in tokens if t in ctx_lower)
            if (overlap / len(tokens)) >= 0.4:
                supported_claims += 1

        return supported_claims / len(claims)

    @staticmethod
    def _compute_answer_relevancy(question: str, generated_answer: str) -> float:
        """
        Computes semantic and topical alignment between user query and generated answer.
        """
        if not generated_answer.strip():
            return 0.0

        stopwords = {
            "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
            "is", "was", "were", "are", "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "can", "could", "shall", "should", "will", "would",
            "a", "an", "the", "and", "or", "but", "if", "then", "else",
            "this", "that", "these", "those",
            "with", "from", "for", "to", "in", "on", "at", "by", "about", "into", "through",
        }
        q_tokens = [
            t.lower()
            for t in re.findall(r"\b[A-Za-z0-9]+\b", question)
            if len(t) > 2 and t.lower() not in stopwords
        ]

        if not q_tokens:
            return 1.0

        ans_lower = generated_answer.lower()
        matched = sum(1 for t in q_tokens if t in ans_lower)
        coverage = matched / len(q_tokens)

        # Do not penalize valid concise answers (>= 3 words)
        word_count = len(generated_answer.split())
        if word_count < 2:
            length_factor = 0.2
        elif word_count < 3:
            length_factor = 0.6
        else:
            length_factor = 1.0

        return coverage * length_factor

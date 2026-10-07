import hashlib
import json
import logging
import math
from functools import lru_cache

from ..config import get_settings
from ..interfaces.embedding import EmbeddingProvider

logger = logging.getLogger(__name__)


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic normalized embedding generator for local dev and test environments.
    Produces 1536-dimensional unit vectors using token-frequency hashing,
    enabling realistic cosine similarity calculations without external API calls.
    """

    def __init__(self, dimension: int = 1536):
        self._dim = dimension

    @property
    def dimension(self) -> int:
        return self._dim

    def _generate_vector(self, text: str) -> list[float]:
        # Hash text words to preserve semantic token overlap
        words = text.lower().split()
        vector = [0.0] * self._dim

        for idx, word in enumerate(words):
            h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            pos = h % self._dim
            weight = 1.0 / math.sqrt(idx + 1)
            vector[pos] += weight

        # Also add full text hash seed
        full_h = hashlib.sha256(text.encode("utf-8")).digest()
        for i in range(min(len(full_h), self._dim)):
            vector[i] += (full_h[i] - 128) / 256.0

        # L2 Normalize
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0.0:
            return [1.0 / math.sqrt(self._dim)] * self._dim
        return [x / norm for x in vector]

    async def embed_query(self, text: str) -> list[float]:
        return self._generate_vector(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._generate_vector(t) for t in texts]


class BedrockTitanEmbeddingProvider(EmbeddingProvider):
    """
    Production Amazon Bedrock Titan Embeddings G1 provider (amazon.titan-embed-text-v1).
    Falls back gracefully to DeterministicEmbeddingProvider in local test environments.
    """

    def __init__(self, region_name: str = "us-east-1", model_id: str = "amazon.titan-embed-text-v1"):
        self.region_name = region_name
        self.model_id = model_id
        self._dim = 1536
        self._bedrock_client = None
        self._fallback = DeterministicEmbeddingProvider(self._dim)

        try:
            import boto3
            self._bedrock_client = boto3.client("bedrock-runtime", region_name=self.region_name)
            logger.info(f"Initialized AWS Bedrock embeddings client for model '{model_id}'")
        except Exception as e:
            logger.warning(f"Failed to initialize AWS Bedrock client ({e}); using deterministic fallback")
            self._bedrock_client = None

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed_query(self, text: str) -> list[float]:
        if not self._bedrock_client:
            return await self._fallback.embed_query(text)

        try:
            body = json.dumps({"inputText": text})
            response = self._bedrock_client.invoke_model(
                modelId=self.model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            resp_body = json.loads(response["body"].read())
            return resp_body.get("embedding", [])
        except Exception as e:
            logger.warning(f"Bedrock embed_query error ({e}); using fallback")
            return await self._fallback.embed_query(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_query(t) for t in texts]


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    """Factory delivering appropriate embedding provider based on environment."""
    settings = get_settings()
    if settings.app_env in ("production", "staging") and getattr(settings, "aws_region", None):
        return BedrockTitanEmbeddingProvider(region_name=settings.aws_region)
    return DeterministicEmbeddingProvider()

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """
    Contract for generating dense vector embeddings for financial texts.
    Supports AWS Bedrock (Titan Embeddings G1 / Cohere Embed) and local test providers.
    """

    async def embed_query(self, text: str) -> list[float]:
        """Generates embedding vector for a single query text."""
        ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Generates embedding vectors for a batch of documents/chunks."""
        ...

    @property
    def dimension(self) -> int:
        """Returns the vector dimensionality (e.g. 1536)."""
        ...

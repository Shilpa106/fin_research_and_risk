from abc import ABC, abstractmethod

from ..models import LLMRequest, LLMResponse


class LLMProvider(ABC):
    """Abstract interface defining the contract for all LLM foundation providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identifier for the provider (e.g., 'aws_bedrock', 'mock_local')."""
        pass

    @abstractmethod
    async def generate(self, request: LLMRequest, model: str) -> LLMResponse:
        """
        Executes a completion request against the foundation model.
        Returns standardized LLMResponse envelope.
        """
        pass

    @abstractmethod
    def is_healthy(self) -> bool:
        """Returns True if provider endpoints and authentication credentials are functional."""
        pass

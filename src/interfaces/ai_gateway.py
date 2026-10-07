from abc import ABC, abstractmethod
from typing import Any


class AIGatewayInterface(ABC):
    """
    Contract for Centralized AI Gateway.
    Decouples business logic from specific cloud LLM vendors (AWS Bedrock, Azure, Local Mock).
    """

    @abstractmethod
    def generate_completion(
        self,
        prompt: str,
        system_prompt: str | None = None,
        use_fast_model: bool = False,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        """
        Generates completion from foundation model with circuit breaking and retries.
        """
        pass

    @abstractmethod
    def generate_embedding(self, text: str, dimensions: int = 1536) -> list[float]:
        """
        Generates dense vector embedding for text.
        """
        pass

    @abstractmethod
    def evaluate_guardrails(self, text: str) -> dict[str, Any]:
        """
        Evaluates text against compliance policies, PII redaction, and prompt injection filters.
        """
        pass

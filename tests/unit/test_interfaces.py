import pytest

from src.interfaces import AIGatewayInterface, CacheManagerInterface, RetrievalServiceInterface


@pytest.mark.unit
def test_ai_gateway_interface_cannot_be_instantiated_directly():
    """Verify abstract base class enforcement."""
    with pytest.raises(TypeError):
        AIGatewayInterface()


@pytest.mark.unit
def test_retrieval_interface_cannot_be_instantiated_directly():
    """Verify retrieval abstract base class enforcement."""
    with pytest.raises(TypeError):
        RetrievalServiceInterface()


@pytest.mark.unit
def test_cache_interface_cannot_be_instantiated_directly():
    """Verify cache abstract base class enforcement."""
    with pytest.raises(TypeError):
        CacheManagerInterface()

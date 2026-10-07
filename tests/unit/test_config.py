import pytest
from pydantic import ValidationError

from src.config.settings import AppSettings


@pytest.mark.unit
def test_default_app_settings():
    """Verify default enterprise settings load properly with valid types."""
    settings = AppSettings()
    assert settings.app_name == "Enterprise Financial Research & Risk Copilot"
    assert settings.port == 8000
    assert settings.rate_limit_rps == 10000
    assert settings.semantic_cache_threshold == 0.96
    assert settings.api_prefix == "/api/v1"


@pytest.mark.unit
def test_environment_validation():
    """Verify app_env validation permits only valid environments."""
    valid_settings = AppSettings(app_env="production")
    assert valid_settings.app_env == "production"

    with pytest.raises(ValidationError):
        AppSettings(app_env="invalid_env_name")


@pytest.mark.unit
def test_secret_masking():
    """Verify secret values are masked in string representations."""
    settings = AppSettings()
    assert "dev-insecure" not in str(settings.jwt_secret_key)
    assert settings.jwt_secret_key.get_secret_value() is not None

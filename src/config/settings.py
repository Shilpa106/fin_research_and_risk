from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """
    Enterprise Configuration Management with Pydantic v2 Settings.
    Strictly validated from environment variables or .env file.
    Secrets are masked via SecretStr.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

    # Application Metadata
    app_name: str = "Enterprise Financial Research & Risk Copilot"
    app_version: str = "1.0.0"
    app_env: str = Field(default="development", description="development | staging | production")
    debug: bool = False
    log_level: str = "INFO"

    # API Server & Networking
    host: str = "0.0.0.0"
    port: int = 8000
    api_prefix: str = "/api/v1"
    allowed_origins: list[str] = ["*"]
    cors_allow_credentials: bool = True

    # Security & JWT Tokens
    jwt_secret_key: SecretStr = Field(
        default=SecretStr("dev-insecure-secret-key-change-in-production-must-be-32-chars-long"),
        description="HMAC secret for signing JWTs. Must be rotated in production via AWS KMS/Secrets Manager.",
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    encryption_key_arn: str | None = None

    # Database (PostgreSQL with Row-Level Security)
    database_url: str = Field(
        default="sqlite+aiosqlite:///./financial_copilot_dev.db",
        description="Async database connection URI (asyncpg for PostgreSQL, aiosqlite for tests/dev)",
    )
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_echo: bool = False

    # Redis (Rate Limiting, Semantic Cache & Sessions)
    redis_url: str = "redis://localhost:6379/0"
    redis_cluster_enabled: bool = False
    rate_limit_rps: int = 10000
    rate_limit_burst: int = 15000
    semantic_cache_enabled: bool = True
    semantic_cache_threshold: float = 0.96

    # OpenSearch Cluster (1B+ Chunks Hybrid Search)
    opensearch_host: str = "localhost"
    opensearch_port: int = 9200
    opensearch_user: str | None = None
    opensearch_password: SecretStr | None = None
    opensearch_use_ssl: bool = False
    opensearch_verify_certs: bool = False
    opensearch_index_chunks: str = "enterprise_financial_chunks_v1"

    # AWS Bedrock Foundation Models & Guardrails
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    bedrock_router_model_id: str = "anthropic.claude-3-5-haiku-20241022-v1:0"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    bedrock_guardrail_id: str | None = None
    bedrock_guardrail_version: str = "DRAFT"

    # Model Context Protocol (MCP) Endpoints
    mcp_sec_edgar_url: str = "http://localhost:8001"
    mcp_market_data_url: str = "http://localhost:8002"

    # Observability & Metrics
    otel_service_name: str = "financial-research-copilot"
    otel_exporter_otlp_endpoint: str | None = None
    prometheus_metrics_enabled: bool = True

    @field_validator("app_env")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        valid_envs = {"development", "staging", "production", "test"}
        if v.lower() not in valid_envs:
            raise ValueError(f"Invalid app_env '{v}'. Must be one of: {valid_envs}")
        return v.lower()

    @field_validator("semantic_cache_threshold")
    @classmethod
    def validate_cache_threshold(cls, v: float) -> float:
        if not (0.80 <= v <= 1.0):
            raise ValueError("Semantic cache threshold must be between 0.80 and 1.0.")
        return v


_settings_instance: AppSettings | None = None


def get_settings() -> AppSettings:
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = AppSettings()
    return _settings_instance

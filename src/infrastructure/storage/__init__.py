from functools import lru_cache

from ...config import get_settings
from ...interfaces.storage import ObjectStorageService
from .local_storage import LocalStorageService
from .s3_storage import S3StorageService


@lru_cache
def get_storage_service() -> ObjectStorageService:
    """Factory providing storage service based on environment settings."""
    settings = get_settings()
    if settings.app_env in ("production", "staging") and settings.aws_s3_bucket:
        return S3StorageService(
            bucket_name=settings.aws_s3_bucket,
            region_name=settings.aws_region,
        )
    return LocalStorageService()


__all__ = ["ObjectStorageService", "LocalStorageService", "S3StorageService", "get_storage_service"]

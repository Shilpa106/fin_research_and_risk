from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass
class StorageMetadata:
    """Metadata for an object in storage."""
    uri: str
    content_type: str
    content_length: int
    checksum_sha256: str
    last_modified: datetime


@runtime_checkable
class ObjectStorageService(Protocol):
    """
    Interface for enterprise object storage operations.
    Supports local filesystem/MinIO development and AWS S3 in production.
    """

    async def upload_file(
        self,
        tenant_id: str,
        file_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Uploads an object to storage and returns its canonical URI.
        Canonical URI format: s3://{bucket}/{tenant_id}/{checksum}_{file_name}
        """
        ...

    async def download_file(self, uri: str) -> bytes:
        """Downloads raw binary bytes from storage given its URI."""
        ...

    async def delete_file(self, uri: str) -> bool:
        """Deletes an object from storage given its URI."""
        ...

    async def get_metadata(self, uri: str) -> StorageMetadata:
        """Retrieves metadata and checksum for a stored object."""
        ...

    async def exists(self, uri: str) -> bool:
        """Checks if an object exists in storage."""
        ...

    def compute_checksum(self, data: bytes) -> str:
        """Computes SHA-256 hexadecimal checksum for data bytes."""
        ...

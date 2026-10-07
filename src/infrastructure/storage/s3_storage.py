import hashlib
import logging
from datetime import datetime

from ...interfaces.storage import ObjectStorageService, StorageMetadata
from .local_storage import LocalStorageService

logger = logging.getLogger(__name__)


class S3StorageService(ObjectStorageService):
    """
    Production AWS S3 object storage implementation.
    Falls back gracefully to LocalStorageService if boto3 is unavailable or AWS credentials are omitted.
    """

    def __init__(
        self,
        bucket_name: str = "financial-documents",
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
    ):
        self.bucket_name = bucket_name
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self._s3_client = None
        self._fallback_local = LocalStorageService(default_bucket=bucket_name)

        try:
            import boto3

            if aws_access_key_id and aws_secret_access_key:
                self._s3_client = boto3.client(
                    "s3",
                    region_name=self.region_name,
                    endpoint_url=self.endpoint_url,
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                )
            else:
                # Use default AWS credential provider chain
                self._s3_client = boto3.client("s3", region_name=self.region_name, endpoint_url=self.endpoint_url)
            logger.info(f"Initialized AWS S3 storage client for bucket '{bucket_name}' in region '{region_name}'")
        except Exception as e:
            logger.warning(f"Failed to initialize AWS S3 client ({e}); using LocalStorageService fallback")
            self._s3_client = None

    def compute_checksum(self, data: bytes) -> str:
        """Computes SHA-256 hexadecimal digest for binary data."""
        return hashlib.sha256(data).hexdigest()

    async def upload_file(
        self,
        tenant_id: str,
        file_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Uploads file to S3 bucket or local fallback."""
        if not self._s3_client:
            return await self._fallback_local.upload_file(tenant_id, file_name, data, content_type)

        checksum = self.compute_checksum(data)
        key = f"{tenant_id}/{checksum[:12]}_{file_name}"
        try:
            self._s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata={
                    "tenant_id": tenant_id,
                    "checksum_sha256": checksum,
                },
            )
            return f"s3://{self.bucket_name}/{key}"
        except Exception as e:
            logger.warning(f"S3 upload error ({e}); writing to local fallback")
            return await self._fallback_local.upload_file(tenant_id, file_name, data, content_type)

    async def download_file(self, uri: str) -> bytes:
        """Downloads file from S3 or local fallback."""
        if not self._s3_client or not uri.startswith("s3://"):
            return await self._fallback_local.download_file(uri)

        # Parse s3://bucket/key
        parts = uri[5:].split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""

        try:
            response = self._s3_client.get_object(Bucket=bucket, Key=key)
            return response["Body"].read()
        except Exception as e:
            logger.warning(f"S3 download error ({e}); attempting local fallback")
            return await self._fallback_local.download_file(uri)

    async def delete_file(self, uri: str) -> bool:
        """Deletes file from S3 or local fallback."""
        if not self._s3_client or not uri.startswith("s3://"):
            return await self._fallback_local.delete_file(uri)

        parts = uri[5:].split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""

        try:
            self._s3_client.delete_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return await self._fallback_local.delete_file(uri)

    async def get_metadata(self, uri: str) -> StorageMetadata:
        """Retrieves metadata for S3 object or local fallback."""
        if not self._s3_client or not uri.startswith("s3://"):
            return await self._fallback_local.get_metadata(uri)

        parts = uri[5:].split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""

        try:
            head = self._s3_client.head_object(Bucket=bucket, Key=key)
            checksum = head.get("Metadata", {}).get("checksum_sha256", "")
            return StorageMetadata(
                uri=uri,
                content_type=head.get("ContentType", "application/octet-stream"),
                content_length=head.get("ContentLength", 0),
                checksum_sha256=checksum,
                last_modified=head.get("LastModified", datetime.utcnow()),
            )
        except Exception:
            return await self._fallback_local.get_metadata(uri)

    async def exists(self, uri: str) -> bool:
        """Checks if object exists in S3 or local fallback."""
        if not self._s3_client or not uri.startswith("s3://"):
            return await self._fallback_local.exists(uri)

        parts = uri[5:].split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""

        try:
            self._s3_client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return await self._fallback_local.exists(uri)

import hashlib
from datetime import datetime
from pathlib import Path

from ...interfaces.storage import ObjectStorageService, StorageMetadata


class LocalStorageService(ObjectStorageService):
    """
    Local filesystem object storage implementation simulating S3 / MinIO.
    Stores files structured by bucket, tenant_id, and checksum-prefixed filename.
    Translates s3:// URIs transparently to local paths.
    """

    def __init__(self, base_dir: str | Path = "./data/storage", default_bucket: str = "financial-documents"):
        self.base_dir = Path(base_dir).resolve()
        self.default_bucket = default_bucket
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def compute_checksum(self, data: bytes) -> str:
        """Computes SHA-256 hexadecimal digest for binary data."""
        return hashlib.sha256(data).hexdigest()

    def _uri_to_path(self, uri: str) -> Path:
        """Converts s3://bucket/tenant_id/filename to local filesystem path."""
        if uri.startswith("s3://"):
            relative_path = uri[5:]  # Remove s3://
        elif uri.startswith("file://"):
            relative_path = uri[7:]
        else:
            relative_path = uri

        return self.base_dir / relative_path

    def _path_to_uri(self, relative_path: str) -> str:
        """Converts relative path to canonical s3:// URI."""
        normalized = relative_path.replace("\\", "/")
        return f"s3://{normalized}"

    async def upload_file(
        self,
        tenant_id: str,
        file_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Saves file to local disk under bucket/tenant_id/ and returns canonical s3 URI."""
        checksum = self.compute_checksum(data)
        safe_filename = Path(file_name).name
        # Format: financial-documents/{tenant_id}/{checksum[:12]}_{safe_filename}
        relative_path = f"{self.default_bucket}/{tenant_id}/{checksum[:12]}_{safe_filename}"
        full_path = self.base_dir / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        full_path.write_bytes(data)
        return self._path_to_uri(relative_path)

    async def download_file(self, uri: str) -> bytes:
        """Reads binary bytes from local storage."""
        full_path = self._uri_to_path(uri)
        if not full_path.exists():
            raise FileNotFoundError(f"Object not found in storage at URI: {uri}")
        return full_path.read_bytes()

    async def delete_file(self, uri: str) -> bool:
        """Deletes file from local storage."""
        full_path = self._uri_to_path(uri)
        if full_path.exists():
            full_path.unlink()
            return True
        return False

    async def get_metadata(self, uri: str) -> StorageMetadata:
        """Returns metadata for the stored object."""
        full_path = self._uri_to_path(uri)
        if not full_path.exists():
            raise FileNotFoundError(f"Object not found at URI: {uri}")

        stat = full_path.stat()
        data = full_path.read_bytes()
        checksum = self.compute_checksum(data)

        ext = full_path.suffix.lower()
        content_type = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".html": "text/html",
            ".htm": "text/html",
            ".csv": "text/csv",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
        }.get(ext, "application/octet-stream")

        return StorageMetadata(
            uri=uri,
            content_type=content_type,
            content_length=stat.st_size,
            checksum_sha256=checksum,
            last_modified=datetime.fromtimestamp(stat.st_mtime),
        )

    async def exists(self, uri: str) -> bool:
        """Checks if file exists at target URI."""
        full_path = self._uri_to_path(uri)
        return full_path.exists()

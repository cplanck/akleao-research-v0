"""Storage abstraction layer for file uploads.

Supports:
- LocalStorage: For local development (files on disk)
- GCSStorage: For production (Google Cloud Storage)

Usage:
    storage = get_storage()
    path = storage.save(project_id, filename, content)
    url = storage.get_download_url(path)
    storage.delete(path)
"""

import os
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import timedelta
from typing import BinaryIO


class StorageBackend(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    def save(self, project_id: str, filename: str, content: bytes) -> str:
        """Save file content and return the storage path/key."""
        pass

    @abstractmethod
    def get_download_url(self, path: str, filename: str | None = None) -> str:
        """Get a URL for downloading the file.

        For local storage, returns a relative path for FileResponse.
        For GCS, returns a signed URL.
        """
        pass

    @abstractmethod
    def get_file_path(self, path: str) -> str | None:
        """Get local file path if available (for local storage only).

        Returns None for cloud storage backends.
        """
        pass

    @abstractmethod
    def read(self, path: str) -> bytes:
        """Read file contents."""
        pass

    @abstractmethod
    def delete(self, path: str) -> bool:
        """Delete a file. Returns True if deleted, False if not found."""
        pass

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if a file exists."""
        pass


class LocalStorage(StorageBackend):
    """Local filesystem storage for development."""

    def __init__(self, base_dir: str = "uploads"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)

    def save(self, project_id: str, filename: str, content: bytes) -> str:
        """Save file to local filesystem."""
        project_dir = self.base_dir / project_id
        project_dir.mkdir(exist_ok=True)

        file_path = project_dir / filename
        with open(file_path, "wb") as f:
            f.write(content)

        return str(file_path)

    def get_download_url(self, path: str, filename: str | None = None) -> str:
        """Return the local file path (used with FileResponse)."""
        return path

    def get_file_path(self, path: str) -> str | None:
        """Return the local file path."""
        if os.path.exists(path):
            return path
        return None

    def read(self, path: str) -> bytes:
        """Read file from local filesystem."""
        with open(path, "rb") as f:
            return f.read()

    def delete(self, path: str) -> bool:
        """Delete file from local filesystem."""
        try:
            if os.path.exists(path):
                os.remove(path)
                return True
            return False
        except Exception:
            return False

    def exists(self, path: str) -> bool:
        """Check if file exists on local filesystem."""
        return os.path.exists(path)


class GCSStorage(StorageBackend):
    """Google Cloud Storage backend for production."""

    def __init__(self, bucket_name: str):
        from google.cloud import storage as gcs

        self.bucket_name = bucket_name
        self.client = gcs.Client()
        self.bucket = self.client.bucket(bucket_name)

    def _get_blob_name(self, project_id: str, filename: str) -> str:
        """Generate blob name (path in GCS)."""
        return f"uploads/{project_id}/{filename}"

    def save(self, project_id: str, filename: str, content: bytes) -> str:
        """Save file to GCS and return the blob name."""
        blob_name = self._get_blob_name(project_id, filename)
        blob = self.bucket.blob(blob_name)
        blob.upload_from_string(content)
        return blob_name

    def get_download_url(self, path: str, filename: str | None = None) -> str:
        """Generate a signed URL for downloading.

        URL is valid for 1 hour.
        """
        blob = self.bucket.blob(path)

        # Set content disposition if filename provided
        response_disposition = None
        if filename:
            response_disposition = f'attachment; filename="{filename}"'

        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(hours=1),
            method="GET",
            response_disposition=response_disposition,
        )
        return url

    def get_file_path(self, path: str) -> str | None:
        """GCS doesn't have local file paths."""
        return None

    def read(self, path: str) -> bytes:
        """Read file from GCS."""
        blob = self.bucket.blob(path)
        return blob.download_as_bytes()

    def delete(self, path: str) -> bool:
        """Delete file from GCS."""
        try:
            blob = self.bucket.blob(path)
            blob.delete()
            return True
        except Exception:
            return False

    def exists(self, path: str) -> bool:
        """Check if file exists in GCS."""
        blob = self.bucket.blob(path)
        return blob.exists()


# Singleton storage instance
_storage_instance: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Get the configured storage backend.

    Returns GCSStorage if GCS_BUCKET is set, otherwise LocalStorage.
    """
    global _storage_instance

    if _storage_instance is None:
        gcs_bucket = os.getenv("GCS_BUCKET")
        if gcs_bucket:
            print(f"[Storage] Using GCS bucket: {gcs_bucket}")
            _storage_instance = GCSStorage(gcs_bucket)
        else:
            print("[Storage] Using local filesystem storage")
            _storage_instance = LocalStorage()

    return _storage_instance


def reset_storage():
    """Reset the storage singleton (for testing)."""
    global _storage_instance
    _storage_instance = None

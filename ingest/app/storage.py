"""Audio storage: a Protocol, a Supabase Storage implementation, and an in-memory fake."""

from __future__ import annotations

from typing import Any, Protocol


class AudioStore(Protocol):
    bucket: str

    def upload(self, path: str, data: bytes, content_type: str) -> None: ...

    def signed_url(self, path: str, expires_in: int = 3600) -> str: ...


class SupabaseAudioStore:
    """Supabase Storage (private bucket). supabase-py is used ONLY for Storage."""

    def __init__(self, url: str, service_role_key: str, bucket: str = "meeting-audio") -> None:
        from supabase import create_client  # lazy: keeps tests/imports light

        self.bucket = bucket
        self._client: Any = create_client(url, service_role_key)

    def upload(self, path: str, data: bytes, content_type: str) -> None:
        # upsert so a retry after a partial failure does not error on an existing object.
        self._client.storage.from_(self.bucket).upload(
            path, data, {"content-type": content_type, "upsert": "true"}
        )

    def signed_url(self, path: str, expires_in: int = 3600) -> str:
        res = self._client.storage.from_(self.bucket).create_signed_url(path, expires_in)
        return str(res["signedURL"])


class InMemoryAudioStore:
    """Test fake."""

    def __init__(self, bucket: str = "meeting-audio") -> None:
        self.bucket = bucket
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.upload_calls = 0

    def upload(self, path: str, data: bytes, content_type: str) -> None:
        self.upload_calls += 1
        self.objects[path] = (data, content_type)

    def signed_url(self, path: str, expires_in: int = 3600) -> str:
        if path not in self.objects:
            raise KeyError(path)
        return f"memory://{self.bucket}/{path}?expires_in={expires_in}"

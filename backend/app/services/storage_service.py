from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.core.config import settings


@dataclass(frozen=True)
class StoredObject:
    backend: str
    bucket: str
    path: str


class StorageService(ABC):
    @abstractmethod
    def upload_private_file(
        self,
        *,
        path: str,
        content: bytes,
        content_type: str,
    ) -> StoredObject:
        raise NotImplementedError

    @abstractmethod
    def create_signed_url(self, *, path: str, expires_in_seconds: int) -> str:
        raise NotImplementedError


class SupabaseStorageService(StorageService):
    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        bucket: str,
    ) -> None:
        self.supabase_url = supabase_url.rstrip("/")
        self.service_role_key = service_role_key
        self.bucket = bucket

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.service_role_key}",
            "apikey": self.service_role_key,
        }

    def upload_private_file(
        self,
        *,
        path: str,
        content: bytes,
        content_type: str,
    ) -> StoredObject:
        encoded_path = quote(path, safe="/")
        url = f"{self.supabase_url}/storage/v1/object/{self.bucket}/{encoded_path}"
        headers = {
            **self._headers,
            "Content-Type": content_type,
            "x-upsert": "false",
        }
        response = httpx.post(url, headers=headers, content=content, timeout=60)
        response.raise_for_status()
        return StoredObject(backend="supabase", bucket=self.bucket, path=path)

    def create_signed_url(self, *, path: str, expires_in_seconds: int) -> str:
        encoded_path = quote(path, safe="/")
        url = f"{self.supabase_url}/storage/v1/object/sign/{self.bucket}/{encoded_path}"
        response = httpx.post(
            url,
            headers={**self._headers, "Content-Type": "application/json"},
            json={"expiresIn": expires_in_seconds},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        signed_url = data.get("signedURL") or data.get("signedUrl") or data.get("signed_url")
        if not signed_url:
            raise RuntimeError("Supabase did not return a signed URL")
        if signed_url.startswith("http"):
            return signed_url
        return f"{self.supabase_url}/storage/v1{signed_url}"


def get_storage_service() -> StorageService:
    return SupabaseStorageService(
        supabase_url=settings.SUPABASE_URL,
        service_role_key=settings.SUPABASE_SERVICE_ROLE_KEY,
        bucket=settings.SUPABASE_STORAGE_BUCKET,
    )

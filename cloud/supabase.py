from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from cloud.config import CloudConfig


class SupabaseClient:
    def __init__(self, config: CloudConfig) -> None:
        self.config = config

    def _headers(
        self,
        *,
        prefer: str | None = None,
        content_type: str = "application/json",
    ) -> dict[str, str]:
        headers = {
            "apikey": self.config.supabase_service_role_key,
            "Authorization": f"Bearer {self.config.supabase_service_role_key}",
            "Content-Type": content_type,
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        request = Request(url, data=body, headers=headers or self._headers(), method=method)
        try:
            with urlopen(request, timeout=30) as response:
                return response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Supabase {method} {url} failed: {exc.code} {detail}") from exc

    def upsert(self, table: str, rows: list[dict[str, Any]] | dict[str, Any]) -> None:
        payload = rows if isinstance(rows, list) else [rows]
        url = f"{self.config.supabase_url}/rest/v1/{table}"
        body = json.dumps(payload).encode()
        self._request(
            "POST",
            url,
            body=body,
            headers=self._headers(prefer="resolution=merge-duplicates"),
        )

    def select(
        self,
        table: str,
        *,
        select: str = "*",
        filters: dict[str, str] | None = None,
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, str] = {"select": select}
        if filters:
            query.update(filters)
        if order:
            query["order"] = order
        if limit is not None:
            query["limit"] = str(limit)
        url = f"{self.config.supabase_url}/rest/v1/{table}?{urlencode(query)}"
        data = self._request("GET", url)
        return json.loads(data.decode("utf-8"))

    def upload_file(self, local_path: Path, object_path: str, *, content_type: str) -> str:
        quoted_path = quote(object_path.lstrip("/"))
        url = (
            f"{self.config.supabase_url}/storage/v1/object/"
            f"{self.config.supabase_bucket}/{quoted_path}?upsert=true"
        )
        headers = self._headers(content_type=content_type)
        self._request("POST", url, body=local_path.read_bytes(), headers=headers)
        return f"{self.config.supabase_bucket}/{object_path}"

    def signed_url(self, object_path: str, *, expires_in: int = 3600) -> str | None:
        quoted_path = quote(object_path.lstrip("/"))
        url = (
            f"{self.config.supabase_url}/storage/v1/object/sign/"
            f"{self.config.supabase_bucket}/{quoted_path}"
        )
        body = json.dumps({"expiresIn": expires_in}).encode()
        try:
            data = self._request("POST", url, body=body)
        except RuntimeError:
            return None
        payload = json.loads(data.decode("utf-8"))
        signed_url = payload.get("signedURL")
        if not isinstance(signed_url, str):
            return None
        return f"{self.config.supabase_url}/storage/v1{signed_url}"

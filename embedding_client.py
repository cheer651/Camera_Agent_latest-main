from __future__ import annotations

from typing import Any

import requests


class EmbeddingClient:
    def __init__(
        self,
        base_url: str,
        endpoint: str = "/embed",
        model: str = "",
        timeout_seconds: int = 60,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")
        self.endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        self.model = str(model or "").strip()
        self.timeout_seconds = timeout_seconds
        self.embed_url = self.base_url + self.endpoint
        self.last_error = ""

    def test_connection(self) -> bool:
        if not self.enabled:
            self.last_error = "disabled"
            return False
        health_url = self.base_url + ("/api/tags" if self._is_ollama_embed_endpoint() else "/health")
        try:
            response = requests.get(health_url, timeout=5)
            ok = response.ok
            if not ok:
                self.last_error = f"health_check_failed: HTTP {response.status_code}"
            else:
                self.last_error = ""
            return ok
        except requests.RequestException as exc:
            self.last_error = str(exc)
            return False

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.enabled:
            raise RuntimeError("Embedding client is disabled.")

        normalized = [str(text).strip() for text in texts if str(text).strip()]
        if not normalized:
            return []

        request_payload: dict[str, Any]
        if self._is_ollama_embed_endpoint():
            if not self.model:
                raise RuntimeError("Ollama embedding model is not configured.")
            request_payload = {"model": self.model, "input": normalized}
        else:
            request_payload = {"inputs": normalized}

        try:
            response = requests.post(
                self.embed_url,
                json=request_payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            self.last_error = f"Embedding service request failed: {exc}"
            raise RuntimeError(f"Embedding service request failed: {exc}") from exc

        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise RuntimeError("Embedding service returned invalid JSON.") from exc

        if isinstance(payload, dict) and isinstance(payload.get("embeddings"), list):
            return list(payload["embeddings"])
        if not isinstance(payload, list):
            raise RuntimeError("Embedding service returned an unexpected payload.")
        return payload

    def embed_text(self, text: str) -> list[float]:
        embeddings = self.embed_texts([text])
        return embeddings[0] if embeddings else []

    def _is_ollama_embed_endpoint(self) -> bool:
        return self.endpoint.rstrip("/") == "/api/embed"

from __future__ import annotations

import socket
from typing import Any
from urllib.parse import urlparse

import requests


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5:latest",
        generate_endpoint: str = "/api/generate",
        timeout_seconds: int = 120,
        keep_alive: str = "30m",
        temperature: float = 0.2,
        num_ctx: int = 1024,
        enabled: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.generate_url = self.base_url + self._normalize_path(generate_endpoint)
        self.timeout_seconds = max(5, int(timeout_seconds))
        self.keep_alive = keep_alive.strip()
        self.temperature = float(temperature)
        self.num_ctx = max(512, int(num_ctx or 1024))
        self.enabled = bool(enabled and self.model)
        self.last_error = ""

    @staticmethod
    def _normalize_path(path: str) -> str:
        if not path:
            return ""
        return path if path.startswith("/") else f"/{path}"

    def test_connection(self, timeout: int = 3) -> bool:
        if not self.enabled:
            return False

        parsed = urlparse(self.base_url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not host:
            self.last_error = "invalid_base_url"
            return False

        try:
            socket.create_connection((host, port), timeout=timeout).close()
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=timeout)
            if not response.ok:
                self.last_error = f"HTTP {response.status_code} {response.text[:200]}".strip()
                return False
        except requests.RequestException as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False

        self.last_error = ""
        return True

    def generate(self, prompt: str, timeout: int | None = None, temperature: float | None = None) -> str | None:
        if not self.enabled:
            self.last_error = "disabled"
            return None

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": self.temperature if temperature is None else float(temperature),
                "num_ctx": self.num_ctx,
            },
        }

        try:
            response = requests.post(
                self.generate_url,
                json=payload,
                timeout=timeout or self.timeout_seconds,
            )
        except requests.RequestException as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

        if not response.ok:
            self.last_error = f"HTTP {response.status_code} {response.text[:200]}".strip()
            return None

        try:
            data = response.json()
        except ValueError:
            text = response.text.strip()
            if text:
                self.last_error = ""
                return text
            self.last_error = "invalid_json_response"
            return None

        if isinstance(data, dict):
            text = str(data.get("response", "")).strip()
            if text:
                self.last_error = ""
                return text

        self.last_error = "empty_response"
        return None

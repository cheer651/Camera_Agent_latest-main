from __future__ import annotations

import base64
import os
import socket
from typing import Any
from urllib.parse import urlparse

import requests


class LLMClient:
    def __init__(
        self,
        server_ip: str | None = None,
        port: int = 5120,
        base_url: str | None = None,
        provider: str = "legacy_form",
        model: str = "",
        api_key: str = "$empty",
        photo_endpoint: str = "/photo",
        chat_endpoint: str = "/chat",
        chat_completions_endpoint: str = "/chat/completions",
        timeout_seconds: int = 120,
        max_tokens: int = 8192,
        temperature: float = 1.0,
        top_p: float = 0.95,
        presence_penalty: float = 1.5,
        top_k: int = 20,
    ) -> None:
        if base_url:
            self.base_url = base_url.rstrip("/")
        elif server_ip:
            self.base_url = f"http://{server_ip}:{port}"
        else:
            raise ValueError("Either base_url or server_ip must be provided.")

        self.provider = str(provider or "legacy_form").strip().lower()
        self.model = str(model or "").strip()
        self.api_key = str(api_key or "$empty")
        self.timeout_seconds = int(timeout_seconds)
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        self.top_p = float(top_p)
        self.presence_penalty = float(presence_penalty)
        self.top_k = int(top_k)
        self.photo_url = self.base_url + self._normalize_path(photo_endpoint)
        self.chat_url = self.base_url + self._normalize_path(chat_endpoint) if chat_endpoint else ""
        self.chat_completions_url = (
            self.base_url + self._normalize_path(chat_completions_endpoint) if chat_completions_endpoint else ""
        )
        self.last_error = ""

    @staticmethod
    def _normalize_path(path: str) -> str:
        if not path:
            return ""
        return path if path.startswith("/") else f"/{path}"

    def test_connection(self, timeout: int = 3) -> bool:
        parsed = urlparse(self.base_url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not host:
            return False

        try:
            socket.create_connection((host, port), timeout=timeout).close()
            return True
        except OSError:
            return False

    def analyze_frame(self, image_path: str, prompt_text: str) -> str | None:
        if not os.path.exists(image_path):
            self.last_error = f"image_not_found:{image_path}"
            return None

        if self.provider == "openai_compatible":
            return self._analyze_frame_openai_compatible(image_path, prompt_text)
        return self._analyze_frame_legacy_form(image_path, prompt_text)

    def _analyze_frame_legacy_form(self, image_path: str, prompt_text: str) -> str | None:
        try:
            with open(image_path, "rb") as image_file:
                files = {
                    "file": (os.path.basename(image_path), image_file, "image/jpeg"),
                    "prompt": ("prompt.txt", prompt_text.encode("utf-8"), "text/plain"),
                }
                response = requests.post(self.photo_url, files=files, timeout=self.timeout_seconds)
                if response.ok:
                    self.last_error = ""
                    return response.text.strip()
                body = response.text.strip()
                self.last_error = f"HTTP {response.status_code} {body[:200]}".strip()
                return f"__ERROR__: {self.last_error}"
        except requests.RequestException as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return f"__ERROR__: {self.last_error}"

    def _analyze_frame_openai_compatible(self, image_path: str, prompt_text: str) -> str | None:
        if not self.chat_completions_url:
            self.last_error = "chat_completions_endpoint_not_configured"
            return f"__ERROR__: {self.last_error}"
        if not self.model:
            self.last_error = "model_not_configured"
            return f"__ERROR__: {self.last_error}"

        try:
            with open(image_path, "rb") as image_file:
                encoded_image = base64.b64encode(image_file.read()).decode("utf-8")
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return f"__ERROR__: {self.last_error}"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"},
                        },
                        {
                            "type": "text",
                            "text": prompt_text,
                        },
                    ],
                }
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "presence_penalty": self.presence_penalty,
            "top_k": self.top_k,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                self.chat_completions_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            if not response.ok:
                body = response.text.strip()
                self.last_error = f"HTTP {response.status_code} {body[:200]}".strip()
                return f"__ERROR__: {self.last_error}"

            data: Any = response.json()
            content = self._extract_openai_content(data)
            if content:
                self.last_error = ""
                return content.strip()

            self.last_error = "empty_response_content"
            return f"__ERROR__: {self.last_error}"
        except requests.RequestException as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return f"__ERROR__: {self.last_error}"
        except ValueError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return f"__ERROR__: {self.last_error}"

    @staticmethod
    def _extract_openai_content(data: Any) -> str:
        if not isinstance(data, dict):
            return str(data or "").strip()

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return str(first_choice or "").strip()

        message = first_choice.get("message", {})
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                        parts.append(str(item["text"]).strip())
                    elif isinstance(item, str):
                        parts.append(item.strip())
                return "\n".join(part for part in parts if part).strip()
        return ""

    def chat(self, prompt_text: str, timeout: int = 90) -> str | None:
        if self.provider == "openai_compatible":
            return self._chat_openai_compatible(prompt_text, timeout=timeout)
        if not self.chat_url:
            return None

        payload_candidates = [
            {"prompt": prompt_text},
            {"question": prompt_text},
            {"message": prompt_text},
        ]

        for payload in payload_candidates:
            try:
                response = requests.post(self.chat_url, json=payload, timeout=timeout)
            except requests.RequestException as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                return None

            if not response.ok:
                self.last_error = f"HTTP {response.status_code} {response.text[:200]}".strip()
                continue

            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                try:
                    data: Any = response.json()
                except ValueError:
                    self.last_error = ""
                    return response.text.strip() or None

                if isinstance(data, dict):
                    for key in ("answer", "response", "content", "text", "message"):
                        if data.get(key):
                            self.last_error = ""
                            return str(data[key]).strip()
                self.last_error = ""
                return str(data).strip()

            text = response.text.strip()
            if text:
                self.last_error = ""
                return text

        return None

    def _chat_openai_compatible(self, prompt_text: str, timeout: int = 90) -> str | None:
        if not self.chat_completions_url or not self.model:
            return None

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt_text}],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "presence_penalty": self.presence_penalty,
            "top_k": self.top_k,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(self.chat_completions_url, json=payload, headers=headers, timeout=timeout)
            if not response.ok:
                self.last_error = f"HTTP {response.status_code} {response.text[:200]}".strip()
                return None

            data: Any = response.json()
            content = self._extract_openai_content(data)
            if content:
                self.last_error = ""
                return content
        except (requests.RequestException, ValueError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
        return None

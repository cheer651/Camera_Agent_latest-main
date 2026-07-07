from __future__ import annotations

from typing import Any

import requests


class QdrantVectorStore:
    def __init__(
        self,
        base_url: str,
        collection_name: str,
        vector_size: int,
        distance: str = "Cosine",
        enabled: bool = True,
        create_payload_indexes: bool = True,
    ) -> None:
        self.enabled = enabled
        self.base_url = base_url.rstrip("/")
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.distance = distance
        self.create_payload_indexes = create_payload_indexes

    @property
    def collection_url(self) -> str:
        return f"{self.base_url}/collections/{self.collection_name}"

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = requests.request(method, f"{self.base_url}{path}", timeout=30, **kwargs)
        response.raise_for_status()
        return response.json()

    def test_connection(self) -> bool:
        if not self.enabled:
            return False
        try:
            response = requests.get(f"{self.base_url}/collections", timeout=5)
            return response.ok
        except requests.RequestException:
            return False

    def ensure_collection(self) -> None:
        if not self.enabled:
            return

        try:
            requests.get(self.collection_url, timeout=10).raise_for_status()
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 404:
                raise RuntimeError(f"Failed to inspect Qdrant collection: {exc}") from exc
            self._create_collection()
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to reach Qdrant: {exc}") from exc

        if self.create_payload_indexes:
            self._ensure_payload_indexes()

    def _create_collection(self) -> None:
        payload = {
            "vectors": {
                "size": self.vector_size,
                "distance": self.distance,
            }
        }
        try:
            requests.put(self.collection_url, json=payload, timeout=30).raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to create Qdrant collection: {exc}") from exc

    def _ensure_payload_indexes(self) -> None:
        fields = {
            "camera_id": "keyword",
            "camera_name": "keyword",
            "event_date": "keyword",
            "event_hour": "integer",
            "period_name": "keyword",
            "risk_level": "keyword",
            "anomaly_type": "keyword",
            "event_group_id": "keyword",
            "event_frame_count": "integer",
        }
        for field_name, field_schema in fields.items():
            path = f"/collections/{self.collection_name}/index"
            payload = {"field_name": field_name, "field_schema": field_schema}
            try:
                requests.put(f"{self.base_url}{path}", json=payload, timeout=15).raise_for_status()
            except requests.RequestException:
                continue

    def upsert_points(self, points: list[dict[str, Any]]) -> None:
        if not self.enabled or not points:
            return
        payload = {"points": points}
        try:
            requests.put(
                f"{self.collection_url}/points?wait=true",
                json=payload,
                timeout=60,
            ).raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to upsert Qdrant points: {exc}") from exc

    def search(
        self,
        query_vector: list[float],
        limit: int = 12,
        query_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not self.enabled or not query_vector:
            return []

        payload: dict[str, Any] = {
            "vector": query_vector,
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
        }
        if query_filter:
            payload["filter"] = query_filter

        try:
            response = requests.post(
                f"{self.collection_url}/points/search",
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Failed to search Qdrant: {exc}") from exc

        data = response.json()
        return list(data.get("result", []))

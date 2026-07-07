from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


RiskLevel = Literal["High", "Medium", "Low"]
SourceType = Literal["rtsp", "http", "file", "index"]
CaptureMode = Literal["local_direct"]


class ValidationError(ValueError):
    pass


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y", "detected", "abnormal", "anomaly", "是", "异常"}


def _normalize_risk_level(value: object) -> str:
    if value is None:
        return "Low"

    text = str(value).strip().lower()
    mapping = {
        "high": "High",
        "medium": "Medium",
        "low": "Low",
        "critical": "High",
        "normal": "Low",
        "none": "Low",
        "high risk": "High",
        "medium risk": "Medium",
        "low risk": "Low",
        "high-risk": "High",
        "medium-risk": "Medium",
        "low-risk": "Low",
        "high risk level": "High",
        "medium risk level": "Medium",
        "low risk level": "Low",
        "高": "High",
        "中": "Medium",
        "低": "Low",
        "高风险": "High",
        "中风险": "Medium",
        "低风险": "Low",
    }
    return mapping.get(text, "Low")


@dataclass
class CameraConfig:
    camera_id: str
    name: str
    source_type: SourceType = "rtsp"
    source: str = ""
    fallback_file: str = ""
    enabled: bool = True
    preview_enabled: bool = True
    description: str = ""

    @property
    def effective_source(self) -> str:
        return self.source or self.fallback_file

    @classmethod
    def model_validate(cls, payload: dict) -> "CameraConfig":
        camera_id = str(payload.get("camera_id", "")).strip()
        name = str(payload.get("name", "")).strip()
        if not camera_id:
            raise ValidationError("camera_id is required")
        if not name:
            raise ValidationError("name is required")
        return cls(
            camera_id=camera_id,
            name=name,
            source_type=str(payload.get("source_type", "rtsp")),
            source=str(payload.get("source", "")),
            fallback_file=str(payload.get("fallback_file", "")),
            enabled=bool(payload.get("enabled", True)),
            preview_enabled=bool(payload.get("preview_enabled", True)),
            description=str(payload.get("description", "")),
        )

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class ServerConfig:
    provider: str = "legacy_form"
    base_url: str = "http://100.106.1.46:5120"
    photo_endpoint: str = "/photo"
    chat_endpoint: str = "/chat"
    model: str = ""
    api_key: str = "$empty"
    chat_completions_endpoint: str = "/chat/completions"
    timeout_seconds: int = 120
    max_tokens: int = 8192
    temperature: float = 1.0
    top_p: float = 0.95
    presence_penalty: float = 1.5
    top_k: int = 20

    @classmethod
    def model_validate(cls, payload: dict | None) -> "ServerConfig":
        payload = payload or {}
        return cls(
            provider=str(payload.get("provider", cls.provider)),
            base_url=str(payload.get("base_url", cls.base_url)).rstrip("/"),
            photo_endpoint=str(payload.get("photo_endpoint", cls.photo_endpoint)),
            chat_endpoint=str(payload.get("chat_endpoint", cls.chat_endpoint)),
            model=str(payload.get("model", cls.model)),
            api_key=str(payload.get("api_key", cls.api_key)),
            chat_completions_endpoint=str(
                payload.get("chat_completions_endpoint", cls.chat_completions_endpoint)
            ),
            timeout_seconds=int(payload.get("timeout_seconds", cls.timeout_seconds)),
            max_tokens=int(payload.get("max_tokens", cls.max_tokens)),
            temperature=float(payload.get("temperature", cls.temperature)),
            top_p=float(payload.get("top_p", cls.top_p)),
            presence_penalty=float(payload.get("presence_penalty", cls.presence_penalty)),
            top_k=int(payload.get("top_k", cls.top_k)),
        )

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class TextLLMConfig:
    enabled: bool = True
    provider: str = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:latest"
    generate_endpoint: str = "/api/generate"
    timeout_seconds: int = 120
    keep_alive: str = "30m"
    temperature: float = 0.2
    num_ctx: int = 1024

    @classmethod
    def model_validate(cls, payload: dict | None) -> "TextLLMConfig":
        payload = payload or {}
        return cls(
            enabled=bool(payload.get("enabled", cls.enabled)),
            provider=str(payload.get("provider", cls.provider)),
            base_url=str(payload.get("base_url", cls.base_url)).rstrip("/"),
            model=str(payload.get("model", cls.model)),
            generate_endpoint=str(payload.get("generate_endpoint", cls.generate_endpoint)),
            timeout_seconds=int(payload.get("timeout_seconds", cls.timeout_seconds)),
            keep_alive=str(payload.get("keep_alive", cls.keep_alive)),
            temperature=float(payload.get("temperature", cls.temperature)),
            num_ctx=int(payload.get("num_ctx", cls.num_ctx)),
        )

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class StorageConfig:
    base_dir: str = r"D:\camera_agent_data"
    database_path: str = r"D:\camera_agent_data\security_events.db"
    clip_duration_seconds: int = 30
    frame_sample_rate: int = 8
    similarity_threshold: float = 0.78
    min_frame_gap_seconds: float = 0.5
    extractor_scale_factor: float = 0.55
    motion_score_threshold: float = 1.8
    camera_capture_workers: int = 2
    analysis_workers: int = 2
    event_merge_time_gap_seconds: float = 2.5
    event_merge_similarity_threshold: float = 0.45
    event_max_duration_seconds: float = 20.0
    max_representative_frames: int = 2
    daily_summary_time: str = "20:00"
    enable_daily_summary_scheduler: bool = False

    @classmethod
    def model_validate(cls, payload: dict | None) -> "StorageConfig":
        payload = payload or {}
        return cls(
            base_dir=str(payload.get("base_dir", cls.base_dir)),
            database_path=str(payload.get("database_path", cls.database_path)),
            clip_duration_seconds=int(payload.get("clip_duration_seconds", cls.clip_duration_seconds)),
            frame_sample_rate=int(payload.get("frame_sample_rate", cls.frame_sample_rate)),
            similarity_threshold=float(payload.get("similarity_threshold", cls.similarity_threshold)),
            min_frame_gap_seconds=float(payload.get("min_frame_gap_seconds", cls.min_frame_gap_seconds)),
            extractor_scale_factor=float(payload.get("extractor_scale_factor", cls.extractor_scale_factor)),
            motion_score_threshold=float(payload.get("motion_score_threshold", cls.motion_score_threshold)),
            camera_capture_workers=int(payload.get("camera_capture_workers", cls.camera_capture_workers)),
            analysis_workers=int(payload.get("analysis_workers", cls.analysis_workers)),
            event_merge_time_gap_seconds=float(
                payload.get("event_merge_time_gap_seconds", cls.event_merge_time_gap_seconds)
            ),
            event_merge_similarity_threshold=float(
                payload.get("event_merge_similarity_threshold", cls.event_merge_similarity_threshold)
            ),
            event_max_duration_seconds=float(
                payload.get("event_max_duration_seconds", cls.event_max_duration_seconds)
            ),
            max_representative_frames=int(payload.get("max_representative_frames", cls.max_representative_frames)),
            daily_summary_time=str(payload.get("daily_summary_time", cls.daily_summary_time)),
            enable_daily_summary_scheduler=bool(payload.get("enable_daily_summary_scheduler", cls.enable_daily_summary_scheduler)),
        )

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class FeishuConfig:
    app_id: str = ""
    app_secret: str = ""
    chat_id: str = ""
    webhook_url: str = ""

    @classmethod
    def model_validate(cls, payload: dict | None) -> "FeishuConfig":
        payload = payload or {}
        return cls(
            app_id=str(payload.get("app_id", "")),
            app_secret=str(payload.get("app_secret", "")),
            chat_id=str(payload.get("chat_id", "")),
            webhook_url=str(payload.get("webhook_url", "")),
        )

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class EmbeddingConfig:
    enabled: bool = True
    base_url: str = "http://127.0.0.1:8080"
    endpoint: str = "/embed"
    model: str = ""
    timeout_seconds: int = 60

    @classmethod
    def model_validate(cls, payload: dict | None) -> "EmbeddingConfig":
        payload = payload or {}
        return cls(
            enabled=bool(payload.get("enabled", cls.enabled)),
            base_url=str(payload.get("base_url", cls.base_url)).rstrip("/"),
            endpoint=str(payload.get("endpoint", cls.endpoint)),
            model=str(payload.get("model", cls.model)),
            timeout_seconds=int(payload.get("timeout_seconds", cls.timeout_seconds)),
        )

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class VectorStoreConfig:
    enabled: bool = True
    provider: str = "qdrant"
    base_url: str = "http://127.0.0.1:6333"
    collection_name: str = "security_events"
    vector_size: int = 1024
    distance: str = "Cosine"
    search_limit: int = 12
    create_payload_indexes: bool = True

    @classmethod
    def model_validate(cls, payload: dict | None) -> "VectorStoreConfig":
        payload = payload or {}
        return cls(
            enabled=bool(payload.get("enabled", cls.enabled)),
            provider=str(payload.get("provider", cls.provider)),
            base_url=str(payload.get("base_url", cls.base_url)).rstrip("/"),
            collection_name=str(payload.get("collection_name", cls.collection_name)),
            vector_size=int(payload.get("vector_size", cls.vector_size)),
            distance=str(payload.get("distance", cls.distance)),
            search_limit=int(payload.get("search_limit", cls.search_limit)),
            create_payload_indexes=bool(payload.get("create_payload_indexes", cls.create_payload_indexes)),
        )

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class CaptureConfig:
    mode: CaptureMode = "local_direct"

    @classmethod
    def model_validate(cls, payload: dict | None) -> "CaptureConfig":
        payload = payload or {}
        mode = str(payload.get("mode", cls.mode))
        if mode != "local_direct":
            mode = "local_direct"
        return cls(mode=mode)

    def model_dump(self) -> dict:
        return asdict(self)


@dataclass
class SystemConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    text_llm: TextLLMConfig = field(default_factory=TextLLMConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    vector_store: VectorStoreConfig = field(default_factory=VectorStoreConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    cameras: list[CameraConfig] = field(default_factory=list)

    @classmethod
    def model_validate(cls, payload: dict) -> "SystemConfig":
        payload = payload or {}
        cameras = [CameraConfig.model_validate(item) for item in payload.get("cameras", [])]
        return cls(
            server=ServerConfig.model_validate(payload.get("server")),
            text_llm=TextLLMConfig.model_validate(payload.get("text_llm")),
            storage=StorageConfig.model_validate(payload.get("storage")),
            feishu=FeishuConfig.model_validate(payload.get("feishu")),
            embedding=EmbeddingConfig.model_validate(payload.get("embedding")),
            vector_store=VectorStoreConfig.model_validate(payload.get("vector_store")),
            capture=CaptureConfig.model_validate(payload.get("capture")),
            cameras=cameras,
        )

    def model_dump(self) -> dict:
        return {
            "server": self.server.model_dump(),
            "text_llm": self.text_llm.model_dump(),
            "storage": self.storage.model_dump(),
            "feishu": self.feishu.model_dump(),
            "embedding": self.embedding.model_dump(),
            "vector_store": self.vector_store.model_dump(),
            "capture": self.capture.model_dump(),
            "cameras": [camera.model_dump() for camera in self.cameras],
        }


@dataclass
class FrameAnalysis:
    timestamp: str
    camera_id: str
    risk_level: RiskLevel = "Low"
    anomaly_detected: bool = False
    anomaly_type: str = "normal"
    description: str = ""
    reason: str = ""
    frame_second: float = 0.0
    frame_path: str = ""
    clip_path: str = ""
    event_group_id: str = ""
    event_frame_count: int = 1
    representative_count: int = 1
    event_start_second: float = 0.0
    event_end_second: float = 0.0
    event_duration_seconds: float = 0.0
    person_present: bool = False
    person_count: int = 0
    action_type: str = ""
    upper_clothing_color: str = ""
    lower_clothing_color: str = ""
    confidence: float = 0.0

    @classmethod
    def model_validate(cls, payload: dict) -> "FrameAnalysis":
        timestamp = str(payload.get("timestamp", "")).strip()
        camera_id = str(payload.get("camera_id", "")).strip()
        if not timestamp:
            raise ValidationError("timestamp is required")
        if not camera_id:
            raise ValidationError("camera_id is required")
        return cls(
            timestamp=timestamp,
            camera_id=camera_id,
            risk_level=_normalize_risk_level(payload.get("risk_level")),
            anomaly_detected=_as_bool(payload.get("anomaly_detected", False)),
            anomaly_type=str(payload.get("anomaly_type", "normal")),
            description=str(payload.get("description", "")),
            reason=str(payload.get("reason", "")),
            frame_second=float(payload.get("frame_second", 0.0)),
            frame_path=str(payload.get("frame_path", "")),
            clip_path=str(payload.get("clip_path", "")),
            event_group_id=str(payload.get("event_group_id", "")),
            event_frame_count=max(1, int(payload.get("event_frame_count", 1))),
            representative_count=max(1, int(payload.get("representative_count", 1))),
            event_start_second=float(payload.get("event_start_second", payload.get("frame_second", 0.0))),
            event_end_second=float(payload.get("event_end_second", payload.get("frame_second", 0.0))),
            event_duration_seconds=float(payload.get("event_duration_seconds", 0.0)),
            person_present=_as_bool(payload.get("person_present", False)),
            person_count=max(0, int(payload.get("person_count", 0))),
            action_type=str(payload.get("action_type", "")).strip(),
            upper_clothing_color=str(payload.get("upper_clothing_color", "")).strip(),
            lower_clothing_color=str(payload.get("lower_clothing_color", "")).strip(),
            confidence=max(0.0, min(1.0, float(payload.get("confidence", 0.0)))),
        )

    def model_dump(self) -> dict:
        return asdict(self)

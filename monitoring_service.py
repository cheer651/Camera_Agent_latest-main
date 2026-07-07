from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from camera_recorder import CameraService, record_clip
from embedding_client import EmbeddingClient
from event_store import EventStore
from feishu_agent import FeishuAgent
from llm_client import LLMClient
from monitoring_analysis import MonitoringAnalysisMixin
from monitoring_dashboard import MonitoringDashboardMixin
from monitoring_prompts import DEFAULT_PROMPT, SUMMARY_PERIODS
from monitoring_query import MonitoringQueryMixin
from monitoring_summary import MonitoringSummaryMixin
from monitoring_types import FrameJob
from ollama_client import OllamaClient
from schemas import CameraConfig, SystemConfig
from smart_extractor import SmartKeyframeExtractor
from vector_store import QdrantVectorStore
from xiaoan_assistant import XiaoAnAssistantMixin


class MonitoringOrchestrator(
    XiaoAnAssistantMixin,
    MonitoringDashboardMixin,
    MonitoringQueryMixin,
    MonitoringAnalysisMixin,
    MonitoringSummaryMixin,
):
    def __init__(self, config_path: str = "camera_config.json", prompt_path: str = "prompt.txt", start_preview: bool = True) -> None:
        self.config_path = Path(config_path)
        self.prompt_path = Path(prompt_path)
        self.config = self._load_config()
        self._start_preview = start_preview

        self.base_dir = Path(self.config.storage.base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.prompt_template = self._load_prompt()
        self.summary_periods = SUMMARY_PERIODS
        self.logs: list[dict[str, str]] = []
        self.capture_mode = "local_direct"

        self.store = EventStore(self.config.storage.database_path)
        self.llm_client = LLMClient(
            base_url=self.config.server.base_url,
            provider=self.config.server.provider,
            model=self.config.server.model,
            api_key=self.config.server.api_key,
            photo_endpoint=self.config.server.photo_endpoint,
            chat_endpoint=self.config.server.chat_endpoint,
            chat_completions_endpoint=self.config.server.chat_completions_endpoint,
            timeout_seconds=self.config.server.timeout_seconds,
            max_tokens=self.config.server.max_tokens,
            temperature=self.config.server.temperature,
            top_p=self.config.server.top_p,
            presence_penalty=self.config.server.presence_penalty,
            top_k=self.config.server.top_k,
        )
        self.text_llm_client = OllamaClient(
            base_url=self.config.text_llm.base_url,
            model=self.config.text_llm.model,
            generate_endpoint=self.config.text_llm.generate_endpoint,
            timeout_seconds=self.config.text_llm.timeout_seconds,
            keep_alive=self.config.text_llm.keep_alive,
            temperature=self.config.text_llm.temperature,
            num_ctx=self.config.text_llm.num_ctx,
            enabled=self.config.text_llm.enabled and self.config.text_llm.provider.lower() == "ollama",
        )
        self.embedding_client = EmbeddingClient(
            base_url=self.config.embedding.base_url,
            endpoint=self.config.embedding.endpoint,
            model=self.config.embedding.model,
            timeout_seconds=self.config.embedding.timeout_seconds,
            enabled=self.config.embedding.enabled,
        )
        self.vector_store = QdrantVectorStore(
            base_url=self.config.vector_store.base_url,
            collection_name=self.config.vector_store.collection_name,
            vector_size=self.config.vector_store.vector_size,
            distance=self.config.vector_store.distance,
            enabled=self.config.vector_store.enabled and self.config.vector_store.provider.lower() == "qdrant",
            create_payload_indexes=self.config.vector_store.create_payload_indexes,
        )

        self.text_llm_ready = self.text_llm_client.test_connection(timeout=2) if self.text_llm_client.enabled else False
        if self.text_llm_client.enabled:
            if self.text_llm_ready:
                self.add_log("text_llm", f"Local text model ready: {self.config.text_llm.model}")
            else:
                self.add_log("text_llm", f"Local text model unavailable: {self.text_llm_client.last_error or 'unknown'}")

        feishu_runtime = self._resolve_feishu_runtime_config()
        self.feishu_agent = FeishuAgent(
            app_id=feishu_runtime["app_id"],
            app_secret=feishu_runtime["app_secret"],
            chat_id=feishu_runtime["chat_id"],
            webhook_url=feishu_runtime["webhook_url"],
        )

        self.camera_lookup = {camera.camera_id: camera for camera in self.config.cameras if camera.enabled}
        self.camera_services = self._build_camera_services()
        self.analysis_graph = self._build_analysis_graph()
        self.summary_graph = self._build_summary_graph()
        self.chat_graph = self._build_chat_graph()

        self.latest_report: list[dict[str, Any]] = self.get_events_for_date(self._today())
        self.latest_summary = self._deserialize_summary_record(self.store.get_latest_summary())
        self.task_status: dict[str, Any] = {
            "task_id": "",
            "status": "idle",
            "started_at": "",
            "finished_at": "",
            "duration_seconds": self.config.storage.clip_duration_seconds,
            "camera_ids": list(self.camera_lookup.keys()),
            "message": "System idle. Waiting for local capture tasks.",
            "event_count": len(self.latest_report),
        }

        self.task_thread: threading.Thread | None = None
        self.task_lock = threading.Lock()
        self.scheduler_thread: threading.Thread | None = None
        self.last_scheduler_run_date = ""

        if self.config.storage.enable_daily_summary_scheduler:
            self.scheduler_thread = threading.Thread(target=self._daily_summary_scheduler, daemon=True)
            self.scheduler_thread.start()

        self.vector_search_enabled = self._init_vector_services()
        self.add_log("capture", "Running in local-direct mode. Remote capture code is not used.")

    def _load_config(self) -> SystemConfig:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        payload = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
        return SystemConfig.model_validate(payload)

    def _load_prompt(self) -> str:
        if self.prompt_path.exists():
            text = self.prompt_path.read_text(encoding="utf-8-sig").strip()
            if text:
                return text
        return DEFAULT_PROMPT

    def _resolve_feishu_runtime_config(self) -> dict[str, str]:
        return {
            "app_id": self.config.feishu.app_id,
            "app_secret": self.config.feishu.app_secret,
            "chat_id": self.config.feishu.chat_id,
            "webhook_url": self.config.feishu.webhook_url,
        }

    def _run_text_llm(self, prompt: str, timeout: int | None = None, temperature: float | None = None) -> str:
        if not self.text_llm_client.enabled:
            return ""
        try:
            response = self.text_llm_client.generate(prompt, timeout=timeout, temperature=temperature)
        except Exception as exc:
            self.add_log("text_llm", f"Generation failed: {exc}")
            return ""

        cleaned = str(response or "").strip()
        cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.S | re.I).strip()
        cleaned = cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return cleaned

    def _init_vector_services(self) -> bool:
        if not (self.embedding_client.enabled and self.vector_store.enabled):
            self.add_log("vector", "Vector search disabled by config.")
            return False
        if not self.embedding_client.test_connection():
            self.add_log("vector", f"Embedding service unavailable: {self.embedding_client.last_error or 'unknown'}")
            return False
        if not self.vector_store.test_connection():
            self.add_log("vector", "Qdrant service unavailable.")
            return False
        try:
            self.vector_store.ensure_collection()
            self.add_log("vector", f"Qdrant collection ready: {self.config.vector_store.collection_name}")
            self._backfill_recent_events_to_vector_store(limit=300)
            return True
        except Exception as exc:
            self.add_log("vector", f"Vector initialization failed: {exc}")
            return False

    def _backfill_recent_events_to_vector_store(self, limit: int = 300) -> None:
        rows = self.store.list_recent_events(limit=limit)
        if not rows:
            return
        report_items = [self._build_report_item_from_row(row) for row in rows]
        self._index_report_items(report_items, source="backfill", force=True)

    def _build_camera_services(self) -> dict[str, CameraService]:
        services: dict[str, CameraService] = {}
        if not self._start_preview:
            return services
        for camera in self.config.cameras:
            if camera.enabled and camera.preview_enabled:
                services[camera.camera_id] = CameraService(
                    camera_id=camera.camera_id,
                    name=camera.name,
                    source_type=camera.source_type,
                    source=camera.effective_source,
                )
        return services

    def add_log(self, module: str, message: str) -> None:
        self.logs.append(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "module": str(module),
                "message": str(message),
            }
        )
        if len(self.logs) > 500:
            self.logs = self.logs[-500:]

    def get_logs(self) -> list[dict[str, str]]:
        return list(self.logs)

    @staticmethod
    def _today() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def get_task_status(self) -> dict[str, Any]:
        return dict(self.task_status)

    def get_latest_report(self) -> list[dict[str, Any]]:
        return list(self.latest_report)

    def get_latest_summary(self) -> dict[str, Any] | None:
        return dict(self.latest_summary) if self.latest_summary else None

    def get_summary_for_date(
        self,
        summary_date: str | None = None,
        regenerate: bool = False,
        send_to_feishu: bool = False,
    ) -> dict[str, Any]:
        target_date = summary_date or self._today()
        if regenerate:
            return self.generate_daily_summary(summary_date=target_date, send_to_feishu=send_to_feishu)
        record = self.store.get_summary_by_date(target_date)
        parsed = self._deserialize_summary_record(record)
        if parsed:
            return parsed
        return {
            "summary_date": target_date,
            "title": f"{target_date} summary",
            "overall_summary": "",
            "periods": [],
            "sent_to_feishu": False,
        }

    def get_events_for_date(self, summary_date: str | None = None) -> list[dict[str, Any]]:
        target_date = summary_date or self._today()
        rows = self.store.list_events_for_day(target_date)
        return [self._build_report_item_from_row(row) for row in rows]

    def get_camera_service(self, camera_id: str) -> CameraService | None:
        return self.camera_services.get(camera_id)

    def get_cameras_overview(self) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        for camera in self.config.cameras:
            service = self.camera_services.get(camera.camera_id)
            snapshot = service.status_snapshot() if service else {
                "camera_id": camera.camera_id,
                "name": camera.name,
                "source_type": camera.source_type,
                "configured": bool(camera.effective_source),
                "available": False,
                "last_error": "" if camera.enabled else "disabled",
                "last_success_at": "",
            }
            snapshot.update(
                {
                    "enabled": bool(camera.enabled),
                    "preview_enabled": bool(camera.preview_enabled),
                    "description": camera.description,
                    "source": self._sanitize_source(camera.effective_source, camera.source_type),
                    "source_preview": self._sanitize_source(camera.effective_source, camera.source_type),
                    "video_feed_url": f"/video_feed/{camera.camera_id}",
                }
            )
            snapshots.append(snapshot)
        return snapshots

    def get_overview(self) -> dict[str, Any]:
        cameras = self.get_cameras_overview()
        events = self.get_events_for_date(self._today())
        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "capture_mode": self.capture_mode,
            "cameras": cameras,
            "task": self.get_task_status(),
            "latest_report": events,
            "latest_summary": self.get_latest_summary(),
            "logs": self.get_logs(),
            "vector_search_enabled": bool(self.vector_search_enabled),
            "text_llm_ready": bool(self.text_llm_ready),
        }

    def start_task(self, camera_ids: list[str] | None = None, duration_seconds: int | None = None) -> dict[str, Any]:
        with self.task_lock:
            if self.task_thread and self.task_thread.is_alive():
                return {"status": "busy", "message": "A capture task is already running."}

            cameras = self._select_cameras(camera_ids)
            if not cameras:
                return {"status": "failed", "message": "No enabled cameras selected."}

            task_id = datetime.now().strftime("task_%Y%m%d_%H%M%S")
            duration = int(duration_seconds or self.config.storage.clip_duration_seconds)
            started_at = datetime.now().isoformat(timespec="seconds")
            selected_ids = [camera.camera_id for camera in cameras]
            self.store.create_task(
                task_id=task_id,
                started_at=started_at,
                status="running",
                trigger_type="manual",
                requested_duration=duration,
                camera_ids=selected_ids,
            )
            self.task_status = {
                "task_id": task_id,
                "status": "running",
                "started_at": started_at,
                "finished_at": "",
                "duration_seconds": duration,
                "camera_ids": selected_ids,
                "message": "Local capture and analysis task is running.",
                "event_count": 0,
            }
            self.task_thread = threading.Thread(
                target=self._run_task,
                args=(task_id, cameras, duration),
                daemon=True,
            )
            self.task_thread.start()
            return {"status": "success", "task_id": task_id, "message": "Task started."}

    def run_task_sync(self, camera_ids: list[str] | None = None, duration_seconds: int | None = None) -> dict[str, Any]:
        result = self.start_task(camera_ids=camera_ids, duration_seconds=duration_seconds)
        if result.get("status") != "success":
            return result
        if self.task_thread:
            self.task_thread.join()
        return self.get_task_status()

    def _run_task(self, task_id: str, cameras: list[CameraConfig], duration_seconds: int) -> None:
        try:
            frame_jobs = self._prepare_frame_jobs_for_cameras(task_id, cameras, duration_seconds)
            if not frame_jobs:
                finished_at = datetime.now().isoformat(timespec="seconds")
                self.store.update_task(task_id, "partial_failed", finished_at, "No keyframes extracted.")
                self.task_status.update(
                    {
                        "status": "partial_failed",
                        "finished_at": finished_at,
                        "message": "No analyzable keyframes were extracted.",
                        "event_count": 0,
                    }
                )
                return

            graph_result = self.analysis_graph.invoke({"task_id": task_id, "frame_jobs": frame_jobs})
            report_items = list(graph_result.get("report_items", []))
            finished_at = datetime.now().isoformat(timespec="seconds")
            status = "completed"
            self.store.update_task(task_id, status, finished_at)
            self.latest_report = self.get_events_for_date(self._today())
            self.task_status.update(
                {
                    "status": status,
                    "finished_at": finished_at,
                    "message": f"Task completed with {len(report_items)} events.",
                    "event_count": len(report_items),
                }
            )
            self.add_log("task", f"{task_id} completed with {len(report_items)} events.")
        except Exception as exc:
            finished_at = datetime.now().isoformat(timespec="seconds")
            self.store.update_task(task_id, "failed", finished_at, str(exc))
            self.task_status.update(
                {
                    "status": "failed",
                    "finished_at": finished_at,
                    "message": f"Task failed: {exc}",
                }
            )
            self.add_log("task", f"{task_id} failed: {exc}")

    def _prepare_frame_jobs_for_cameras(
        self,
        task_id: str,
        cameras: list[CameraConfig],
        duration_seconds: int,
    ) -> list[FrameJob]:
        if not cameras:
            return []
        max_workers = max(1, min(len(cameras), int(self.config.storage.camera_capture_workers)))
        prepared_jobs: list[FrameJob] = []
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="clip-worker") as executor:
            future_map = {
                executor.submit(self._prepare_frame_jobs, task_id, camera, duration_seconds): camera
                for camera in cameras
            }
            for future in as_completed(future_map):
                camera = future_map[future]
                try:
                    prepared_jobs.extend(future.result())
                except Exception as exc:
                    self.add_log("capture", f"{camera.name} failed during local capture/extraction: {exc}")
        return self._interleave_frame_jobs(prepared_jobs)

    def _prepare_frame_jobs(self, task_id: str, camera: CameraConfig, duration_seconds: int) -> list[FrameJob]:
        clip_dir = self.base_dir / task_id / "raw_clips"
        clip_dir.mkdir(parents=True, exist_ok=True)
        clip_path = clip_dir / f"{camera.camera_id}.mp4"

        # 暂停摄像头预览，释放 RTSP 流供录制独占使用
        camera_service = self.camera_services.get(camera.camera_id)
        was_running = False
        if camera_service is not None and camera_service.is_running:
            camera_service.pause()
            was_running = True
            time.sleep(0.3)  # 等待 FFmpeg 完全释放资源

        self.add_log("capture", f"{camera.name} local recording started.")
        try:
            record_result = record_clip(
                source_type=camera.source_type,
                source=camera.effective_source,
                filepath=str(clip_path),
                duration_seconds=duration_seconds,
            )
        finally:
            # 录制完成后恢复预览
            if was_running and camera_service is not None:
                camera_service.resume()

        run_status = "completed" if record_result.get("success") else "failed"
        self.store.add_camera_run(
            task_id=task_id,
            camera_id=camera.camera_id,
            camera_name=camera.name,
            clip_path=str(clip_path),
            frames_written=int(record_result.get("frames_written", 0)),
            fps=float(record_result.get("fps", 0.0)),
            status=run_status,
            error_message=str(record_result.get("error", "")),
        )

        if not record_result.get("success"):
            self.add_log("capture", f"{camera.name} recording failed: {record_result.get('error', 'unknown_error')}")
            return []

        return self._extract_frame_jobs_from_clip(
            task_id=task_id,
            camera=camera,
            clip_path=str(clip_path),
            clip_started_at=str(record_result.get("started_at", datetime.now().isoformat(timespec="seconds"))),
            frames_written=int(record_result.get("frames_written", 0)),
            fps=float(record_result.get("fps", 0.0)),
        )

    def _extract_frame_jobs_from_clip(
        self,
        task_id: str,
        camera: CameraConfig,
        clip_path: str,
        clip_started_at: str,
        frames_written: int,
        fps: float,
    ) -> list[FrameJob]:
        _ = frames_written, fps
        analysis_dir = self.base_dir / task_id / "analysis" / camera.camera_id
        extractor = SmartKeyframeExtractor(
            input_video=clip_path,
            output_path=str(analysis_dir),
            base_threshold=self.config.storage.similarity_threshold,
            frame_rate=self.config.storage.frame_sample_rate,
            scale_factor=self.config.storage.extractor_scale_factor,
            min_time_gap=self.config.storage.min_frame_gap_seconds,
            event_time_gap=self.config.storage.event_merge_time_gap_seconds,
            event_similarity_threshold=self.config.storage.event_merge_similarity_threshold,
            max_event_duration=self.config.storage.event_max_duration_seconds,
            max_representative_frames=self.config.storage.max_representative_frames,
            motion_threshold=self.config.storage.motion_score_threshold,
        )
        extraction_result = extractor.run()
        if not extraction_result:
            self.add_log("extract", f"{camera.name} did not produce extracted frames.")
            return []

        jobs: list[FrameJob] = []
        for index, frame in enumerate(extraction_result.get("frames", [])):
            second = float(frame.get("second", frame.get("frame_second", 0.0)) or 0.0)
            jobs.append(
                {
                    "task_id": task_id,
                    "camera_id": camera.camera_id,
                    "camera_name": camera.name,
                    "clip_path": clip_path,
                    "clip_started_at": clip_started_at,
                    "frame_path": str(frame.get("filepath", frame.get("frame_path", ""))),
                    "frame_second": second,
                    "event_group_id": str(frame.get("event_group_id", f"frame_{index:03d}")),
                    "event_frame_count": int(frame.get("event_frame_count", 1)),
                    "representative_count": int(frame.get("representative_count", 1)),
                    "event_start_second": float(frame.get("event_start_second", second)),
                    "event_end_second": float(frame.get("event_end_second", second)),
                    "event_duration_seconds": float(frame.get("event_duration_seconds", 0.0)),
                    "representative_rank": int(frame.get("representative_rank", 1)),
                    "is_primary": int(frame.get("is_primary", 1)),
                    "person_count_hint": int(frame.get("person_count_hint", 0)),
                    "person_score_hint": float(frame.get("person_score_hint", 0.0)),
                    "low_pose_hint": int(frame.get("low_pose_hint", 0)),
                    "foreground_area_ratio_hint": float(frame.get("foreground_area_ratio_hint", 0.0)),
                    "analysis_order": index,
                }
            )
        self.add_log("extract", f"{camera.name} extracted {len(jobs)} representative frames.")
        return jobs

    def answer_question(self, question: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        if not question.strip():
            return {"answer": "Please enter a question.", "references": []}

        cleaned_question = question.strip()
        if self._classify_query_intent(cleaned_question) == "greeting":
            return {
                "answer": "你好，我可以帮你按日期、摄像头、风险等级和人物特征查询监控记录。",
                "references": [],
                "used_llm": False,
                "standalone_question": cleaned_question,
            }

        result = self.chat_graph.invoke({"question": cleaned_question, "history": list(history or [])})
        return {
            "answer": result.get("answer", "未生成有效回答。"),
            "references": result.get("references", []),
            "used_llm": bool(result.get("used_llm", False)),
            "standalone_question": result.get("standalone_question", cleaned_question),
        }

    def shutdown(self) -> None:
        for service in self.camera_services.values():
            service.release()

    def _select_cameras(self, camera_ids: list[str] | None) -> list[CameraConfig]:
        if not camera_ids:
            return [camera for camera in self.config.cameras if camera.enabled]
        target_ids = {str(camera_id) for camera_id in camera_ids}
        return [camera for camera in self.config.cameras if camera.enabled and camera.camera_id in target_ids]

    def _sanitize_source(self, source: str, source_type: str) -> str:
        source = str(source or "").strip()
        if not source:
            return ""
        if source_type in {"local", "file"}:
            return Path(source).name
        if source_type == "rtsp":
            parsed = urlparse(source)
            if parsed.scheme and parsed.hostname:
                port = f":{parsed.port}" if parsed.port else ""
                return f"{parsed.scheme}://{parsed.hostname}{port}{parsed.path}"
            return "RTSP source"
        return source

    def _parse_datetime(self, value: str) -> datetime | None:
        if not value:
            return None
        candidate = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            parsed = parsed.replace(tzinfo=None)
        return parsed

    def _format_time_label(self, timestamp: str) -> str:
        parsed = self._parse_datetime(timestamp)
        if parsed:
            return parsed.strftime("%H:%M:%S")
        return timestamp[-8:] if len(timestamp) >= 8 else timestamp

    def _daily_summary_scheduler(self) -> None:
        while True:
            now = datetime.now()
            current_marker = now.strftime("%Y-%m-%d")
            if now.strftime("%H:%M") == self.config.storage.daily_summary_time:
                if current_marker != self.last_scheduler_run_date:
                    try:
                        self.generate_daily_summary(summary_date=current_marker, send_to_feishu=True)
                        self.last_scheduler_run_date = current_marker
                    except Exception as exc:
                        self.add_log("summary", f"Scheduled daily summary failed: {exc}")
            time.sleep(30)

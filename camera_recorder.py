from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import os


def _open_capture(source_type: str, source: str) -> cv2.VideoCapture:
    if source_type == "index":
        return cv2.VideoCapture(int(source), cv2.CAP_DSHOW)
    if source_type == "rtsp" or str(source).startswith("rtsp"):
        # 强制 TCP 传输避免 FFmpeg 断言崩溃，同时兼容多连接场景
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
        return cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    return cv2.VideoCapture(source)


def _placeholder_frame(text: str) -> np.ndarray:
    width, height = 960, 540
    image = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.rectangle(image, (20, 20), (width - 20, height - 20), (70, 70, 70), 3)
    cv2.putText(
        image,
        text,
        (60, height // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 180, 255),
        2,
        cv2.LINE_AA,
    )
    return image

class CameraService:
    def __init__(self, camera_id: str, name: str, source_type: str, source: str) -> None:
        self.camera_id = camera_id
        self.name = name
        self.source_type = source_type
        self.source = source

        self.lock = threading.Lock()
        self.is_running = True
        self.last_error = "未配置视频源" if not source else ""
        self.last_success_at = ""
        self.current_frame = _placeholder_frame(f"{name}: 未配置视频源")
        self.available = False

        self.cap: cv2.VideoCapture | None = None
        self.thread = threading.Thread(target=self._update_frames, daemon=True)
        self.thread.start()

    def _connect(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

        if not self.source:
            with self.lock:
                self.available = False
                self.last_error = "未配置视频源"
                self.current_frame = _placeholder_frame(f"{self.name}: 未配置视频源")
            return

        cap = _open_capture(self.source_type, self.source)
        if cap.isOpened():
            self.cap = cap
            with self.lock:
                self.available = True
                self.last_error = ""
        else:
            cap.release()
            with self.lock:
                self.available = False
                self.last_error = "无法打开视频源"
                self.current_frame = _placeholder_frame(f"{self.name}: 离线")

    def _update_frames(self) -> None:
        self._connect()

        while self.is_running:
            if self.cap is None or not self.cap.isOpened():
                self._connect()
                time.sleep(1.0)
                continue

            success, frame = self.cap.read()
            if success:
                with self.lock:
                    self.current_frame = frame
                    self.available = True
                    self.last_success_at = datetime.now().isoformat(timespec="seconds")
                    self.last_error = ""
            else:
                with self.lock:
                    self.available = False
                    self.last_error = "读取画面失败"
                    self.current_frame = _placeholder_frame(f"{self.name}: 无信号")

                if self.source_type == "file":
                    if self.cap is not None:
                        self.cap.release()
                    self.cap = None
                    time.sleep(0.5)
                else:
                    if self.cap is not None:
                        self.cap.release()
                    self.cap = None
                    time.sleep(1.0)
            time.sleep(0.03)

    def get_frame_bytes(self) -> bytes | None:
        with self.lock:
            frame = self.current_frame.copy()
        ok, buffer = cv2.imencode(".jpg", frame)
        if not ok:
            return None
        return buffer.tobytes()

    def status_snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "camera_id": self.camera_id,
                "name": self.name,
                "source_type": self.source_type,
                "configured": bool(self.source),
                "available": self.available,
                "last_error": self.last_error,
                "last_success_at": self.last_success_at,
            }

    def pause(self) -> None:
        """暂停摄像头预览（释放视频流，供录制独占使用）"""
        self.is_running = False
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def resume(self) -> None:
        """恢复摄像头预览"""
        self.is_running = True
        self.thread = threading.Thread(target=self._update_frames, daemon=True)
        self.thread.start()

    def release(self) -> None:
        self.is_running = False
        if self.cap is not None:
            self.cap.release()
            self.cap = None


def record_clip(
    source_type: str,
    source: str,
    filepath: str,
    duration_seconds: int,
) -> dict[str, Any]:
    target_path = Path(filepath)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if not source:
        return {
            "success": False,
            "error": "摄像头视频源为空",
            "filepath": str(target_path),
        }

    cap = _open_capture(source_type, source)
    if not cap.isOpened():
        return {
            "success": False,
            "error": f"无法打开视频源：{source}",
            "filepath": str(target_path),
        }

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 1 or fps > 120:
        fps = 12.0

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    writer = cv2.VideoWriter(
        str(target_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    if not writer.isOpened():
        cap.release()
        return {
            "success": False,
            "error": "无法创建输出文件",
            "filepath": str(target_path),
        }

    started_at = datetime.now()
    frames_written = 0
    max_file_frames = max(1, int(duration_seconds * fps)) if source_type == "file" else None
    deadline = time.time() + duration_seconds if source_type != "file" else None

    try:
        while True:
            if deadline is not None and time.time() >= deadline:
                break
            if max_file_frames is not None and frames_written >= max_file_frames:
                break

            success, frame = cap.read()
            if not success:
                if source_type == "file":
                    break
                time.sleep(0.1)
                continue

            writer.write(frame)
            frames_written += 1
    finally:
        cap.release()
        writer.release()

    actual_duration = frames_written / fps if fps > 0 else 0.0
    return {
        "success": frames_written > 0,
        "error": "" if frames_written > 0 else "未采集到有效画面",
        "filepath": str(target_path),
        "started_at": started_at.isoformat(timespec="seconds"),
        "frames_written": frames_written,
        "fps": round(fps, 2),
        "duration_seconds": round(actual_duration, 2),
        "width": width,
        "height": height,
    }

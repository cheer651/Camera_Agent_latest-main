from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import wave
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_TTS_PROVIDER = "sherpa_onnx"
DEFAULT_TTS_PROVIDER_NAME = "sherpa_onnx_vits_zh_ll"
DEFAULT_TTS_VOICE = "2"
DEFAULT_TTS_SPEED = 1.18
DEFAULT_TTS_CACHE_VERSION = "sherpa_onnx_vits_zh_ll_v1"


class VoiceBridgeError(RuntimeError):
    """Raised when ASR or TTS execution fails."""


class VoicePipelineBridge:
    def __init__(self, project_root: Path, data_root: Path) -> None:
        self.project_root = Path(project_root).resolve()
        voice_data_root = (
            os.environ.get("CAMERA_AGENT_VOICE_DATA_ROOT")
            or os.environ.get("CAMERA_AGENT_DATA_ROOT")
            or r"D:\camera_agent_data"
        )
        self.data_root = Path(voice_data_root).resolve()
        self.voice_root = self.data_root / "_voice"
        self.inputs_dir = self.voice_root / "inputs"
        self.outputs_dir = self.voice_root / "outputs"
        self.meta_dir = self.voice_root / "meta"
        self.logs_dir = self.voice_root / "logs"
        self.cache_dir = self.voice_root / "cache"

        self.sensevoice_python = self.data_root / "venvs" / "sensevoice" / "Scripts" / "python.exe"
        self.sensevoice_server_script = self.project_root / "tools" / "sensevoice_server.py"
        self.sensevoice_model_dir = self.data_root / "local_models" / "sensevoice" / "iic" / "SenseVoiceSmall"
        self.asr_host = "127.0.0.1"
        self.asr_port = 5092

        self.tts_provider = DEFAULT_TTS_PROVIDER
        self.sherpa_python = self.data_root / "venvs" / "sherpa-onnx-tts" / "Scripts" / "python.exe"
        self.sherpa_fallback_python = self.project_root / ".venv" / "Scripts" / "python.exe"
        self.sherpa_server_script = self.project_root / "tools" / "sherpa_onnx_tts_server.py"
        self.sherpa_model_dir = self.data_root / "local_models" / "sherpa_onnx_tts" / "sherpa-onnx-vits-zh-ll"
        self.sherpa_output_dir = self.outputs_dir / "sherpa_onnx"
        self.tts_host = "127.0.0.1"
        self.tts_port = 5091

        self._asr_lock = threading.Lock()
        self._asr_warmup_lock = threading.Lock()
        self._asr_warmed_up = False
        self._asr_server_process: subprocess.Popen[str] | None = None
        self._asr_server_log_handle: Any | None = None

        self._tts_lock = threading.Lock()
        self._tts_warmup_lock = threading.Lock()
        self._tts_warmed_up = False
        self._tts_server_process: subprocess.Popen[str] | None = None
        self._tts_server_log_handle: Any | None = None

        for directory in (
            self.inputs_dir,
            self.outputs_dir,
            self.meta_dir,
            self.logs_dir,
            self.cache_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def save_uploaded_audio(self, uploaded_file: Any) -> Path:
        suffix = Path(getattr(uploaded_file, "filename", "") or "").suffix.lower() or ".wav"
        target_path = self.inputs_dir / f"{self._timestamp()}_{self._random_suffix()}{suffix}"
        uploaded_file.save(target_path)
        if not target_path.exists() or target_path.stat().st_size <= 0:
            raise VoiceBridgeError("Audio file save failed.")
        return target_path

    def ensure_services_ready(self) -> None:
        self.ensure_tts_server()
        self.warmup_tts()
        self.ensure_asr_server()
        self.warmup_asr()

    def transcribe_file(self, audio_path: Path) -> dict[str, Any]:
        source_path = Path(audio_path).resolve()
        if not source_path.exists():
            raise VoiceBridgeError(f"Audio file not found: {source_path}")

        self.ensure_asr_server()
        self.warmup_asr()

        response = self._request_json_server(
            host=self.asr_host,
            port=self.asr_port,
            path="/transcribe",
            payload={
                "audio_path": str(source_path),
                "language": "zh",
                "batch_size_s": 30,
            },
            timeout_seconds=240,
            service_name="ASR",
        )

        payload_path = self.meta_dir / f"asr_{source_path.stem}.json"
        payload_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")

        if str(response.get("status", "success")).lower() != "success":
            message = str(response.get("message", "")).strip() or "ASR transcription failed."
            raise VoiceBridgeError(message)

        transcript = str(response.get("text", "")).strip()
        if not self._is_valid_asr_transcript(transcript):
            raise VoiceBridgeError("No valid speech content was recognized.")

        return {
            "transcript": transcript,
            "audio_path": str(source_path),
            "audio_url": self._build_session_url(source_path),
        }

    def synthesize_text(
        self,
        text: str,
        *,
        speed: float = DEFAULT_TTS_SPEED,
        voice: str = DEFAULT_TTS_VOICE,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        clean_text = str(text or "").strip()
        if not clean_text:
            raise VoiceBridgeError("Missing text content for speech synthesis.")
        tts_text = self._normalize_tts_text_to_chinese(clean_text)

        cache_key = self._build_tts_cache_key(
            tts_text,
            speed=speed,
            voice=voice,
            provider=self.tts_provider,
            cache_version=DEFAULT_TTS_CACHE_VERSION,
        )
        payload_path = self.meta_dir / f"tts_{cache_key}.json"
        cache_meta_path = self.cache_dir / f"{cache_key}.json"
        preferred_audio_path = self.cache_dir / f"{cache_key}.wav"

        if use_cache:
            cached = self._read_tts_cache(cache_meta_path, clean_text)
            if cached is not None:
                return cached

        self.ensure_tts_server()
        self.warmup_tts()

        response = self._request_json_server(
            host=self.tts_host,
            port=self.tts_port,
            path="/synthesize",
            payload={
                "text": tts_text,
                "output_path": str(preferred_audio_path),
                "speed": float(speed),
                "voice": str(voice or DEFAULT_TTS_VOICE).strip() or DEFAULT_TTS_VOICE,
            },
            timeout_seconds=120,
            service_name="TTS",
        )
        payload_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")

        if str(response.get("status", "success")).lower() != "success":
            message = str(response.get("message", "")).strip() or "TTS synthesis failed."
            raise VoiceBridgeError(message)

        output_path = Path(response.get("output_path") or preferred_audio_path).resolve()
        if not output_path.exists() or output_path.stat().st_size <= 0:
            raise VoiceBridgeError("Speech synthesis failed: no playable audio was generated.")

        cache_meta_path.write_text(
            json.dumps(
                {
                    "output_path": str(output_path),
                    "text": clean_text,
                    "tts_text": tts_text,
                    "speed": float(speed),
                    "voice": str(voice or DEFAULT_TTS_VOICE).strip() or DEFAULT_TTS_VOICE,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return {
            "audio_path": str(output_path),
            "audio_url": self._build_session_url(output_path),
            "text": clean_text,
            "tts_text": tts_text,
            "cached": False,
        }

    def warmup_asr(self, timeout_seconds: int = 240) -> None:
        if self._asr_warmed_up:
            return

        with self._asr_warmup_lock:
            if self._asr_warmed_up:
                return

            warmup_audio_path = self.inputs_dir / "_asr_warmup.wav"
            warmup_meta_path = self.meta_dir / "_asr_warmup.json"
            self._write_silence_wav(warmup_audio_path, duration_seconds=0.4)
            response = self._request_json_server(
                host=self.asr_host,
                port=self.asr_port,
                path="/transcribe",
                payload={
                    "audio_path": str(warmup_audio_path),
                    "language": "zh",
                    "batch_size_s": 30,
                },
                timeout_seconds=timeout_seconds,
                service_name="ASR",
            )
            warmup_meta_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
            if str(response.get("status", "success")).lower() != "success":
                message = str(response.get("message", "")).strip() or "ASR warmup failed."
                raise VoiceBridgeError(message)
            self._asr_warmed_up = True
            try:
                warmup_audio_path.unlink(missing_ok=True)
            except OSError:
                pass

    def warmup_tts(self, timeout_seconds: int = 180) -> None:
        if self._tts_warmed_up:
            return

        with self._tts_warmup_lock:
            if self._tts_warmed_up:
                return

            warmup_audio_path = self.outputs_dir / "_tts_warmup.wav"
            warmup_meta_path = self.meta_dir / "_tts_warmup.json"
            response = self._request_json_server(
                host=self.tts_host,
                port=self.tts_port,
                path="/synthesize",
                payload={
                    "text": "语音播报已就绪。",
                    "output_path": str(warmup_audio_path),
                    "speed": 1.08,
                    "voice": DEFAULT_TTS_VOICE,
                },
                timeout_seconds=timeout_seconds,
                service_name="TTS",
            )
            warmup_meta_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
            if str(response.get("status", "success")).lower() != "success":
                message = str(response.get("message", "")).strip() or "TTS warmup failed."
                raise VoiceBridgeError(message)
            self._tts_warmed_up = True
            try:
                warmup_audio_path.unlink(missing_ok=True)
            except OSError:
                pass

    def prime_common_tts_cache(self, phrases: list[str] | tuple[str, ...]) -> None:
        for phrase in phrases:
            clean_phrase = str(phrase or "").strip()
            if not clean_phrase:
                continue
            try:
                self.synthesize_text(clean_phrase, use_cache=False)
            except Exception:
                continue

    def ensure_asr_server(self, timeout_seconds: int = 240) -> None:
        if self._is_asr_server_ready():
            return

        with self._asr_lock:
            if self._is_asr_server_ready():
                return
            if self._asr_server_process is None or self._asr_server_process.poll() is not None:
                self._start_asr_server_process()

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self._is_asr_server_ready():
                return
            if self._asr_server_process is not None and self._asr_server_process.poll() is not None:
                raise VoiceBridgeError(self._build_asr_server_failure_message())
            time.sleep(1.0)

        raise VoiceBridgeError("ASR server startup timed out.")

    def ensure_tts_server(self, timeout_seconds: int = 180) -> None:
        if self._is_tts_server_ready():
            return

        with self._tts_lock:
            if self._is_tts_server_ready():
                return
            if self._tts_server_process is None or self._tts_server_process.poll() is not None:
                self._start_tts_server_process()

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self._is_tts_server_ready():
                return
            if self._tts_server_process is not None and self._tts_server_process.poll() is not None:
                raise VoiceBridgeError(self._build_tts_server_failure_message())
            time.sleep(1.0)

        raise VoiceBridgeError("TTS server startup timed out.")

    def shutdown(self) -> None:
        for process in (self._asr_server_process, self._tts_server_process):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

        if self._asr_server_log_handle is not None:
            self._asr_server_log_handle.close()
            self._asr_server_log_handle = None
        if self._tts_server_log_handle is not None:
            self._tts_server_log_handle.close()
            self._tts_server_log_handle = None

    def _is_asr_server_ready(self) -> bool:
        try:
            payload = self._request_json_server(
                host=self.asr_host,
                port=self.asr_port,
                path="/health",
                timeout_seconds=2,
                service_name="ASR",
            )
        except VoiceBridgeError:
            return False
        return bool(payload.get("ready"))

    def _is_tts_server_ready(self) -> bool:
        try:
            payload = self._request_json_server(
                host=self.tts_host,
                port=self.tts_port,
                path="/health",
                timeout_seconds=2,
                service_name="TTS",
            )
        except VoiceBridgeError:
            return False
        expected_provider = DEFAULT_TTS_PROVIDER_NAME
        return bool(payload.get("ready")) and str(payload.get("provider", "")).strip() == expected_provider

    def _start_asr_server_process(self) -> None:
        if not self.sensevoice_python.exists():
            raise VoiceBridgeError(f"Missing ASR Python environment: {self.sensevoice_python}")
        if not self.sensevoice_server_script.exists():
            raise VoiceBridgeError(f"Missing ASR server script: {self.sensevoice_server_script}")

        log_path = self.logs_dir / f"sensevoice_server_{self._timestamp()}.log"
        if self._asr_server_log_handle is not None:
            self._asr_server_log_handle.close()
            self._asr_server_log_handle = None
        self._asr_server_log_handle = log_path.open("a", encoding="utf-8")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        self._asr_server_process = subprocess.Popen(
            [
                str(self.sensevoice_python),
                str(self.sensevoice_server_script),
                "--host",
                self.asr_host,
                "--port",
                str(self.asr_port),
                "--model-dir",
                str(self.sensevoice_model_dir),
                "--device",
                "auto",
            ],
            cwd=str(self.project_root),
            stdout=self._asr_server_log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )

    def _start_tts_server_process(self) -> None:
        self._start_sherpa_onnx_tts_server_process()

    def _start_sherpa_onnx_tts_server_process(self) -> None:
        tts_python = self.sherpa_python if self.sherpa_python.exists() else self.sherpa_fallback_python
        if not tts_python.exists():
            raise VoiceBridgeError(f"Missing sherpa-onnx TTS Python environment: {self.sherpa_python}")
        if not self.sherpa_server_script.exists():
            raise VoiceBridgeError(f"Missing sherpa-onnx TTS server script: {self.sherpa_server_script}")

        log_path = self.logs_dir / f"sherpa_onnx_tts_server_{self._timestamp()}.log"
        if self._tts_server_log_handle is not None:
            self._tts_server_log_handle.close()
            self._tts_server_log_handle = None
        self._tts_server_log_handle = log_path.open("a", encoding="utf-8")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        self._tts_server_process = subprocess.Popen(
            [
                str(tts_python),
                str(self.sherpa_server_script),
                "--host",
                self.tts_host,
                "--port",
                str(self.tts_port),
                "--model-dir",
                str(self.sherpa_model_dir),
                "--output-dir",
                str(self.sherpa_output_dir),
                "--cpu-threads",
                str(max(2, min(8, int(os.cpu_count() or 4)))),
                "--speaker-id",
                str(DEFAULT_TTS_VOICE),
            ],
            cwd=str(self.project_root),
            stdout=self._tts_server_log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )

    def _request_json_server(
        self,
        *,
        host: str,
        port: int,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout_seconds: int,
        service_name: str,
    ) -> dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        method = "GET"
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
            method = "POST"

        request = urllib.request.Request(
            url=f"http://{host}:{port}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                response_text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_text = exc.read().decode("utf-8", errors="replace")
            try:
                error_payload = json.loads(error_text)
                message = str(error_payload.get("message", "")).strip() or error_text
            except json.JSONDecodeError:
                message = error_text or str(exc)
            raise VoiceBridgeError(f"{service_name} server request failed: {message}") from exc
        except urllib.error.URLError as exc:
            raise VoiceBridgeError(f"{service_name} server unavailable: {exc}") from exc

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise VoiceBridgeError(f"Invalid {service_name} server response: {exc}") from exc

    def _build_asr_server_failure_message(self) -> str:
        if self._asr_server_process is None:
            return "ASR server is not running."
        log_hint = ""
        if self._asr_server_log_handle is not None:
            log_hint = f" Check log: {Path(self._asr_server_log_handle.name)}"
        return f"ASR server exited with code {self._asr_server_process.returncode}.{log_hint}"

    def _build_tts_server_failure_message(self) -> str:
        if self._tts_server_process is None:
            return "TTS server is not running."
        log_hint = ""
        if self._tts_server_log_handle is not None:
            log_hint = f" Check log: {Path(self._tts_server_log_handle.name)}"
        return f"TTS server exited with code {self._tts_server_process.returncode}.{log_hint}"

    def _read_tts_cache(self, cache_meta_path: Path, clean_text: str) -> dict[str, Any] | None:
        try:
            cached_payload = json.loads(cache_meta_path.read_text(encoding="utf-8"))
            cached_output_path = Path(str(cached_payload.get("output_path", ""))).resolve()
            if cached_output_path.exists() and cached_output_path.stat().st_size > 0:
                return {
                    "audio_path": str(cached_output_path),
                    "audio_url": self._build_session_url(cached_output_path),
                    "text": clean_text,
                    "tts_text": str(cached_payload.get("tts_text", "")).strip() or clean_text,
                    "cached": True,
                }
        except Exception:
            return None
        return None

    @staticmethod
    def _is_valid_asr_transcript(text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or "").strip())
        if not normalized:
            return False
        invalid_values = {
            ".",
            "。",
            "the",
            "the.",
            "The.",
            "字幕",
            "谢谢",
        }
        if normalized in invalid_values:
            return False
        if re.fullmatch(r"[\W_]+", normalized, flags=re.UNICODE):
            return False
        if normalized.count("�") >= max(1, len(normalized) // 2):
            return False
        return True

    @classmethod
    def _normalize_tts_text_to_chinese(cls, text: str) -> str:
        normalized = re.sub(r"\s+", " ", str(text or "").strip())
        if not normalized:
            return normalized

        normalized = normalized.replace(":", "点")
        normalized = normalized.replace(",", "，")
        normalized = normalized.replace(".", "。")
        normalized = re.sub(
            r"(\d{4})年(\d{1,2})月(\d{1,2})[日号]",
            lambda m: f"{cls._digits_to_chinese(m.group(1))}年{cls._int_to_chinese(int(m.group(2)))}月{cls._int_to_chinese(int(m.group(3)))}日",
            normalized,
        )
        normalized = re.sub(
            r"(?<!\d)(\d{1,2})月(\d{1,2})[日号]",
            lambda m: f"{cls._int_to_chinese(int(m.group(1)))}月{cls._int_to_chinese(int(m.group(2)))}日",
            normalized,
        )
        normalized = re.sub(
            r"(?<!\d)(\d{1,2})点(\d{2})(?!\d)",
            lambda m: cls._format_chinese_time(int(m.group(1)), int(m.group(2))),
            normalized,
        )
        normalized = re.sub(
            r"(?<!\d)(\d+)(号摄像头|号|条|起|个|名|次|人|分|点)",
            lambda m: f"{cls._int_to_chinese(int(m.group(1)))}{m.group(2)}",
            normalized,
        )
        normalized = re.sub(
            r"\d+",
            lambda m: cls._int_to_chinese(int(m.group(0))) if len(m.group(0)) <= 4 else cls._digits_to_chinese(m.group(0)),
            normalized,
        )
        return normalized

    @staticmethod
    def _digits_to_chinese(value: str) -> str:
        digit_map = {
            "0": "零",
            "1": "一",
            "2": "二",
            "3": "三",
            "4": "四",
            "5": "五",
            "6": "六",
            "7": "七",
            "8": "八",
            "9": "九",
        }
        return "".join(digit_map.get(ch, ch) for ch in str(value))

    @classmethod
    def _format_chinese_time(cls, hour: int, minute: int) -> str:
        hour_text = cls._int_to_chinese(hour)
        if minute == 0:
            return f"{hour_text}点整"
        return f"{hour_text}点{cls._int_to_chinese(minute)}分"

    @staticmethod
    def _int_to_chinese(value: int) -> str:
        value = int(value)
        if value == 0:
            return "零"
        if value < 0:
            return "负" + VoicePipelineBridge._int_to_chinese(abs(value))
        if value >= 10000:
            return VoicePipelineBridge._digits_to_chinese(str(value))

        digits = "零一二三四五六七八九"
        units = ["", "十", "百", "千"]
        chars = list(str(value))
        result: list[str] = []
        zero_pending = False
        length = len(chars)
        for idx, ch in enumerate(chars):
            digit = int(ch)
            unit_index = length - idx - 1
            if digit == 0:
                zero_pending = bool(result)
                continue
            if zero_pending:
                result.append("零")
                zero_pending = False
            if not (digit == 1 and unit_index == 1 and not result):
                result.append(digits[digit])
            result.append(units[unit_index])
        return "".join(result)

    def _build_session_url(self, file_path: Path) -> str:
        relative_path = Path(file_path).resolve().relative_to(self.data_root).as_posix()
        return f"/session_data/{relative_path}"

    @staticmethod
    def _build_tts_cache_key(
        text: str,
        *,
        speed: float,
        voice: str,
        provider: str = DEFAULT_TTS_PROVIDER,
        cache_version: str = DEFAULT_TTS_CACHE_VERSION,
    ) -> str:
        payload = json.dumps(
            {
                "text": str(text or "").strip(),
                "speed": round(float(speed), 3),
                "voice": str(voice or "").strip(),
                "provider": str(provider or "").strip(),
                "cache_version": str(cache_version or "").strip(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    @staticmethod
    def _random_suffix() -> str:
        return datetime.now().strftime("%f")[-4:]

    @staticmethod
    def _write_silence_wav(target_path: Path, duration_seconds: float) -> None:
        sample_rate = 16000
        frame_count = max(int(sample_rate * duration_seconds), 1)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(target_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"\x00\x00" * frame_count)

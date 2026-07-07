from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
import wave
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np
import sherpa_onnx


DEFAULT_MODEL_DIR = Path(r"D:\camera_agent_data\local_models\sherpa_onnx_tts\sherpa-onnx-vits-zh-ll")
DEFAULT_OUTPUT_DIR = Path(r"D:\camera_agent_data\_voice\outputs\sherpa_onnx")
DEFAULT_SPEAKER_ID = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persistent sherpa-onnx Chinese VITS TTS HTTP server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=5091, help="Bind port")
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR, help="sherpa-onnx VITS model directory")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Generated wav output directory")
    parser.add_argument("--cpu-threads", type=int, default=max(2, min(8, int(os.cpu_count() or 4))))
    parser.add_argument("--speaker-id", type=int, default=DEFAULT_SPEAKER_ID)
    return parser


def normalize_text_for_tts(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return "语音播报已就绪。"
    normalized = re.sub(r"```.*?```", " ", normalized, flags=re.S)
    normalized = re.sub(r"`([^`]+)`", r"\1", normalized)
    normalized = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", normalized)
    normalized = re.sub(r"https?://\S+", " ", normalized)
    normalized = normalized.replace("\r", " ").replace("\n", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or "语音播报已就绪。"


def write_wav(audio: Any, output_path: Path) -> None:
    samples = np.asarray(audio.samples)
    if samples.size <= 0:
        raise RuntimeError("sherpa-onnx generated empty audio.")
    if samples.dtype != np.int16:
        samples = np.clip(samples.astype(np.float32), -1.0, 1.0)
        samples = (samples * 32767).astype(np.int16)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(audio.sample_rate))
        wav_file.writeframes(samples.tobytes())


class SherpaOnnxTtsRuntime:
    def __init__(self, *, model_dir: Path, output_dir: Path, cpu_threads: int, speaker_id: int) -> None:
        self.model_dir = Path(model_dir).expanduser().resolve()
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.cpu_threads = max(1, int(cpu_threads))
        self.speaker_id = max(0, int(speaker_id))
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.lock = threading.Lock()
        self._tts: Any | None = None
        self._load_error = ""

    @property
    def loaded(self) -> bool:
        return self._tts is not None

    @property
    def load_error(self) -> str:
        return self._load_error

    def _require_file(self, name: str) -> Path:
        path = self.model_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Missing sherpa-onnx model file: {path}")
        return path

    def _ensure_runtime(self) -> Any:
        if self._tts is not None:
            return self._tts

        model = self._require_file("model.onnx")
        lexicon = self._require_file("lexicon.txt")
        tokens = self._require_file("tokens.txt")
        rule_fsts = ",".join(
            str(path)
            for path in (
                self.model_dir / "phone.fst",
                self.model_dir / "date.fst",
                self.model_dir / "number.fst",
            )
            if path.exists()
        )
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(model),
                    lexicon=str(lexicon),
                    tokens=str(tokens),
                    data_dir="",
                    length_scale=1.0,
                ),
                num_threads=self.cpu_threads,
                debug=False,
                provider="cpu",
            ),
            rule_fsts=rule_fsts,
            max_num_sentences=1,
            silence_scale=0.2,
        )
        if not config.validate():
            raise RuntimeError(f"Invalid sherpa-onnx TTS config. Model dir: {self.model_dir}")
        self._tts = sherpa_onnx.OfflineTts(config)
        return self._tts

    def synthesize(self, *, text: str, output_path: Path, speed: float, voice: str) -> dict[str, Any]:
        clean_text = str(text or "").strip()
        if not clean_text:
            return {"status": "error", "message": "Missing text content for synthesis"}

        spoken_text = normalize_text_for_tts(clean_text)
        output_path = Path(output_path).expanduser().resolve().with_suffix(".wav")
        speaker_id = self._parse_speaker_id(voice)
        speed_value = max(0.5, min(2.0, float(speed or 1.0)))

        with self.lock:
            try:
                runtime = self._ensure_runtime()
                if int(runtime.num_speakers) > 0:
                    speaker_id = min(max(0, speaker_id), int(runtime.num_speakers) - 1)
                start_time = time.perf_counter()
                audio = runtime.generate(spoken_text, sid=speaker_id, speed=speed_value)
                write_wav(audio, output_path)
                elapsed_seconds = time.perf_counter() - start_time
            except Exception as exc:
                self._load_error = f"{type(exc).__name__}: {exc}"
                return {"status": "error", "message": self._load_error}

        if not output_path.exists() or output_path.stat().st_size <= 0:
            return {"status": "error", "message": "sherpa-onnx did not generate a playable audio file."}

        return {
            "status": "success",
            "output_path": str(output_path),
            "text": clean_text,
            "spoken_text": spoken_text,
            "provider": "sherpa_onnx_vits_zh_ll",
            "device": "cpu",
            "voice": str(speaker_id),
            "speed": speed_value,
            "elapsed_seconds": round(float(elapsed_seconds), 3),
            "sample_rate": 16000,
        }

    def _parse_speaker_id(self, voice: str) -> int:
        raw = str(voice or "").strip()
        if not raw:
            return self.speaker_id
        match = re.search(r"\d+", raw)
        if not match:
            return self.speaker_id
        return int(match.group(0))


class SherpaOnnxTtsHandler(BaseHTTPRequestHandler):
    runtime: SherpaOnnxTtsRuntime | None = None

    def do_GET(self) -> None:
        if self.path == "/health":
            runtime = self.runtime
            self._send_json(
                {
                    "status": "success",
                    "ready": runtime is not None,
                    "loaded": bool(runtime.loaded) if runtime is not None else False,
                    "provider": "sherpa_onnx_vits_zh_ll",
                    "device": "cpu",
                    "message": runtime.load_error if runtime is not None else "",
                }
            )
            return
        self._send_json({"status": "error", "message": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/synthesize":
            self._send_json({"status": "error", "message": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if self.runtime is None:
            self._send_json({"status": "error", "message": "TTS runtime not ready"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            self._send_json({"status": "error", "message": f"Invalid request body: {exc}"}, status=HTTPStatus.BAD_REQUEST)
            return

        text = str(payload.get("text", "")).strip()
        output_path = Path(str(payload.get("output_path", "")).strip()).expanduser()
        speed = float(payload.get("speed", 1.0))
        voice = str(payload.get("voice", "")).strip()
        if not text:
            self._send_json({"status": "error", "message": "Missing text content for synthesis"}, status=HTTPStatus.BAD_REQUEST)
            return
        if not str(output_path).strip():
            self._send_json({"status": "error", "message": "Missing output_path"}, status=HTTPStatus.BAD_REQUEST)
            return

        result = self.runtime.synthesize(text=text, output_path=output_path, speed=speed, voice=voice)
        status = HTTPStatus.OK if str(result.get("status")).lower() == "success" else HTTPStatus.INTERNAL_SERVER_ERROR
        self._send_json(result, status=status)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    args = build_parser().parse_args()
    SherpaOnnxTtsHandler.runtime = SherpaOnnxTtsRuntime(
        model_dir=args.model_dir,
        output_dir=args.output_dir,
        cpu_threads=args.cpu_threads,
        speaker_id=args.speaker_id,
    )
    server = ThreadingHTTPServer((args.host, args.port), SherpaOnnxTtsHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import torch
from funasr import AutoModel


DEFAULT_MODEL_DIR = Path(r"D:\camera_agent_data\local_models\sensevoice\iic\SenseVoiceSmall")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persistent SenseVoice ASR HTTP server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=5092, help="Bind port")
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR, help="SenseVoiceSmall model directory")
    parser.add_argument("--device", default="auto", help="Inference device: auto, cuda:0, cpu")
    return parser


def resolve_device(raw_device: str) -> str:
    normalized = str(raw_device or "auto").strip().lower()
    if normalized != "auto":
        return raw_device
    return "cuda:0" if torch.cuda.is_available() else "cpu"


def clean_transcript(text: str) -> str:
    import re

    cleaned = re.sub(r"<\|[^>]+?\|>", " ", str(text or ""))
    cleaned = cleaned.replace("<unk>", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def extract_transcript(result: object) -> str:
    if isinstance(result, list):
        parts: list[str] = []
        for item in result:
            if isinstance(item, dict):
                item_text = item.get("text")
                if item_text:
                    parts.append(clean_transcript(str(item_text)))
        return " ".join(part for part in parts if part).strip()
    if isinstance(result, dict):
        return clean_transcript(str(result.get("text", "")))
    return clean_transcript(str(result or ""))


class SenseVoiceRuntime:
    def __init__(self, model_dir: Path, device: str) -> None:
        resolved_model_dir = Path(model_dir).resolve()
        if not resolved_model_dir.exists():
            raise FileNotFoundError(f"SenseVoice model directory not found: {resolved_model_dir}")
        self.model_dir = resolved_model_dir
        self.device = resolve_device(device)
        self.lock = threading.Lock()
        self.model = AutoModel(
            model=str(self.model_dir),
            device=self.device,
            trust_remote_code=True,
            disable_update=True,
        )

    def transcribe(self, audio_path: Path, *, language: str = "auto", batch_size_s: int = 30) -> dict:
        resolved_audio_path = Path(audio_path).resolve()
        if not resolved_audio_path.exists():
            return {"status": "error", "message": f"Audio file not found: {resolved_audio_path}"}

        with self.lock:
            result = self.model.generate(
                input=str(resolved_audio_path),
                cache={},
                language=language,
                use_itn=True,
                batch_size_s=batch_size_s,
            )

        transcript = extract_transcript(result)
        return {
            "status": "success",
            "text": transcript,
            "audio_path": str(resolved_audio_path),
            "device": self.device,
        }


class SenseVoiceHandler(BaseHTTPRequestHandler):
    runtime: SenseVoiceRuntime | None = None

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(
                {
                    "status": "success",
                    "ready": self.runtime is not None,
                }
            )
            return
        self._send_json({"status": "error", "message": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/transcribe":
            self._send_json({"status": "error", "message": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if self.runtime is None:
            self._send_json({"status": "error", "message": "ASR runtime not ready"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            self._send_json({"status": "error", "message": f"Invalid request body: {exc}"}, status=HTTPStatus.BAD_REQUEST)
            return

        audio_path = Path(str(payload.get("audio_path", "")).strip()).expanduser()
        language = str(payload.get("language", "auto")).strip() or "auto"
        batch_size_s = int(payload.get("batch_size_s", 30))
        if not str(audio_path).strip():
            self._send_json({"status": "error", "message": "Missing audio_path"}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            result = self.runtime.transcribe(audio_path, language=language, batch_size_s=batch_size_s)
            status = HTTPStatus.OK if str(result.get("status", "success")).lower() == "success" else HTTPStatus.BAD_REQUEST
            self._send_json(result, status=status)
        except Exception as exc:  # pragma: no cover
            self._send_json({"status": "error", "message": f"{type(exc).__name__}: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    args = build_parser().parse_args()
    runtime = SenseVoiceRuntime(model_dir=args.model_dir, device=args.device)
    SenseVoiceHandler.runtime = runtime
    server = ThreadingHTTPServer((args.host, args.port), SenseVoiceHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

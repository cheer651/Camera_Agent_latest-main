from __future__ import annotations

import atexit
import json
import mimetypes
import os
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file, send_from_directory, stream_with_context

from monitoring_service import MonitoringOrchestrator
from voice_bridge import DEFAULT_TTS_SPEED, DEFAULT_TTS_VOICE, VoiceBridgeError, VoicePipelineBridge


app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
XIAOAN_NO_RESULT_TEXT = "未发现相关异常记录。"
config_path = os.environ.get("CAMERA_CONFIG_PATH", "camera_config.json")
prompt_path = os.environ.get("PROMPT_PATH", "prompt.txt")
orchestrator = MonitoringOrchestrator(config_path=config_path, prompt_path=prompt_path)
voice_bridge = VoicePipelineBridge(project_root=Path(app.root_path), data_root=orchestrator.base_dir)
atexit.register(orchestrator.shutdown)
atexit.register(voice_bridge.shutdown)


def _warmup_voice_services() -> None:
    try:
        voice_bridge.ensure_services_ready()
        voice_bridge.prime_common_tts_cache(
            [
                "我在。",
                XIAOAN_NO_RESULT_TEXT,
                "正在为您查询，请稍候。",
            ]
        )
    except Exception as exc:
        print(f"[voice] service warmup skipped: {exc}")


threading.Thread(target=_warmup_voice_services, daemon=True).start()


def _query_bool(name: str, default: bool = False) -> bool:
    raw_value = request.args.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _chunk_stream_text(text: str, chunk_size: int = 14) -> list[str]:
    chunks: list[str] = []
    buffer = ""
    punctuation_chars = {"\n", "\uFF0C", "\u3002", "\uFF01", "\uFF1F", "\uFF1B", ",", ".", "!", "?", ";"}
    for char in str(text or ""):
        buffer += char
        if len(buffer) >= chunk_size or char in punctuation_chars:
            chunks.append(buffer)
            buffer = ""
    if buffer:
        chunks.append(buffer)
    return chunks or [""]


def _build_asset_version(*paths: Path) -> int:
    existing_paths = [path for path in paths if path.exists()]
    if not existing_paths:
        return int(time.time())
    return max(int(path.stat().st_mtime) for path in existing_paths)


def _get_xiaoan_cached_audio_path(text: str) -> Path:
    speech = voice_bridge.synthesize_text(text, use_cache=True)
    audio_path = Path(str(speech.get("audio_path", "")).strip())
    if not audio_path.exists() or audio_path.stat().st_size <= 0:
        raise VoiceBridgeError("语音缓存文件不存在。")
    return audio_path


def _build_stream_response(question: str, history: list[dict[str, str]], answer_callable, *, include_audio: bool = False) -> Response:
    def generate():
        yield _sse({"type": "start"})
        if not question.strip():
            yield _sse({"type": "error", "message": "\u8bf7\u8f93\u5165\u8981\u67e5\u8be2\u7684\u95ee\u9898\u3002"})
            return

        try:
            result = answer_callable(question, history=history)
            answer = str(result.get("answer", "")).strip() or "\u672a\u8fd4\u56de\u6709\u6548\u7ed3\u679c\u3002"

            for chunk in _chunk_stream_text(answer):
                yield _sse({"type": "delta", "text": chunk})
                time.sleep(0.01)

            done_payload = {
                "type": "done",
                "answer": answer,
                "references": result.get("references", []),
                "used_llm": bool(result.get("used_llm", False)),
                "standalone_question": str(result.get("standalone_question", question.strip())),
            }
            if include_audio:
                done_payload["speech_text"] = str(result.get("speech_text", "")).strip()

            yield _sse(done_payload)
        except Exception as exc:
            yield _sse({"type": "error", "message": f"\u67e5\u8be2\u5931\u8d25\uff1a{exc}"})

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return Response(stream_with_context(generate()), mimetype="text/event-stream", headers=headers)


@app.route("/")
def index() -> str:
    asset_version = _build_asset_version(
        Path(app.root_path) / "templates" / "index.html",
        Path(app.root_path) / "static" / "css" / "style.css",
        Path(app.root_path) / "static" / "js" / "script.js",
    )
    return render_template("index.html", asset_version=asset_version)


@app.route("/dashboard")
def dashboard() -> str:
    asset_version = _build_asset_version(
        Path(app.root_path) / "templates" / "dashboard.html",
        Path(app.root_path) / "static" / "css" / "dashboard.css",
        Path(app.root_path) / "static" / "js" / "dashboard" / "main.js",
        Path(app.root_path) / "static" / "img" / "xiaoan-logo.png",
        Path(app.root_path) / "static" / "vendor" / "vue.esm-browser.prod.js",
    )
    return render_template("dashboard.html", asset_version=asset_version)


@app.route("/video_feed/<camera_id>")
def video_feed(camera_id: str) -> Response:
    camera_service = orchestrator.get_camera_service(camera_id)
    if camera_service is None:
        return Response("未找到对应摄像头。", status=404)

    def generate() -> bytes:
        while True:
            frame_bytes = camera_service.get_frame_bytes()
            if frame_bytes is not None:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                )
            else:
                time.sleep(0.1)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/overview")
def get_overview():
    return jsonify(orchestrator.get_overview())


@app.get("/api/dashboard")
def get_dashboard():
    payload = orchestrator.get_dashboard_payload()
    assistant_payload = dict(payload.get("assistant") or {})
    assistant_payload["no_result_audio_url"] = (
        f"/api/xiaoan/voice/cached/no-result?voice={DEFAULT_TTS_VOICE}&speed={DEFAULT_TTS_SPEED}"
    )
    payload["assistant"] = assistant_payload
    return jsonify(payload)


@app.get("/api/cameras")
def get_cameras():
    return jsonify(orchestrator.get_cameras_overview())


@app.get("/api/status")
def get_status():
    return jsonify(orchestrator.get_task_status())


@app.get("/api/logs")
@app.get("/api/get_logs")
def get_logs():
    return jsonify(orchestrator.get_logs())


@app.get("/api/events")
@app.get("/api/get_report")
def get_events():
    query_date = request.args.get("date")
    return jsonify(orchestrator.get_events_for_date(query_date))


@app.get("/api/summaries")
def get_summary_for_date():
    query_date = request.args.get("date")
    regenerate = _query_bool("regenerate", default=False)
    send_to_feishu = _query_bool("send_to_feishu", default=False)
    return jsonify(
        orchestrator.get_summary_for_date(
            summary_date=query_date,
            regenerate=regenerate,
            send_to_feishu=send_to_feishu,
        )
    )


@app.get("/api/summaries/latest")
def get_latest_summary():
    return jsonify(orchestrator.get_latest_summary() or {})


@app.post("/api/tasks/start")
@app.post("/api/start_task")
def start_task():
    payload = request.get_json(silent=True) or {}
    result = orchestrator.start_task(
        camera_ids=payload.get("camera_ids"),
        duration_seconds=payload.get("duration_seconds"),
    )
    status_code = 200 if result.get("status") == "success" else 400
    return jsonify(result), status_code


@app.post("/api/reports/daily")
def generate_daily_report():
    payload = request.get_json(silent=True) or {}
    result = orchestrator.generate_daily_summary(
        summary_date=payload.get("date"),
        send_to_feishu=bool(payload.get("send_to_feishu", False)),
    )
    return jsonify(result)


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", ""))
    raw_history = payload.get("history", [])
    history = raw_history if isinstance(raw_history, list) else []
    return jsonify(orchestrator.answer_question(question, history=history))


@app.post("/api/chat/stream")
def chat_stream():
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", ""))
    raw_history = payload.get("history", [])
    history = raw_history if isinstance(raw_history, list) else []
    return _build_stream_response(question, history, orchestrator.answer_question, include_audio=False)


@app.post("/api/xiaoan/chat/stream")
def xiaoan_chat_stream():
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", ""))
    raw_history = payload.get("history", [])
    history = raw_history if isinstance(raw_history, list) else []
    return _build_stream_response(question, history, orchestrator.answer_xiaoan_question, include_audio=True)


@app.post("/api/voice/transcribe")
def voice_transcribe():
    audio_file = request.files.get("audio")
    if audio_file is None:
        return jsonify({"message": "缺少音频文件。"}), 400

    try:
        audio_path = voice_bridge.save_uploaded_audio(audio_file)
        return jsonify(voice_bridge.transcribe_file(audio_path))
    except VoiceBridgeError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"message": f"语音转写失败: {exc}"}), 500


@app.post("/api/voice/speak")
def voice_speak():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    use_cache = bool(payload.get("use_cache", True))
    if not text:
        return jsonify({"message": "缺少要播报的文本内容。"}), 400

    try:
        return jsonify(voice_bridge.synthesize_text(text, use_cache=use_cache))
    except VoiceBridgeError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"message": f"语音合成失败: {exc}"}), 500


@app.post("/api/voice/audio")
def voice_audio():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    use_cache = bool(payload.get("use_cache", True))
    if not text:
        return jsonify({"message": "缺少要播报的文本内容。"}), 400

    try:
        speech = voice_bridge.synthesize_text(text, use_cache=use_cache)
        audio_path = Path(str(speech.get("audio_path", "")).strip())
        if not audio_path.exists() or audio_path.stat().st_size <= 0:
            return jsonify({"message": "语音文件生成失败。"}), 500
        mimetype = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
        return send_file(audio_path, mimetype=mimetype, as_attachment=False, max_age=0)
    except VoiceBridgeError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"message": f"语音音频输出失败: {exc}"}), 500


@app.post("/api/xiaoan/voice/transcribe")
def xiaoan_voice_transcribe():
    return voice_transcribe()


@app.post("/api/xiaoan/voice/speak")
def xiaoan_voice_speak():
    return voice_speak()


@app.post("/api/xiaoan/voice/audio")
def xiaoan_voice_audio():
    return voice_audio()


@app.get("/api/xiaoan/voice/cached/no-result")
def xiaoan_cached_no_result_audio():
    try:
        audio_path = _get_xiaoan_cached_audio_path(XIAOAN_NO_RESULT_TEXT)
        mimetype = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
        response = send_file(audio_path, mimetype=mimetype, as_attachment=False, max_age=31536000)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
    except VoiceBridgeError as exc:
        return jsonify({"message": str(exc)}), 400
    except Exception as exc:
        return jsonify({"message": f"读取缓存语音失败: {exc}"}), 500


@app.route("/session_data/<path:filename>")
def serve_session_data(filename: str):
    return send_from_directory(str(orchestrator.base_dir), filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)

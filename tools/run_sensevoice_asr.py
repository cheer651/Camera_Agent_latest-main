from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import torch
from funasr import AutoModel


DEFAULT_MODEL_DIR = Path(r"D:\camera_agent_data\local_models\sensevoice\iic\SenseVoiceSmall")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SenseVoiceSmall ASR runner")
    parser.add_argument("--audio", type=Path, required=True, help="Input audio file path")
    parser.add_argument("--output-json", type=Path, required=True, help="Output JSON file path")
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR, help="SenseVoiceSmall model directory")
    parser.add_argument("--device", default="auto", help="Inference device: auto, cuda:0, cpu")
    parser.add_argument("--language", default="auto", help="Language hint for SenseVoice")
    parser.add_argument("--batch-size-s", type=int, default=30, help="Batch size seconds")
    return parser


def resolve_device(raw_device: str) -> str:
    if raw_device != "auto":
        return raw_device
    return "cuda:0" if torch.cuda.is_available() else "cpu"


def clean_transcript(text: str) -> str:
    cleaned = re.sub(r"<\|[^>]+?\|>", " ", str(text or ""))
    cleaned = cleaned.replace("<unk>", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def extract_transcript(result: object) -> str:
    if isinstance(result, list):
        parts = []
        for item in result:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(clean_transcript(str(text)))
        return " ".join(part for part in parts if part).strip()
    if isinstance(result, dict):
        return clean_transcript(str(result.get("text", "")))
    return clean_transcript(str(result or ""))


def write_payload(target_path: Path, payload: dict) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = build_parser().parse_args()
    audio_path = args.audio.resolve()
    model_dir = args.model_dir.resolve()
    output_path = args.output_json.resolve()

    if not audio_path.exists():
        write_payload(output_path, {"status": "error", "message": f"Input audio not found: {audio_path}"})
        return 1
    if not model_dir.exists():
        write_payload(output_path, {"status": "error", "message": f"Model directory not found: {model_dir}"})
        return 1

    try:
        device = resolve_device(args.device)
        model = AutoModel(
            model=str(model_dir),
            device=device,
            disable_update=True,
        )
        result = model.generate(
            input=str(audio_path),
            cache={},
            language=args.language,
            use_itn=True,
            batch_size_s=args.batch_size_s,
        )
        transcript = extract_transcript(result)
        write_payload(
            output_path,
            {
                "status": "success",
                "text": transcript,
                "audio_path": str(audio_path),
                "device": device,
            },
        )
        return 0
    except Exception as exc:  # pragma: no cover
        write_payload(output_path, {"status": "error", "message": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

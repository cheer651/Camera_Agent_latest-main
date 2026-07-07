from __future__ import annotations

import argparse
import json
from pathlib import Path

from funasr import AutoModel


DEFAULT_MODEL_DIR = Path(r"D:\camera_agent_data\local_models\sensevoice\iic\SenseVoiceSmall")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SenseVoiceSmall 本地转写测试脚本")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=DEFAULT_MODEL_DIR,
        help="SenseVoiceSmall 模型目录",
    )
    parser.add_argument(
        "--audio",
        type=Path,
        default=None,
        help="待转写音频路径；默认使用模型目录下的 example/zh.mp3",
    )
    parser.add_argument(
        "--device",
        default="cuda:0",
        help="推理设备，例如 cuda:0 或 cpu",
    )
    parser.add_argument(
        "--language",
        default="auto",
        help="语言参数，默认 auto",
    )
    parser.add_argument(
        "--batch-size-s",
        type=int,
        default=30,
        help="批处理时长参数",
    )
    return parser


def resolve_audio_path(model_dir: Path, audio_path: Path | None) -> Path:
    if audio_path is not None:
        return audio_path
    return model_dir / "example" / "zh.mp3"


def main() -> int:
    args = build_parser().parse_args()
    model_dir = args.model_dir.resolve()
    audio_path = resolve_audio_path(model_dir, args.audio).resolve()

    if not model_dir.exists():
        raise FileNotFoundError(f"模型目录不存在: {model_dir}")
    if not audio_path.exists():
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")

    print(f"模型目录: {model_dir}")
    print(f"音频文件: {audio_path}")
    print(f"推理设备: {args.device}")

    model = AutoModel(
        model=str(model_dir),
        device=args.device,
        disable_update=True,
    )

    result = model.generate(
        input=str(audio_path),
        cache={},
        language=args.language,
        use_itn=True,
        batch_size_s=args.batch_size_s,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

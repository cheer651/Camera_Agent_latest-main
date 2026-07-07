from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from sentence_transformers import SentenceTransformer


MODEL_CACHE_ROOT = Path(r"D:\Qwen3-Embedding-0.6B")
MODEL_REPO_DIR = MODEL_CACHE_ROOT / "models--Qwen--Qwen3-Embedding-0.6B"
MODEL_REF_FILE = MODEL_REPO_DIR / "refs" / "main"
DATA_ROOT = Path(r"D:\camera_agent_data")
MATERIALIZED_MODEL_DIR = DATA_ROOT / "local_models" / "qwen3_embedding_0_6b"


def resolve_model_path() -> Path:
    # 优先使用已实体化的模型目录（兼容直接拷贝模型文件的情况）
    if MATERIALIZED_MODEL_DIR.exists() and (MATERIALIZED_MODEL_DIR / "model.safetensors").exists():
        return MATERIALIZED_MODEL_DIR

    if MODEL_REF_FILE.exists():
        revision = MODEL_REF_FILE.read_text(encoding="utf-8").strip()
        snapshot_path = MODEL_REPO_DIR / "snapshots" / revision
        if snapshot_path.exists():
            return snapshot_path

    snapshots_dir = MODEL_REPO_DIR / "snapshots"
    if snapshots_dir.exists():
        snapshots = sorted([path for path in snapshots_dir.iterdir() if path.is_dir()])
        if snapshots:
            return snapshots[-1]

    raise FileNotFoundError(
        "未找到本地 Qwen3-Embedding-0.6B 模型，请检查 D 盘模型缓存或实体化目录是否完整。"
    )


def resolve_blob_file(source_path: Path) -> Path:
    command = ["fsutil", "reparsepoint", "query", str(source_path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    output = f"{result.stdout}\n{result.stderr}"
    hex_bytes = re.findall(r"\b[0-9a-fA-F]{2}\b", output)
    relative_target = ""
    if len(hex_bytes) > 4:
        try:
            relative_target = bytes.fromhex("".join(hex_bytes[4:])).decode("utf-8", errors="ignore")
        except ValueError:
            relative_target = ""

    match = re.search(r"blobs/([0-9a-f]{8,64})", relative_target)
    if not match:
        raise FileNotFoundError(f"无法解析模型快照链接文件：{source_path}")
    blob_path = MODEL_REPO_DIR / "blobs" / match.group(1)
    if not blob_path.exists():
        raise FileNotFoundError(f"快照文件对应的 blob 不存在：{blob_path}")
    return blob_path


def materialize_model(snapshot_path: Path) -> Path:
    target_dir = MATERIALIZED_MODEL_DIR
    if (target_dir / "modules.json").exists() and (target_dir / "model.safetensors").exists():
        return target_dir

    print(f"检测到 Hugging Face 快照为链接结构，正在实体化到：{target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)

    for root, dirs, files in os.walk(snapshot_path):
        relative_root = Path(root).relative_to(snapshot_path)
        destination_root = target_dir / relative_root
        destination_root.mkdir(parents=True, exist_ok=True)

        for dirname in dirs:
            (destination_root / dirname).mkdir(parents=True, exist_ok=True)

        for filename in files:
            source_file = Path(root) / filename
            destination_file = destination_root / filename
            if destination_file.exists():
                continue

            try:
                shutil.copyfile(source_file, destination_file)
                continue
            except OSError:
                pass

            blob_file = resolve_blob_file(source_file)
            shutil.copyfile(blob_file, destination_file)

    return target_dir


def preferred_device() -> str:
    forced = os.getenv("EMBEDDING_DEVICE", "").strip().lower()
    if forced in {"cpu", "cuda"}:
        return forced
    return "cuda" if torch.cuda.is_available() else "cpu"


def load_model(model_path: Path) -> tuple[SentenceTransformer, str]:
    device = preferred_device()
    print(f"正在加载本地向量模型：{model_path}")
    print(f"优先设备：{device}")

    try:
        model = SentenceTransformer(str(model_path), device=device, trust_remote_code=True)
        if device == "cuda":
            model.encode(
                ["系统启动自检"],
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        return model, device
    except Exception as exc:
        if device != "cuda":
            raise
        print(f"CUDA 加载失败，自动回退到 CPU。原因：{exc}")
        model = SentenceTransformer(str(model_path), device="cpu", trust_remote_code=True)
        return model, "cpu"


app = FastAPI(title="本地 Embedding API", version="1.0.0")

SNAPSHOT_PATH = resolve_model_path()
MODEL_PATH = materialize_model(SNAPSHOT_PATH)
MODEL, ACTIVE_DEVICE = load_model(MODEL_PATH)

print(f"模型已就绪，当前设备：{ACTIVE_DEVICE}")
print("服务地址：http://127.0.0.1:8080/embed")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model_path": str(MODEL_PATH),
        "device": ACTIVE_DEVICE,
    }


@app.post("/embed")
async def get_embeddings(request_data: dict[str, Any]) -> list[list[float]]:
    inputs = request_data.get("inputs", [])

    if isinstance(inputs, str):
        inputs = [inputs]

    if not isinstance(inputs, list) or not inputs:
        raise HTTPException(status_code=400, detail="inputs 必须是非空字符串或字符串列表。")

    if not all(isinstance(item, str) and item.strip() for item in inputs):
        raise HTTPException(status_code=400, detail="inputs 中的每一项都必须是非空字符串。")

    embeddings = MODEL.encode(
        inputs,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return embeddings.tolist()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")

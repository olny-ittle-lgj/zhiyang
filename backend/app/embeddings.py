from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import settings


VECTOR_DIM = 1024
DEFAULT_BGE_M3_MODEL = "BAAI/bge-m3"


class StandardRuntimeError(RuntimeError):
    """Raised when a PRD-standard AI runtime dependency is missing."""


def _runtime_message(detail: str) -> str:
    return (
        f"{detail}。标准模式需要 sentence-transformers 与 BGE-M3 模型，"
        "请安装依赖并保证模型可下载，或将 BGE_M3_MODEL 指向本地模型目录。"
    )


def _local_model_snapshot(model_name: str) -> str | None:
    model_path = Path(model_name).expanduser()
    if model_path.is_dir():
        return str(model_path)
    if "/" not in model_name:
        return None
    cache_root = settings.model_cache_dir / f"models--{model_name.replace('/', '--')}" / "snapshots"
    if not cache_root.is_dir():
        return None
    required = {"config.json", "modules.json"}
    candidates = []
    for snapshot in cache_root.iterdir():
        if not snapshot.is_dir():
            continue
        names = {item.name for item in snapshot.iterdir() if item.is_file()}
        has_weights = any(name in names for name in ("pytorch_model.bin", "model.safetensors", "model.safetensors.index.json"))
        if required.issubset(names) and has_weights:
            candidates.append(snapshot)
    if not candidates:
        return None
    return str(max(candidates, key=lambda item: item.stat().st_mtime))


@lru_cache(maxsize=1)
def _embedding_model() -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise StandardRuntimeError(_runtime_message("缺少 sentence-transformers 运行环境")) from exc

    model_name = settings.bge_m3_model.strip() or DEFAULT_BGE_M3_MODEL
    device = settings.bge_m3_device.strip() or None
    backend = settings.bge_m3_backend if settings.bge_m3_backend in {"torch", "onnx", "openvino"} else "torch"
    kwargs: dict[str, Any] = {}
    if device:
        kwargs["device"] = device
    kwargs["cache_folder"] = str(settings.model_cache_dir)
    model_kwargs: dict[str, Any] = {}
    if backend == "onnx":
        model_kwargs["provider"] = "CPUExecutionProvider"
        if settings.bge_m3_onnx_file:
            model_kwargs["file_name"] = settings.bge_m3_onnx_file
    model_source = _local_model_snapshot(model_name) or model_name
    try:
        return SentenceTransformer(model_source, backend=backend, model_kwargs=model_kwargs or None, **kwargs)
    except Exception as exc:
        raise StandardRuntimeError(_runtime_message(f"BGE-M3 模型加载失败：{str(exc)[:180]}")) from exc


def bge_m3_embedding(text: str) -> list[float]:
    value = str(text or "").strip()
    if not value:
        raise StandardRuntimeError("无法为空文本生成 BGE-M3 向量")
    model = _embedding_model()
    try:
        vector = model.encode(value, normalize_embeddings=True)
    except Exception as exc:
        raise StandardRuntimeError(_runtime_message(f"BGE-M3 向量化失败：{str(exc)[:180]}")) from exc
    result = [float(item) for item in vector.tolist()]
    if len(result) != VECTOR_DIM:
        raise StandardRuntimeError(f"BGE-M3 向量维度应为 {VECTOR_DIM}，当前为 {len(result)}")
    return result


def embedding_runtime_status() -> dict[str, str]:
    try:
        _embedding_model()
    except StandardRuntimeError as exc:
        return {
            "status": "missing",
            "model": settings.bge_m3_model or DEFAULT_BGE_M3_MODEL,
            "detail": str(exc),
        }
    return {
        "status": "active",
        "model": settings.bge_m3_model or DEFAULT_BGE_M3_MODEL,
        "detail": "BGE-M3 embedding runtime is ready",
    }

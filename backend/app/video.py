from __future__ import annotations

import re
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import settings
from .ocr import OcrError, extract_image_text


class VideoAnalysisError(RuntimeError):
    """Raised when a video cannot be inspected or text cannot be extracted."""


def _ffmpeg_executable() -> str:
    configured = os.getenv("FFMPEG_BINARY", "").strip()
    if configured and Path(configured).is_file():
        return configured
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise VideoAnalysisError(
            "视频解析组件不可用，请安装 requirements.txt 中的 imageio-ffmpeg，"
            "或通过 FFMPEG_BINARY 配置 FFmpeg 路径"
        ) from exc


def _run_ffmpeg(arguments: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            [_ffmpeg_executable(), *arguments],
            capture_output=True,
            check=False,
            timeout=timeout or settings.video_analysis_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise VideoAnalysisError("视频分析超时，请缩短视频或稍后重试") from exc
    except OSError as exc:
        raise VideoAnalysisError("视频解析组件启动失败") from exc


def _probe_video(path: Path) -> dict[str, int | float]:
    # FFmpeg prints container metadata before requiring an output target, so
    # probing does not need to decode the complete video.
    result = _run_ffmpeg(["-hide_banner", "-i", str(path)])
    output = result.stderr.decode("utf-8", errors="replace")
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    duration = 0.0
    if duration_match:
        hours, minutes, seconds = duration_match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    dimensions_match = re.search(r"\b(\d{2,5})x(\d{2,5})(?:\s|,)", output)
    if not dimensions_match:
        raise VideoAnalysisError("上传文件中没有可读取的视频流")
    width, height = (int(value) for value in dimensions_match.groups())
    if duration <= 0:
        raise VideoAnalysisError("无法读取视频时长")
    if duration > settings.video_max_duration_seconds:
        raise VideoAnalysisError("视频时长超过分析限制")
    if width * height > settings.video_max_pixels:
        raise VideoAnalysisError("视频分辨率超过分析限制")
    return {"duration": round(duration, 2), "width": width, "height": height}


def _subtitle_text(path: Path) -> list[str]:
    result = _run_ffmpeg(["-v", "error", "-i", str(path), "-map", "0:s:0?", "-f", "srt", "-"])
    if result.returncode != 0 or not result.stdout:
        return []
    text = result.stdout.decode("utf-8", errors="replace")
    cues: list[str] = []
    for block in re.split(r"\r?\n\s*\r?\n", text):
        lines: list[str] = []
        for line in block.splitlines():
            clean = re.sub(r"<[^>]+>", "", line).strip()
            if not clean or clean.isdigit() or "-->" in clean:
                continue
            lines.append(clean)
        cue = " ".join(lines).strip()
        if cue:
            cues.append(cue)
    return cues


def _frame_times(duration: float) -> list[float]:
    count = max(1, min(settings.video_ocr_frame_count, 6))
    if duration <= 0:
        return [0.0]
    return [round(duration * (index + 1) / (count + 1), 2) for index in range(count)]


def _keyframe_text(path: Path, duration: float) -> tuple[list[str], int, float]:
    texts: list[str] = []
    confidence_values: list[float] = []
    extracted_frames = 0
    for second in _frame_times(duration):
        result = _run_ffmpeg([
            "-v", "error", "-ss", str(second), "-i", str(path),
            "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
        ])
        if result.returncode != 0 or not result.stdout:
            continue
        extracted_frames += 1
        try:
            ocr = extract_image_text(result.stdout)
        except OcrError:
            continue
        content = str(ocr.get("content", "")).strip()
        if content:
            texts.append(content)
            confidence_values.append(float(ocr.get("confidence", 0)))
    return texts, extracted_frames, (sum(confidence_values) / len(confidence_values) if confidence_values else 0.0)


def _deduplicate(lines: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        clean = re.sub(r"\s+", " ", line).strip()
        key = clean.casefold()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def analyze_video_text(data: bytes, extension: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="zhiyan-video-") as directory:
        source = Path(directory) / f"source{extension}"
        source.write_bytes(data)
        metadata = _probe_video(source)
        subtitles = _subtitle_text(source)
        keyframe_texts, keyframes, confidence = _keyframe_text(source, float(metadata["duration"]))

    subtitle_lines = _deduplicate(subtitles)
    frame_lines = _deduplicate([
        line
        for frame_text in keyframe_texts
        for line in frame_text.splitlines()
    ])
    content_parts: list[str] = []
    if subtitle_lines:
        content_parts.append("\n".join(subtitle_lines))
    if frame_lines:
        content_parts.append("\n\n".join(frame_lines))
    content = "\n\n".join(content_parts).strip()
    return {
        **metadata,
        "content": content,
        "subtitle_lines": len(subtitle_lines),
        "keyframes": keyframes,
        "confidence": round(confidence, 4),
    }

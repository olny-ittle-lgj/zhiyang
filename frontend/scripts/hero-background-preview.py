from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image


def target_background(height: int, width: int) -> np.ndarray:
    start = np.array([5, 23, 41], dtype=np.float32)
    middle = np.array([11, 32, 50], dtype=np.float32)
    end = np.array([14, 36, 52], dtype=np.float32)
    y, x = np.indices((height, width), dtype=np.float32)
    progress = np.clip((x + y) / max(width + height - 2, 1), 0, 1)
    first = np.clip(progress / 0.52, 0, 1)[..., None]
    second = np.clip((progress - 0.52) / 0.48, 0, 1)[..., None]
    background = start * (1 - first) + middle * first
    background = np.where((progress > 0.52)[..., None], middle * (1 - second) + end * second, background)
    return background.astype(np.uint8)


def border_connected(candidate: np.ndarray) -> np.ndarray:
    """Return only candidate pixels that can be reached from the image edge."""
    height, width = candidate.shape
    connected = np.zeros((height, width), dtype=bool)
    queue: deque[tuple[int, int]] = deque()

    def enqueue(row: int, column: int) -> None:
        if candidate[row, column] and not connected[row, column]:
            connected[row, column] = True
            queue.append((row, column))

    for column in range(width):
        enqueue(0, column)
        enqueue(height - 1, column)
    for row in range(1, height - 1):
        enqueue(row, 0)
        enqueue(row, width - 1)

    while queue:
        row, column = queue.popleft()
        if row > 0:
            enqueue(row - 1, column)
        if row + 1 < height:
            enqueue(row + 1, column)
        if column > 0:
            enqueue(row, column - 1)
        if column + 1 < width:
            enqueue(row, column + 1)

    return connected


def background_mask(image: Image.Image, analysis_width: int = 960) -> np.ndarray:
    analysis_width = min(max(analysis_width, 256), image.width)
    analysis_height = max(1, round(image.height * analysis_width / image.width))
    reduced = image.resize((analysis_width, analysis_height), Image.Resampling.BILINEAR)
    pixels = np.asarray(reduced, dtype=np.float32)

    # The top and left margins remain clear of the bust in every hero frame.
    sample_size = max(8, min(analysis_height // 18, 48))
    border = np.concatenate(
        [pixels[:sample_size].reshape(-1, 3), pixels[:, :sample_size].reshape(-1, 3)],
        axis=0,
    )
    background_color = np.median(border, axis=0)
    brightness = pixels.mean(axis=2)
    chroma = pixels.max(axis=2) - pixels.min(axis=2)
    color_distance = np.linalg.norm(pixels - background_color, axis=2)

    # A strict color-distance gate protects the colored face highlights. The
    # flood fill then removes only background-like pixels connected to an edge.
    candidate = (brightness > 125) & (chroma < 70) & (color_distance < 58)
    reduced_background = border_connected(candidate)
    coarse_mask = np.asarray(
        Image.fromarray((reduced_background.astype(np.uint8) * 255), mode="L").resize(
            image.size, Image.Resampling.BICUBIC
        ),
        dtype=np.float32,
    ) / 255.0

    # Refine the final edge at source resolution so the 960px flood fill does
    # not introduce visible stair-stepping around the bust.
    full_pixels = np.asarray(image, dtype=np.float32)
    full_brightness = full_pixels.mean(axis=2)
    full_chroma = full_pixels.max(axis=2) - full_pixels.min(axis=2)
    full_distance = np.linalg.norm(full_pixels - background_color, axis=2)
    full_candidate = (full_brightness > 125) & (full_chroma < 70) & (full_distance < 58)
    return full_candidate.astype(np.float32) * np.clip(coarse_mask, 0, 1)


def replace_background(source: Path, destination: Path, analysis_width: int = 960) -> float:
    image = Image.open(source).convert("RGB")
    source_pixels = np.asarray(image, dtype=np.float32)
    background = background_mask(image, analysis_width)
    foreground = 1.0 - background
    replacement = target_background(image.height, image.width).astype(np.float32)
    result = source_pixels * foreground[..., None] + replacement * background[..., None]
    result = Image.fromarray(np.clip(result, 0, 255).astype(np.uint8), mode="RGB")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.lower() == ".webp":
        result.save(destination, format="WEBP", lossless=True, method=6)
    else:
        result.save(destination, format="PNG", compress_level=3)
    return float(background.mean())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--analysis-width", type=int, default=960)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--end-index", type=int, default=None)
    args = parser.parse_args()
    if args.source.is_dir():
        sources = sorted(args.source.glob("frame-*.webp"))
        if not sources:
            raise RuntimeError(f"No hero frames found in {args.source}")
        sources = sources[args.start_index : args.end_index + 1 if args.end_index is not None else None]
        args.destination.mkdir(parents=True, exist_ok=True)
        for index, source in enumerate(sources, start=1):
            destination = args.destination / source.name
            ratio = replace_background(source, destination, args.analysis_width)
            print(f"[{index}/{len(sources)}] {source.name} background_ratio={ratio:.4f}")
    else:
        ratio = replace_background(args.source, args.destination, args.analysis_width)
        print(f"background_ratio={ratio:.4f}")


if __name__ == "__main__":
    main()

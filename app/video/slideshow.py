import asyncio
import contextlib
import json
import logging
import os
import subprocess
from pathlib import Path

from PIL import Image

from config.config import config

logger = logging.getLogger(__name__)

SLIDESHOW_TMP_DIR = Path(config.app.TEMP_DIR) / "slideshow"
TARGET_W, TARGET_H = 1080, 1920


def _pad_image(img: Image.Image) -> Image.Image:
    img.thumbnail((TARGET_W, TARGET_H), Image.LANCZOS)
    canvas = Image.new("RGB", (TARGET_W, TARGET_H), (0, 0, 0))
    x = (TARGET_W - img.width) // 2
    y = (TARGET_H - img.height) // 2
    canvas.paste(img, (x, y))
    return canvas


def _probe_duration(path: Path) -> float | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        logger.exception("Cannot probe %s", path)
        return None


def _render_slideshow_sync(video_id: str, download_dir: str) -> str | None:
    tmp = SLIDESHOW_TMP_DIR / video_id
    tmp.mkdir(parents=True, exist_ok=True)

    image_files = sorted(f for f in os.listdir(tmp) if f.endswith(".jpg"))
    audio_path = tmp / "audio.mp3"

    if not image_files:
        logger.error("No images found for slideshow %s", video_id)
        return None

    if not audio_path.exists():
        logger.error("No audio found for slideshow %s", video_id)
        return None

    audio_duration = _probe_duration(audio_path)
    if audio_duration is None:
        logger.error("Cannot probe audio for slideshow %s", video_id)
        return None

    padded_dir = tmp / "padded"
    padded_dir.mkdir(exist_ok=True)

    for img_file in image_files:
        img = Image.open(tmp / img_file).convert("RGB")
        padded = _pad_image(img)
        padded.save(padded_dir / img_file)

    padded_images = sorted(f for f in os.listdir(padded_dir) if f.endswith(".jpg"))
    image_count = len(padded_images)
    slide_duration = max(2.0, min(3.0, audio_duration / image_count))

    out_path = Path(download_dir) / f"{video_id}.mp4"
    concat_file = padded_dir / "concat.txt"

    with open(concat_file, "w") as f:
        for img_file in padded_images:
            f.write(f"file '{(padded_dir / img_file).resolve()}'\n")
            f.write(f"duration {slide_duration}\n")
        f.write(f"file '{(padded_dir / padded_images[-1]).resolve()}'\n")

    logger.info("Rendering slideshow %s: %d images, %.1fs total", video_id, image_count, audio_duration)

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(audio_path),
        "-vf",
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        logger.error("ffmpeg slideshow failed: %s", result.stderr[-500:])
        if out_path.exists():
            os.remove(out_path)
        return None

    logger.info("Slideshow saved: %s", out_path)
    return str(out_path)


async def render_slideshow(video_id: str, download_dir: str) -> str | None:
    return await asyncio.to_thread(_render_slideshow_sync, video_id, download_dir)


def cleanup_slideshow_tmp(video_id: str | None = None) -> None:
    if video_id:
        tmp = SLIDESHOW_TMP_DIR / video_id
        if tmp.exists():
            _remove_dir(tmp)
    else:
        base = SLIDESHOW_TMP_DIR
        if base.exists():
            for sub in base.iterdir():
                if sub.is_dir():
                    _remove_dir(sub)
                else:
                    with contextlib.suppress(OSError):
                        os.remove(sub)


def _remove_dir(path: Path) -> None:
    for f in path.iterdir():
        if f.is_dir():
            _remove_dir(f)
        else:
            with contextlib.suppress(OSError):
                os.remove(f)
    with contextlib.suppress(OSError):
        path.rmdir()

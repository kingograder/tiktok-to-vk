import asyncio
import json
import logging
import os
import subprocess

from config.config import config

logger = logging.getLogger(__name__)


def _read_dimensions(video_path: str) -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", video_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning("ffprobe failed for %s", video_path)
            return None
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                return stream["width"], stream["height"]
        logger.warning("No video stream in %s", video_path)
        return None
    except Exception:
        logger.warning("Could not read dimensions for %s", video_path)
        return None


def _convert_video(video_path: str, out_path: str) -> None:
    w, h = config.app.TARGET_WIDTH, config.app.TARGET_HEIGHT
    if config.app.ROTATE_VIDEO:
        vf = "transpose=1"
    else:
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        )

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")


def _ensure_vertical_sync(video_path: str) -> str:
    dims = _read_dimensions(video_path)
    if dims is None:
        return video_path

    w, h = dims
    if h >= w:
        return video_path

    out = os.path.splitext(video_path)[0] + "_vertical.mp4"
    try:
        _convert_video(video_path, out)
    except Exception:
        logger.warning("Failed to convert %s, keeping original", video_path, exc_info=True)
        if os.path.exists(out):
            os.remove(out)
        return video_path
    if os.path.exists(video_path):
        os.remove(video_path)
    logger.info("Converted %s -> vertical (%s)", os.path.basename(video_path),
                 "rotate" if config.app.ROTATE_VIDEO else "pad")
    return out


async def ensure_vertical(video_path: str) -> str:
    return await asyncio.to_thread(_ensure_vertical_sync, video_path)

import asyncio
import logging
import os
import tempfile
from pathlib import Path

import av
from PIL import Image

from config.config import config

logger = logging.getLogger(__name__)

SLIDESHOW_TMP_DIR = Path(tempfile.gettempdir()) / "gallery_dl"


def _pad_image(img: Image.Image) -> Image.Image:
    target_w = config.app.TARGET_WIDTH
    target_h = config.app.TARGET_HEIGHT
    img.thumbnail((target_w, target_h), Image.LANCZOS)
    canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
    x = (target_w - img.width) // 2
    y = (target_h - img.height) // 2
    canvas.paste(img, (x, y))
    return canvas


def _probe_duration(path: Path) -> float | None:
    try:
        container = av.open(str(path))
        duration = float(container.duration / av.time_base)
        container.close()
        return duration
    except Exception:
        logger.exception("Cannot probe %s", path)
        return None


def _render_slideshow_sync(video_id: str, download_dir: str) -> str | None:
    tmp = SLIDESHOW_TMP_DIR
    tmp.mkdir(parents=True, exist_ok=True)

    image_files = sorted(f for f in os.listdir(tmp) if f.lower().endswith((".jpg", ".jpeg", ".png")))
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

    image_count = len(image_files)
    min_dur = config.slideshow.MIN_SLIDE_DURATION
    max_dur = config.slideshow.MAX_SLIDE_DURATION
    fps = config.slideshow.FPS
    target_w = config.app.TARGET_WIDTH
    target_h = config.app.TARGET_HEIGHT

    slide_duration = max(min_dur, min(max_dur, audio_duration / image_count))
    total_duration = max(slide_duration * image_count, audio_duration)
    frames_per_slide = int(slide_duration * fps)

    out_path = Path(download_dir) / f"{video_id}.mp4"

    logger.info("Rendering slideshow %s: %d images, %.1fs total", video_id, image_count, total_duration)

    try:
        out = av.open(str(out_path), mode="w")

        vstream = out.add_stream("h264", rate=fps)
        vstream.width = target_w
        vstream.height = target_h
        vstream.pix_fmt = "yuv420p"

        aout = av.open(str(audio_path))
        astream_in = next(s for s in aout.streams if s.type == "audio")
        astream_out = out.add_stream("aac", rate=astream_in.codec_context.rate)
        astream_out.layout = astream_in.layout

        pts = 0
        for img_file in image_files:
            img = Image.open(tmp / img_file).convert("RGB")
            padded = _pad_image(img)
            frame = av.VideoFrame.from_image(padded)

            for _ in range(frames_per_slide):
                frame.pts = pts
                pts += 1
                for packet in vstream.encode(frame):
                    out.mux(packet)

        total_frames_needed = int(total_duration * fps)
        while pts < total_frames_needed:
            frame.pts = pts
            pts += 1
            for packet in vstream.encode(frame):
                out.mux(packet)

        for packet in vstream.encode():
            out.mux(packet)

        for frame in aout.decode(astream_in):
            for packet in astream_out.encode(frame):
                out.mux(packet)
        for packet in astream_out.encode():
            out.mux(packet)

        out.close()
        aout.close()

        logger.info("Slideshow saved: %s", out_path)
        return str(out_path)

    except Exception:
        logger.exception("Failed to render slideshow %s", video_id)
        if out_path.exists():
            os.remove(out_path)
        return None


async def render_slideshow(video_id: str, download_dir: str) -> str | None:
    return await asyncio.to_thread(_render_slideshow_sync, video_id, download_dir)


def cleanup_slideshow_tmp() -> None:
    tmp = SLIDESHOW_TMP_DIR
    if not tmp.exists():
        return
    for f in tmp.iterdir():
        try:
            os.remove(f)
        except Exception:
            pass

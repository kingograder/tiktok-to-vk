import asyncio
import logging
import os

import av
from av.filter import Graph

from config.config import config

logger = logging.getLogger(__name__)

TARGET_W = 1080
TARGET_H = 1920


def _read_dimensions(video_path: str) -> tuple[int, int] | None:
    try:
        with av.open(video_path) as container:
            stream = next(s for s in container.streams if s.type == "video")
            return stream.codec_context.width, stream.codec_context.height
    except Exception:
        logger.warning("Could not read video info for %s", video_path)
        return None


def _encode_video_filter(video_path: str, out_path: str) -> None:
    in_container = av.open(video_path)
    out_container = av.open(out_path, mode="w")

    try:
        in_vstream = next(s for s in in_container.streams if s.type == "video")
        in_astream = next((s for s in in_container.streams if s.type == "audio"), None)

        out_vstream = out_container.add_stream("h264", rate=in_vstream.average_rate)
        out_vstream.time_base = in_vstream.time_base
        out_vstream.pix_fmt = "yuv420p"

        if config.app.ROTATE_VIDEO:
            w_src, h_src = in_vstream.codec_context.width, in_vstream.codec_context.height
            out_vstream.width = h_src
            out_vstream.height = w_src
        else:
            out_vstream.width = TARGET_W
            out_vstream.height = TARGET_H

        out_astream = None
        if in_astream:
            out_astream = out_container.add_stream("aac", rate=in_astream.codec_context.rate)
            out_astream.layout = in_astream.layout

        graph = Graph()
        src = graph.add_buffer(template=in_vstream)

        if config.app.ROTATE_VIDEO:
            transpose = graph.add("transpose", dir="1")
            src.link_to(transpose)
            last = transpose
        else:
            scale = graph.add("scale", w=str(TARGET_W), h=str(TARGET_H),
                              force_original_aspect_ratio="decrease")
            pad = graph.add("pad", w=str(TARGET_W), h=str(TARGET_H),
                            x="(ow-iw)/2", y="(oh-ih)/2", color="black")
            src.link_to(scale)
            scale.link_to(pad)
            last = pad

        sink = graph.add("buffersink")
        last.link_to(sink)
        graph.configure()

        for frame in in_container.decode(in_vstream):
            graph.push(frame)
            while True:
                try:
                    out_frame = graph.pull()
                except av.error.BlockingIOError:
                    break
                except (EOFError, av.error.EOFError):
                    break
                else:
                    for packet in out_vstream.encode(out_frame):
                        out_container.mux(packet)

        for packet in out_vstream.encode():
            out_container.mux(packet)

        if in_astream and out_astream:
            for frame in in_container.decode(in_astream):
                for packet in out_astream.encode(frame):
                    out_container.mux(packet)
            for packet in out_astream.encode():
                out_container.mux(packet)
    finally:
        out_container.close()
        in_container.close()


def _ensure_vertical_sync(video_path: str) -> str:
    dims = _read_dimensions(video_path)
    if dims is None:
        return video_path

    w, h = dims
    if h >= w:
        return video_path

    out = video_path.rsplit(".",  1)[0] + "_vertical.mp4"
    try:
        _encode_video_filter(video_path, out)
        os.remove(video_path)
        logger.info("Converted %s -> vertical (%s)",
                     os.path.basename(video_path),
                     "rotate" if config.app.ROTATE_VIDEO else "pad")
        return out
    except Exception:
        logger.warning("Failed to convert %s, keeping original", video_path, exc_info=True)
        if os.path.exists(out):
            os.remove(out)
        return video_path


async def ensure_vertical(video_path: str) -> str:
    return await asyncio.to_thread(_ensure_vertical_sync, video_path)

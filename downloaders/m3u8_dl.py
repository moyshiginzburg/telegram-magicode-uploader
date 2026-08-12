"""
HLS / m3u8 stream remuxing downloader module (ffmpeg wrapper).

Purpose:
    Downloads and remuxes live or VOD m3u8/HLS playlists directly to MP4 container
    without re-encoding, preserving exact original quality and maximum download speed.

Method of operation:
    1. Spawns an 'ffmpeg' subprocess with '-c copy -bsf:a aac_adtstoasc'.
    2. Directs the output to a unique temporary MP4 file in temp_cache.
    3. Handles subprocess cancellation gracefully by terminating the process.
    4. Returns the completed MP4 file path upon exit code 0.
"""

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional, Tuple

from utils import get_temp_path, sanitize_filename

logger = logging.getLogger(__name__)


async def download_m3u8_stream(
    url: str,
    custom_title: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> Tuple[Path, str, int]:
    """Remuxes an m3u8 playlist into an MP4 file using ffmpeg.
    
    Returns:
        Tuple of (temp_file_path, filename, total_size)
    """
    temp_path = get_temp_path(prefix="m3u8", suffix=".mp4")
    
    if custom_title:
        filename = sanitize_filename(f"{custom_title}.mp4")
    else:
        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        filename = f"stream_{timestamp_str}.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-headers", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n",
        "-i", url,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart",
        str(temp_path),
    ]

    logger.info("Spawning ffmpeg remux for m3u8: %s -> %s", url, temp_path)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        while proc.returncode is None:
            if is_cancelled and is_cancelled():
                proc.terminate()
                await proc.wait()
                raise asyncio.CancelledError("m3u8 download cancelled")
                
            # Track file size growth on disk
            if on_progress and temp_path.exists():
                curr_size = temp_path.stat().st_size
                await on_progress(curr_size, curr_size)
                
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except Exception:
                proc.kill()
        raise

    if proc.returncode != 0:
        _, stderr_bytes = await proc.communicate()
        err_msg = stderr_bytes.decode(errors="replace").strip() if stderr_bytes else "ffmpeg failed"
        raise RuntimeError(f"ffmpeg error (code {proc.returncode}): {err_msg[:200]}")

    total_size = temp_path.stat().st_size if temp_path.exists() else 0
    logger.info("ffmpeg remux completed: %s (%d bytes)", filename, total_size)
    return temp_path, filename, total_size

"""
Direct HTTP/HTTPS URL streaming downloader module.

Purpose:
    Downloads files from direct web URLs using async aiohttp streaming,
    supporting live byte progress tracking, auto filename extraction, and cancellation.

Method of operation:
    1. Sends an HTTP GET request to the URL with redirect handling.
    2. Determines filename from Content-Disposition header, Content-Type, or URL path.
    3. Streams response chunks (1MB) directly to a temporary file on disk.
    4. Invokes progress callback on each received chunk.
    5. Returns the temporary file path and extracted filename.
"""

import asyncio
from email.message import EmailMessage
import logging
import os
from pathlib import Path
from typing import Callable, Optional, Tuple
from urllib.parse import unquote, urlparse

import aiofiles
import aiohttp

from utils import get_temp_path, sanitize_filename

logger = logging.getLogger(__name__)


def extract_filename_from_headers(url: str, headers: dict) -> str:
    """Extracts a filename from Content-Disposition header or fallback to URL path."""
    cd = headers.get("Content-Disposition", "")
    if cd:
        msg = EmailMessage()
        msg["content-disposition"] = cd
        filename = msg.get_filename()
        if filename:
            return unquote(filename)

    # Fallback to URL path
    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name
    if not name or name == "/":
        name = "downloaded_file"
    return name


async def download_direct_url(
    url: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
    on_filename: Optional[Callable[[str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> Tuple[Path, str, int]:
    """Streams a direct URL to a temporary file.
    
    Returns:
        Tuple of (temp_file_path, filename, total_size)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    timeout = aiohttp.ClientTimeout(total=3600, sock_connect=30, sock_read=120)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        for attempt in range(3):
            try:
                resp = await session.get(url, allow_redirects=True)
                if resp.status in (502, 503, 504):
                    logger.warning("Got HTTP %d from %s, retrying (%d/3)...", resp.status, url, attempt + 1)
                    resp.close()
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                if resp.status != 200:
                    resp.close()
                    raise RuntimeError(f"Direct download failed with HTTP status {resp.status}")
                break
            except aiohttp.ClientError as e:
                if attempt == 2:
                    raise RuntimeError(f"Network error: {e}")
                await asyncio.sleep(2 * (attempt + 1))
                
        async with resp:
                
            raw_filename = extract_filename_from_headers(str(resp.url), resp.headers)
            filename = sanitize_filename(raw_filename)
            total_size = int(resp.headers.get("Content-Length", 0))
            
            if on_filename:
                try:
                    if asyncio.iscoroutinefunction(on_filename):
                        await on_filename(filename)
                    else:
                        on_filename(filename)
                except Exception:
                    pass
            
            ext = Path(filename).suffix or ".tmp"
            temp_path = get_temp_path(prefix="direct", suffix=ext)
            
            logger.info("Streaming direct URL '%s' -> %s (%d bytes)", url, filename, total_size)
            
            downloaded = 0
            async with aiofiles.open(temp_path, "wb") as fh:
                async for chunk in resp.content.iter_chunked(1024 * 1024):  # 1MB chunks
                    if is_cancelled and is_cancelled():
                        raise asyncio.CancelledError("Download cancelled")
                        
                    await fh.write(chunk)
                    downloaded += len(chunk)
                    
                    if on_progress:
                        try:
                            if asyncio.iscoroutinefunction(on_progress):
                                await on_progress(downloaded, total_size or downloaded)
                            else:
                                on_progress(downloaded, total_size or downloaded)
                        except Exception:
                            pass
                            
            final_size = temp_path.stat().st_size if temp_path.exists() else downloaded
            return temp_path, filename, final_size

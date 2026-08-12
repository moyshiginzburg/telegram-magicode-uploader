"""
Google Drive asynchronous file downloader module.

Purpose:
    Extracts Google Drive file IDs from various link formats and downloads public files
    using chunked streaming, handling virus scan confirmation bypass for large files (>100MB),
    automatic filename detection from headers, and live progress reporting.

Method of operation:
    1. 'extract_gdrive_id': Extracts the alphanumeric file ID from Google Drive URLs.
    2. Sends initial GET request to Google Drive download endpoint with cookie persistence.
    3. Detects if a virus warning confirmation page is returned for large files, parses
       the confirmation token/URL, and re-submits with the session cookies.
    4. Extracts the original filename from Content-Disposition headers.
    5. Streams the response in chunks to a temporary file in 'temp_cache/'.
    6. Invokes the progress callback on every chunk received.
    7. Returns the path to the downloaded file, sanitized filename, and total file size.
"""

import asyncio
from email.message import EmailMessage
import logging
import re
from pathlib import Path
from typing import Callable, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlencode, urlparse

import aiofiles
import aiohttp

from utils import get_temp_path, sanitize_filename

logger = logging.getLogger(__name__)

_GDRIVE_ID_PATTERN = re.compile(r"(?:/file/d/|id=|/d/|folders/)([a-zA-Z0-9_-]{15,})")
_CONFIRM_TOKEN_PATTERN = re.compile(r"confirm=([a-zA-Z0-9_-]+)")
_UUID_TOKEN_PATTERN = re.compile(r"name=[\"']uuid[\"']\s+value=[\"']([^\"']+)[\"']")


def extract_gdrive_id(url: str) -> Optional[str]:
    """Extracts the Google Drive file ID from a URL string."""
    if not url:
        return None
    match = _GDRIVE_ID_PATTERN.search(url)
    if match:
        return match.group(1)
    
    # Fallback to query param
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if "id" in params and params["id"]:
            return params["id"][0]
    except Exception:
        pass
        
    return None


def _extract_filename(headers: dict, default: str = "gdrive_file") -> str:
    """Extracts filename from Content-Disposition header."""
    cd = headers.get("Content-Disposition", "")
    if cd:
        msg = EmailMessage()
        msg["content-disposition"] = cd
        filename = msg.get_filename()
        if filename:
            return sanitize_filename(unquote(filename))
    return default


async def download_gdrive_file(
    url: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
    on_filename: Optional[Callable[[str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> Tuple[Path, str, int]:
    """Downloads a public file from Google Drive.

    Args:
        url: Direct or shareable Google Drive link.
        on_progress: Optional async/sync callback with (downloaded_bytes, total_bytes).
        is_cancelled: Optional callable returning True if the task was aborted.

    Returns:
        Tuple of (temp_file_path, filename, total_size)
    """
    file_id = extract_gdrive_id(url)
    if not file_id:
        raise ValueError("Could not extract a valid Google Drive file ID from the provided URL.")

    base_dl_url = "https://drive.google.com/uc"
    params = {"id": file_id, "export": "download"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    timeout = aiohttp.ClientTimeout(total=7200, sock_connect=30, sock_read=120)
    jar = aiohttp.CookieJar(unsafe=True)

    async with aiohttp.ClientSession(timeout=timeout, headers=headers, cookie_jar=jar) as session:
        # Step 1: Initial request
        async with session.get(base_dl_url, params=params, allow_redirects=True) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Google Drive returned HTTP error {resp.status}")

            content_type = resp.headers.get("Content-Type", "").lower()
            
            # Step 2: Check if Google returned a virus warning / large file confirmation page
            if "text/html" in content_type:
                html_body = await resp.text()
                
                # Check for permission errors / file not found
                if "Google Drive – Access Denied" in html_body or "You need access" in html_body:
                    raise PermissionError("The Google Drive file is private. Please ensure 'Anyone with the link can view' is enabled.")
                if "File not found" in html_body or "The file you are trying to download does not exist" in html_body:
                    raise FileNotFoundError("The Google Drive file was not found or has been deleted.")

                # Look for the new Google Drive confirmation form
                form_action_match = re.search(r'<form[^>]+id=[\'"]download-form[\'"][^>]*action=[\'"]([^\'"]+)[\'"]', html_body, re.IGNORECASE)
                if form_action_match:
                    new_base_url = form_action_match.group(1)
                    if new_base_url.startswith('/'):
                        new_base_url = f"https://drive.google.com{new_base_url}"
                    base_dl_url = new_base_url
                    
                    # Extract all hidden inputs and override params
                    inputs = re.findall(r'<input[^>]+type=[\'"]hidden[\'"][^>]*name=[\'"]([^\'"]+)[\'"][^>]*value=[\'"]([^\'"]*)[\'"]', html_body, re.IGNORECASE)
                    if inputs:
                        params.clear()
                        params.update(dict(inputs))
                else:
                    # Fallback for old warning page formats
                    confirm_match = _CONFIRM_TOKEN_PATTERN.search(html_body)
                    uuid_match = _UUID_TOKEN_PATTERN.search(html_body)
                    
                    if confirm_match:
                        params["confirm"] = confirm_match.group(1)
                    elif uuid_match:
                        params["uuid"] = uuid_match.group(1)
                    else:
                        for cookie in jar:
                            if cookie.key.startswith("download_warning"):
                                params["confirm"] = cookie.value
                                break
                        else:
                            params["confirm"] = "t"

                logger.info("Handling Google Drive large-file confirmation for %s with params: %s", base_dl_url, params)

                # Step 3: Stream download with confirmation
                async with session.get(base_dl_url, params=params, allow_redirects=True) as dl_resp:
                    if dl_resp.status != 200:
                        raise RuntimeError(f"Google Drive confirmed download failed with HTTP {dl_resp.status}")
                    return await _stream_to_disk(dl_resp, on_progress, on_filename, is_cancelled)
            else:
                # Direct file stream without confirmation page
                return await _stream_to_disk(resp, on_progress, on_filename, is_cancelled)


async def _stream_to_disk(
    resp: aiohttp.ClientResponse,
    on_progress: Optional[Callable[[int, int], None]] = None,
    on_filename: Optional[Callable[[str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> Tuple[Path, str, int]:
    """Streams an HTTP response content to a temporary file on disk."""
    raw_filename = _extract_filename(resp.headers, default="gdrive_file")
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
    temp_path = get_temp_path(prefix="gdrive", suffix=ext)

    logger.info("Streaming Google Drive file '%s' -> %s (%d bytes)", filename, temp_path, total_size)

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
    logger.info("Google Drive download finished: %s (%d bytes)", filename, final_size)
    return temp_path, filename, final_size

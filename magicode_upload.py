"""
Magicode (send.magicode.me) upload engine.

Purpose:
    Handles chunked, asynchronous file uploads to send.magicode.me, supporting
    live progress tracking, direct download link generation, and cancellation.

Method of operation:
    1. 'prep_upload': Sends a POST to '/send-file/prep-upload' with file size and
       sanitized filename. Retrieves 'keyUpload' (upload session key) and
       'keyFile' (download file key).
    2. Builds the instant download link ('/send-file/file/{keyFile}/download')
       and view link ('/send-file/file/{keyFile}/view').
    3. 'upload_file': Reads the file in chunks (2MB strictly recommended by API doc) and
       sends multipart/form-data POST requests to '/send-file/data-upload',
       using browser-identical request headers and WebKit boundary formats.
    4. Calls 'on_progress' callback with current byte offset and total size.
    5. Confirms completion when the server returns '{"ok": true, "end": true}'.
"""

import asyncio
import json
import logging
import os
import random
import string
from pathlib import Path
from typing import AsyncGenerator, Callable, Optional, Tuple

import aiohttp

from config import (
    CHUNK_SIZE_BYTES,
    MAGICODE_DOWNLOAD_URL_TEMPLATE,
    MAGICODE_PREP_URL,
    MAGICODE_UPLOAD_URL,
    MAGICODE_VIEW_URL_TEMPLATE,
)

logger = logging.getLogger(__name__)

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Origin": "https://send.magicode.me",
    "Referer": "https://send.magicode.me/send-file/upload",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
}

def webkit_boundary() -> str:
    """Generate a random multipart boundary in Chrome's format."""
    chars = string.ascii_letters + string.digits
    return "----WebKitFormBoundary" + "".join(random.choices(chars, k=16))


class MagicodeUploader:
    """Async upload client for send.magicode.me."""

    def __init__(self, chunk_size: int = CHUNK_SIZE_BYTES):
        self.chunk_size = chunk_size

    async def prep_upload(
        self, session: aiohttp.ClientSession, filename: str, total_size: int
    ) -> Tuple[str, str, str, str]:
        """Prepares an upload slot on Magicode.
        
        Returns:
            Tuple of (key_upload, key_file, download_url, view_url)
        """
        payload = {"size": total_size, "filename": filename}
        logger.info("Requesting Magicode upload slot for '%s' (%d bytes)", filename, total_size)
        
        prep_headers = {
            **COMMON_HEADERS,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }
        
        async with session.post(
            MAGICODE_PREP_URL,
            data=json.dumps(payload),
            headers=prep_headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Magicode prep-upload failed (HTTP {resp.status}): {text}")
            
            data = await resp.json()
            key_upload = data.get("keyUpload")
            key_file = data.get("keyFile")
            
            if not key_upload or not key_file:
                raise RuntimeError(f"Invalid prep-upload response from Magicode: {data}")
                
            download_url = MAGICODE_DOWNLOAD_URL_TEMPLATE.format(key_file=key_file)
            view_url = MAGICODE_VIEW_URL_TEMPLATE.format(key_file=key_file)
            
            logger.info("Magicode slot allocated: keyFile=%s", key_file)
            return key_upload, key_file, download_url, view_url

    async def upload_file(
        self,
        file_path: str | Path,
        filename: str,
        on_init: Optional[Callable[[str, str], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> Tuple[str, str]:
        """Uploads a local file to Magicode in chunks with progress tracking.
        
        Args:
            file_path: Path to the local file to upload.
            filename: Target filename.
            on_init: Optional callback invoked immediately with (download_url, view_url).
            on_progress: Optional callback invoked with (uploaded_bytes, total_bytes).
            is_cancelled: Optional callable returning True if the task should abort.

        Returns:
            Tuple of (download_url, view_url)
        """
        path = Path(file_path)
        total_size = path.stat().st_size
        
        timeout = aiohttp.ClientTimeout(total=180, sock_connect=20, sock_read=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            key_upload, key_file, download_url, view_url = await self.prep_upload(
                session, filename, total_size
            )
            
            if on_init:
                try:
                    if asyncio.iscoroutinefunction(on_init):
                        await on_init(download_url, view_url)
                    else:
                        on_init(download_url, view_url)
                except Exception as exc:
                    logger.warning("Error in on_init callback: %s", exc)

            chunk_headers = {**COMMON_HEADERS, "Accept": "*/*"}
            position = 0
            
            with open(path, "rb") as fh:
                while position < total_size or (total_size == 0 and position == 0):
                    if is_cancelled and is_cancelled():
                        raise asyncio.CancelledError("Upload cancelled by user")
                        
                    chunk_data = fh.read(self.chunk_size)
                    chunk_len = len(chunk_data)
                    
                    upload_url = (
                        f"{MAGICODE_UPLOAD_URL}?position={position}&length={chunk_len}"
                        f"&keyUpload={key_upload}&keyFile={key_file}&"
                    )
                    
                    # Upload chunk with retry on transient network errors
                    for attempt in range(3):
                        try:
                            boundary = webkit_boundary()
                            writer = aiohttp.MultipartWriter("form-data", boundary=boundary)
                            part = writer.append(chunk_data, {"Content-Type": "application/octet-stream"})
                            part.set_content_disposition("form-data", name="file", filename="blob")
                            
                            async with session.post(
                                upload_url, data=writer, headers=chunk_headers
                            ) as chunk_resp:
                                if chunk_resp.status != 200:
                                    text = await chunk_resp.text()
                                    raise RuntimeError(
                                        f"Chunk upload failed (HTTP {chunk_resp.status}): {text}"
                                    )
                                res_json = await chunk_resp.json()
                                if res_json.get("ok") != 1 and res_json.get("ok") is not True:
                                    raise RuntimeError(f"Server rejected chunk: {res_json}")
                                break
                        except Exception as e:
                            if attempt == 2:
                                raise
                            logger.warning(
                                "Retrying chunk at pos %d after error: %s (attempt %d/3)",
                                position, e, attempt + 1
                            )
                            await asyncio.sleep(2)

                    position += chunk_len
                    if on_progress:
                        try:
                            if asyncio.iscoroutinefunction(on_progress):
                                await on_progress(position, total_size)
                            else:
                                on_progress(position, total_size)
                        except Exception as exc:
                            logger.warning("Error in on_progress callback: %s", exc)

                    if total_size == 0 or position >= total_size:
                        break

            logger.info("Uploaded successfully: %s -> %s", filename, download_url)
            return download_url, view_url

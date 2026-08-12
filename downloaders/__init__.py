"""
Downloaders package for Telegram Magicode Uploader.

Purpose:
    Exposes unified async downloader functions for direct HTTP/HTTPS URLs,
    public Google Drive files, and HLS/m3u8 live streams.

Method of operation:
    Re-exports 'download_direct_url', 'download_gdrive_file', and 'download_m3u8_stream'.
"""

from .direct_dl import download_direct_url
from .gdrive_dl import download_gdrive_file
from .m3u8_dl import download_m3u8_stream

__all__ = [
    "download_direct_url",
    "download_gdrive_file",
    "download_m3u8_stream",
]

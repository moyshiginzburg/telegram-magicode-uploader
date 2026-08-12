"""
URL classification and detection module.

Purpose:
    Scans text messages for URLs and identifies the source type (Google Drive,
    streaming m3u8 playlist, or direct HTTP/HTTPS file) to route to the appropriate downloader,
    while classifying unsupported services (such as social video platforms) as unsupported.

Method of operation:
    1. Uses regex pattern matching to extract HTTP/HTTPS URLs from message text.
    2. Detects Google Drive share URLs (drive.google.com / docs.google.com).
    3. Detects HLS/m3u8 live stream or playlist URLs.
    4. Rejects known video streaming / social media platforms to maintain compliance.
    5. Routes all other valid HTTP/HTTPS URLs as direct file downloads.
"""

import re
from urllib.parse import urlparse

_URL_REGEX = re.compile(
    r"https?://(?:[a-zA-Z0-9_-]+\.)+[a-zA-Z]{2,}(?::\d+)?(?:/[^\s]*)?",
    re.IGNORECASE,
)

_UNSUPPORTED_DOMAINS = {
    "youtube.com", "youtu.be", "m.youtube.com",
    "instagram.com", "instagr.am",
    "tiktok.com", "vm.tiktok.com",
    "twitter.com", "x.com",
    "facebook.com", "fb.watch", "fb.com",
    "vimeo.com", "dailymotion.com", "reddit.com",
}


def extract_urls(text: str) -> list[str]:
    """Extracts all valid HTTP/HTTPS URLs found in a string."""
    if not text:
        return []
    return _URL_REGEX.findall(text)


def detect_url_type(url: str) -> str:
    """Classifies a URL into 'gdrive', 'm3u8', 'direct', or 'unsupported'.

    Returns:
        'gdrive'      - For Google Drive file/view/download URLs.
        'm3u8'        - For HLS live streams/playlists (ffmpeg).
        'direct'      - For standard direct HTTP/HTTPS files (aiohttp).
        'unsupported' - For blocked or unparsable URLs.
    """
    if not url or not isinstance(url, str):
        return "unsupported"

    try:
        parsed = urlparse(url.strip())
        hostname = (parsed.hostname or "").lower()
        path = (parsed.path or "").lower()
    except Exception:
        return "unsupported"

    if not parsed.scheme or parsed.scheme not in ("http", "https") or not hostname:
        return "unsupported"

    # 1. Google Drive detection
    if hostname in ("drive.google.com", "docs.google.com"):
        return "gdrive"

    # 2. Block unsupported video/social platforms
    for domain in _UNSUPPORTED_DOMAINS:
        if hostname == domain or hostname.endswith("." + domain):
            return "unsupported"

    # 3. m3u8 playlists
    if path.endswith(".m3u8") or ".m3u8?" in url.lower():
        return "m3u8"

    # 4. Direct HTTP/HTTPS downloads
    return "direct"

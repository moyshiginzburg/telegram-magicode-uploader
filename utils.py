"""
Utilities and helper functions for Telegram Magicode Uploader.

Purpose:
    Provides formatting, filename sanitization, time calculation, and
    temporary file management functions used across downloaders and handlers.

Method of operation:
    1. 'sanitize_filename': Strips forbidden characters and truncates safely.
    2. 'format_size': Converts raw byte counts into human-readable units (B, KB, MB, GB).
    3. 'format_speed': Formats transfer speed in MB/s or KB/s.
    4. 'format_eta': Formats remaining seconds into MM:SS or HH:MM:SS format.
    5. 'safe_remove': Safely deletes temporary files with error suppression.
"""

import os
import re
import unicodedata
from pathlib import Path
from config import MAX_FILENAME_LENGTH, TEMP_DIR

_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')

def sanitize_filename(name: str, default: str = "file") -> str:
    """Sanitizes a string for use as a filesystem filename."""
    if not name:
        return default
    
    # Normalize unicode
    name = unicodedata.normalize("NFC", name)
    name = _INVALID_CHARS.sub("_", name).strip(". ")
    
    if not name:
        return default
        
    if len(name.encode("utf-8")) > MAX_FILENAME_LENGTH:
        ext = Path(name).suffix
        stem = Path(name).stem
        allowed_stem_len = MAX_FILENAME_LENGTH - len(ext.encode("utf-8")) - 5
        if allowed_stem_len > 0:
            stem = stem[:allowed_stem_len]
        name = f"{stem}{ext}"
        
    return name

def format_size(bytes_count: int | float) -> str:
    """Formats a byte count into a readable string (e.g. 45.2 MB)."""
    if bytes_count is None or bytes_count < 0:
        return "0 B"
    
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    val = float(bytes_count)
    while val >= 1024.0 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1
        
    if unit_idx == 0:
        return f"{int(val)} B"
    return f"{val:.1f} {units[unit_idx]}"

def format_speed(bytes_per_sec: float) -> str:
    """Formats transfer speed into MB/s or KB/s."""
    if bytes_per_sec <= 0:
        return "0 KB/s"
    mb = bytes_per_sec / (1024 * 1024)
    if mb >= 0.1:
        return f"{mb:.1f} MB/s"
    kb = bytes_per_sec / 1024
    return f"{kb:.0f} KB/s"

def format_eta(seconds: float | int) -> str:
    """Formats estimated remaining time into MM:SS or HH:MM:SS."""
    if seconds is None or seconds < 0 or seconds > 86400 * 7:
        return "--:--"
    sec = int(seconds)
    hrs = sec // 3600
    mins = (sec % 3600) // 60
    rem_sec = sec % 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{rem_sec:02d}"
    return f"{mins:02d}:{rem_sec:02d}"

def get_temp_path(prefix: str = "upload", suffix: str = ".tmp") -> Path:
    """Generates a unique path inside the ephemeral temp_cache directory."""
    import uuid
    filename = f"{prefix}_{uuid.uuid4().hex[:10]}{suffix}"
    return TEMP_DIR / filename

def safe_remove(path: str | Path | None) -> None:
    """Safely removes a file from disk without raising exceptions."""
    if not path:
        return
    try:
        p = Path(path)
        if p.is_file() or p.is_symlink():
            p.unlink(missing_ok=True)
        elif p.is_dir():
            import shutil
            shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass

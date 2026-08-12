"""
Configuration module for Telegram Magicode Uploader.

Purpose:
    Centralizes all application configuration, runtime settings, directory
    path management with cross-platform Pathlib, Magicode endpoint definitions,
    and Telegram Bot settings.

Method of operation:
    1. Determines the project root directory.
    2. Ensures persistent ('local_data') and ephemeral ('temp_cache') directories exist.
    3. Auto-creates inner '.gitignore' files inside storage directories for containment.
    4. Loads settings from environment variables or '.env' files.
    5. Exposes validated typed configuration constants to the rest of the application.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Define root paths
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "local_data"
TEMP_DIR = PROJECT_ROOT / "temp_cache"

# Ensure storage directories exist with self-containment gitignores
for directory in (DATA_DIR, TEMP_DIR):
    directory.mkdir(parents=True, exist_ok=True)
    gi_file = directory / ".gitignore"
    if not gi_file.exists():
        gi_file.write_text("*\n!.gitignore\n", encoding="utf-8")

# Load environment variables if available
_temp_env_file = TEMP_DIR / ".env"
_data_env_file = DATA_DIR / ".env"
if _temp_env_file.exists():
    load_dotenv(_temp_env_file)
elif _data_env_file.exists():
    load_dotenv(_data_env_file)
else:
    load_dotenv(PROJECT_ROOT / ".env")

# Telegram Bot settings
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Runtime settings
CHUNK_SIZE_MB: int = int(os.getenv("CHUNK_SIZE_MB", "2").strip() or "2")
CHUNK_SIZE_BYTES: int = CHUNK_SIZE_MB * 1024 * 1024
MAX_FILENAME_LENGTH: int = 200

# Magicode Endpoints
MAGICODE_BASE_URL: str = "https://send.magicode.me"
MAGICODE_PREP_URL: str = f"{MAGICODE_BASE_URL}/send-file/prep-upload"
MAGICODE_UPLOAD_URL: str = f"{MAGICODE_BASE_URL}/send-file/data-upload"
MAGICODE_DOWNLOAD_URL_TEMPLATE: str = f"{MAGICODE_BASE_URL}/send-file/file/{{key_file}}/download"
MAGICODE_VIEW_URL_TEMPLATE: str = f"{MAGICODE_BASE_URL}/send-file/file/{{key_file}}/view"

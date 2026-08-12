"""
CLI entrypoint and orchestration module for Telegram Magicode Uploader.

Purpose:
    Executes automated downloading (direct HTTP, Google Drive, or m3u8 stream)
    and chunked uploading to send.magicode.me, tracking progress via Telegram
    message edits.

Method of operation:
    1. Parses CLI arguments.
    2. Uses ProgressTracker to dynamically edit the Telegram status message.
    3. Downloads the file to 'temp_cache/' with live download progress.
    4. Uploads to send.magicode.me with live upload progress.
    5. Finalizes the message with the download link and inline buttons.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import aiohttp

from config import TELEGRAM_BOT_TOKEN, TEMP_DIR
from downloaders import download_direct_url, download_gdrive_file, download_m3u8_stream
from link_detector import detect_url_type
from magicode_upload import MagicodeUploader
from utils import format_size, safe_remove, sanitize_filename

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("uploader")


class ProgressTracker:
    def __init__(self, bot_token, chat_id, message_id):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.message_id = message_id
        self.last_edit_time = 0
        self.last_text = ""
        self.download_url = None
        self.filename = None

    async def update(self, text: str, force: bool = False, reply_markup: dict = None):
        if not self.bot_token or not self.chat_id or not self.message_id:
            return
            
        now = time.time()
        if not force and now - self.last_edit_time < 3.0:
            return
            
        if text == self.last_text and not force:
            return
            
        api_url = f"https://api.telegram.org/bot{self.bot_token}/editMessageText"
        payload = {
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
            
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(api_url, json=payload) as resp:
                    if resp.status == 200:
                        self.last_edit_time = time.time()
                        self.last_text = text
        except Exception:
            pass
            
    def format_progress_str(self, current, total):
        if total == 0 or current > total:
            total = current
        if total == 0:
            return f"{format_size(current)}"
        pct = (current / total) * 100
        return f"{pct:.1f}% ({format_size(current)} מתוך {format_size(total)})"

    async def set_filename(self, filename: str):
        self.filename = filename

    async def on_download_progress(self, current, total):
        prog = self.format_progress_str(current, total)
        name_str = f"📁 <b>שם הקובץ:</b> <code>{self.filename}</code>\n" if self.filename else ""
        text = f"{name_str}⏳ <b>מוריד לשרת ענן...</b>\nהתקדמות: {prog}"
        await self.update(text)

    async def on_upload_init(self, download_url, view_url):
        self.download_url = download_url
        print(f"::add-mask::{download_url}")
        print(f"::add-mask::{view_url}")
        text = (
            f"📁 <b>שם הקובץ:</b> <code>{self.filename}</code>\n"
            f"🔗 <b>קישור:</b> {self.download_url}\n"
            f"⏳ <b>מתחיל העלאה...</b>"
        )
        await self.update(text, force=True)

    async def on_upload_progress(self, current, total):
        prog = self.format_progress_str(current, total)
        text = (
            f"📁 <b>שם הקובץ:</b> <code>{self.filename}</code>\n"
            f"🔗 <b>קישור:</b> {self.download_url}\n"
            f"🚀 <b>התקדמות העלאה:</b> {prog}"
        )
        await self.update(text)
        
    async def finish(self):
        text = (
            f"📁 <b>שם הקובץ:</b> <code>{self.filename}</code>\n"
            f"🔗 <b>קישור:</b> {self.download_url}\n"
            f"✅ <b>העלאה הושלמה!</b>"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "⬇️ הורדה ישירה", "url": self.download_url}
                ]
            ]
        }
        await self.update(text, force=True, reply_markup=keyboard)


async def send_telegram_message(
    bot_token: str,
    chat_id: str | int,
    text: str,
    reply_to_message_id: Optional[str | int] = None,
) -> bool:
    """Fallback function for sending a new message if edit fails."""
    if not bot_token or not chat_id:
        return False
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if reply_to_message_id:
        try:
            payload["reply_to_message_id"] = int(reply_to_message_id)
        except Exception:
            pass
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(api_url, json=payload) as resp:
                return resp.status == 200
    except Exception:
        return False


def write_github_step_summary(url, filename, file_size, download_url, view_url):
    return  # STEALTH MODE: Disabled summary output


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Telegram Magicode CLI Uploader")
    parser.add_argument("--url", required=True, help="Download URL to fetch and upload")
    parser.add_argument("--chat-id", default=None, help="Telegram Chat ID to notify")
    parser.add_argument("--message-id", default=None, help="Telegram Message ID to reply to")
    parser.add_argument("--status-message-id", default=None, help="Telegram Message ID of the status to edit")
    parser.add_argument("--filename", default=None, help="Custom filename override")
    parser.add_argument("--bot-token", default=None, help="Telegram Bot Token override")
    args = parser.parse_args()

    url = args.url.strip()
    chat_id = args.chat_id
    message_id = args.message_id
    status_message_id = args.status_message_id
    custom_filename = args.filename.strip() if args.filename else None
    bot_token = args.bot_token or TELEGRAM_BOT_TOKEN

    logger.info("Starting processing for URL: %s", url)
    
    tracker = ProgressTracker(bot_token, chat_id, status_message_id)

    # 1. URL classification
    url_type = detect_url_type(url)
    logger.info("Detected URL type: %s", url_type)

    if url_type == "unsupported":
        logger.warning("URL is unsupported: %s", url)
        if bot_token and chat_id:
            await send_telegram_message(
                bot_token=bot_token,
                chat_id=chat_id,
                text="❌ <b>קישור זה אינו נתמך.</b>\nהבוט תומך בקישורים ישירים, Google Drive ושידורי m3u8 בלבד.",
                reply_to_message_id=message_id,
            )
        return 1

    temp_file: Optional[Path] = None
    try:
        # 2. Download phase
        logger.info("Initiating download for type: %s", url_type)
        if url_type == "gdrive":
            temp_file, filename, file_size = await download_gdrive_file(
                url, on_progress=tracker.on_download_progress, on_filename=tracker.set_filename
            )
        elif url_type == "m3u8":
            if custom_filename:
                await tracker.set_filename(f"{custom_filename}.mp4")
            temp_file, filename, file_size = await download_m3u8_stream(
                url, custom_title=custom_filename, on_progress=tracker.on_download_progress
            )
        else:  # direct
            temp_file, filename, file_size = await download_direct_url(
                url, on_progress=tracker.on_download_progress, on_filename=tracker.set_filename
            )

        # Apply custom filename if specified
        if custom_filename and url_type != "m3u8":
            ext = Path(filename).suffix
            if not custom_filename.endswith(ext) and ext:
                filename = sanitize_filename(f"{custom_filename}{ext}")
            else:
                filename = sanitize_filename(custom_filename)

        tracker.filename = filename

        # STEALTH MODE: Mask filename
        print(f"::add-mask::{filename}")
        logger.info("Downloaded file '%s' (%d bytes) at %s", filename, file_size, temp_file)

        # 3. Upload phase to Magicode
        logger.info("Starting chunked upload to send.magicode.me...")
        uploader = MagicodeUploader()
        download_url, view_url = await uploader.upload_file(
            temp_file, 
            filename,
            on_init=tracker.on_upload_init,
            on_progress=tracker.on_upload_progress
        )
        logger.info("Upload succeeded! Direct link: %s", download_url)

        # 4. Save result.json in temp_cache/
        result_payload = {
            "status": "success",
            "url": url,
            "filename": filename,
            "file_size": file_size,
            "formatted_size": format_size(file_size),
            "magicode_download_url": download_url,
            "magicode_view_url": view_url,
        }
        result_file = TEMP_DIR / "result.json"
        result_file.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        # 5. Notify user on Telegram (edit final message)
        if bot_token and chat_id and status_message_id:
            await tracker.finish()
        elif bot_token and chat_id:
            # Fallback if no status message ID was provided
            await send_telegram_message(
                bot_token, chat_id, 
                f"📁 <b>שם הקובץ:</b> <code>{filename}</code>\n🔗 <b>קישור:</b> {download_url}\n✅ <b>העלאה הושלמה!</b>",
                reply_to_message_id=message_id
            )

        logger.info("Upload workflow finished successfully.")
        return 0

    except Exception as exc:
        logger.exception("Processing failed: %s", exc)
        if bot_token and chat_id:
            err_msg = str(exc) or "שגיאה לא ידועה"
            err_text = f"❌ <b>ההעלאה נכשלה</b>\n\nפירוט השגיאה:\n<code>{err_msg[:500]}</code>"
            if status_message_id:
                await tracker.update(err_text, force=True)
            else:
                await send_telegram_message(bot_token, chat_id, err_text, reply_to_message_id=message_id)
        return 1

    finally:
        if temp_file:
            safe_remove(temp_file)


def main():
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()

"""
Magicode Web Uploader - Hugging Face Spaces Application.

Purpose:
    Provides a modern, high-performance web interface on Hugging Face Spaces
    that accepts direct download URLs, social media video links, or m3u8 streams,
    downloads them server-side, and uploads them to send.magicode.me with instant
    direct download link generation and real-time progress tracking.

Method of operation:
    1. Receives URL input and optional custom filename from the Gradio web UI.
    2. Identifies link type via 'link_detector' (direct HTTP, social media video, or m3u8 stream).
    3. Streams the download to an isolated ephemeral folder in 'temp_cache/'.
    4. Immediately allocates an upload slot on Magicode to retrieve the final download link.
    5. Uploads the file in chunks (configurable, default 5MB) to 'send.magicode.me'.
    6. Yields real-time progress updates (percentage, speed, transfer size, ETA) to the UI.
    7. Automatically cleans up temporary files from disk upon completion or error.
"""

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import AsyncGenerator

import gradio as gr

from config import CHUNK_SIZE_BYTES, SERVER_NAME, SERVER_PORT
from downloaders import download_direct_url, download_m3u8_stream, download_social_video
from link_detector import detect_url_type, extract_urls
from magicode_upload import MagicodeUploader
from utils import format_eta, format_size, format_speed, safe_remove, sanitize_filename

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("MagicodeWebUploader")

# Initialize Magicode uploader instance
uploader = MagicodeUploader(chunk_size=CHUNK_SIZE_BYTES)

# Custom RTL styling for Hebrew interface
CUSTOM_CSS = """
/* RTL and modern typography styling */
body, .gradio-container {
    direction: rtl !important;
    text-align: right !important;
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif !important;
}

.main-header {
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    color: #ffffff;
    padding: 24px;
    border-radius: 16px;
    margin-bottom: 20px;
    text-align: center;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
}

.main-header h1 {
    font-size: 28px !important;
    font-weight: 700 !important;
    margin-bottom: 8px !important;
    color: #38bdf8 !important;
}

.main-header p {
    font-size: 15px !important;
    color: #94a3b8 !important;
}

.result-card {
    background: #f8fafc;
    border: 2px solid #38bdf8;
    border-radius: 14px;
    padding: 20px;
    margin-top: 16px;
    box-shadow: 0 4px 12px rgba(56, 189, 248, 0.15);
}

.dark .result-card {
    background: #1e293b;
    border-color: #38bdf8;
}

.badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 9999px;
    font-size: 13px;
    font-weight: 600;
    margin-left: 8px;
}

.badge-success {
    background-color: #dcfce7;
    color: #15803d;
}

.badge-info {
    background-color: #e0f2fe;
    color: #0369a1;
}
"""


async def process_transfer(
    url_input: str,
    custom_filename: str,
    progress=gr.Progress(track_tqdm=False)
) -> AsyncGenerator[tuple[str, str, str, str], None]:
    """Processes URL download and Magicode upload pipeline with real-time UI yielding.

    Yields tuples of:
        (status_html, download_url_output, view_url_output, details_markdown)
    """
    url_input = (url_input or "").strip()
    if not url_input:
        yield (
            "<div style='color: #ef4444; font-weight: bold;'>⚠️ אנא הזן קישור תקין להורדה.</div>",
            "",
            "",
            ""
        )
        return

    # Extract clean URL
    found_urls = extract_urls(url_input)
    target_url = found_urls[0] if found_urls else url_input

    link_type = detect_url_type(target_url)
    type_names = {
        "direct": "קישור ישיר (HTTP/HTTPS)",
        "social": "רשת חברתית / וידאו (yt-dlp)",
        "m3u8": "שידור וידאו HLS (m3u8)"
    }
    type_display = type_names.get(link_type, "קישור ישיר")

    logger.info("New transfer request: %s (Type: %s)", target_url, link_type)
    progress(0.05, desc="מזהה את מקור הקישור...")

    yield (
        f"<div style='color: #0284c7;'>🔍 זוהה: <b>{type_display}</b> | מתחיל בהורדה לשרת...</div>",
        "",
        "",
        f"**סוג קישור:** {type_display}\n\n**כתובת מקור:** `{target_url}`"
    )

    temp_file_path: Path | None = None
    try:
        # Phase 1: Download from source
        progress(0.10, desc="מוריד לשרת...")
        start_dl_time = time.time()
        last_dl_yield = 0.0

        def dl_progress_cb(downloaded: int, total: int):
            nonlocal last_dl_yield
            now = time.time()
            if now - last_dl_yield < 0.5:
                return
            last_dl_yield = now
            pct = (downloaded / max(total, 1)) * 100 if total > 0 else 0
            elapsed = max(now - start_dl_time, 0.001)
            speed = downloaded / elapsed
            progress(
                min(0.10 + (pct / 100.0) * 0.40, 0.50),
                desc=f"מוריד לשרת... {pct:.1f}% ({format_size(downloaded)} / {format_size(total)})"
            )

        if link_type == "social":
            temp_file_path, original_filename, file_size = await download_social_video(
                target_url, on_progress=dl_progress_cb
            )
        elif link_type == "m3u8":
            temp_file_path, original_filename, file_size = await download_m3u8_stream(
                target_url, on_progress=dl_progress_cb
            )
        else:
            temp_file_path, original_filename, file_size = await download_direct_url(
                target_url, on_progress=dl_progress_cb
            )

        final_filename = sanitize_filename(custom_filename.strip()) if custom_filename.strip() else original_filename
        logger.info("Downloaded successfully: %s (%d bytes)", final_filename, file_size)

        progress(0.50, desc="ההורדה הושלמה! מכין העלאה למג'יקוד...")
        yield (
            f"<div style='color: #0284c7;'>📥 ההורדה הושלמה ({format_size(file_size)})! מכין סלוט ב-Magicode...</div>",
            "",
            "",
            f"**שם קובץ:** `{final_filename}`\n\n**גודל:** {format_size(file_size)}"
        )

        # Phase 2: Upload to Magicode
        magicode_dl_url = ""
        magicode_view_url = ""
        start_up_time = time.time()
        last_up_yield = 0.0

        async def on_init_cb(dl_url: str, vw_url: str):
            nonlocal magicode_dl_url, magicode_view_url
            magicode_dl_url = dl_url
            magicode_view_url = vw_url

        def up_progress_cb(uploaded: int, total: int):
            nonlocal last_up_yield
            now = time.time()
            if now - last_up_yield < 0.5:
                return
            last_up_yield = now
            pct = (uploaded / max(total, 1)) * 100
            elapsed = max(now - start_up_time, 0.001)
            speed = uploaded / elapsed
            rem_bytes = max(total - uploaded, 0)
            eta = rem_bytes / max(speed, 1.0)
            progress(
                min(0.50 + (pct / 100.0) * 0.50, 0.99),
                desc=f"מעלה למג'יקוד... {pct:.1f}% ({format_size(uploaded)} / {format_size(total)}) | {format_speed(speed)}"
            )

        dl_url, view_url = await uploader.upload_file(
            file_path=temp_file_path,
            filename=final_filename,
            on_init=on_init_cb,
            on_progress=up_progress_cb
        )

        progress(1.0, desc="ההעלאה הושלמה בהצלחה!")

        success_html = f"""
        <div class="result-card">
            <div style="font-size: 20px; font-weight: bold; color: #16a34a; margin-bottom: 12px;">
                ✅ ההעלאה ל-Magicode הושלמה בהצלחה!
            </div>
            <div style="font-size: 15px; color: #334155; line-height: 1.8;">
                📁 <b>שם הקובץ:</b> {final_filename}<br>
                📊 <b>גודל:</b> {format_size(file_size)}<br>
                🔗 <b>קישור ישיר להורדה:</b> <a href="{dl_url}" target="_blank" style="color: #0284c7; font-weight: bold; text-decoration: underline;">{dl_url}</a>
            </div>
        </div>
        """

        summary_md = f"""
### 🎉 פרטי ההעלאה:
- **שם הקובץ:** `{final_filename}`
- **גודל:** {format_size(file_size)}
- **קישור ישיר להורדה:** [{dl_url}]({dl_url})
- **קישור לצפייה:** [{view_url}]({view_url})
        """

        yield (
            success_html,
            dl_url,
            view_url,
            summary_md
        )

    except Exception as exc:
        logger.error("Error during transfer process: %s", exc, exc_info=True)
        error_html = f"""
        <div style="background: #fef2f2; border: 1px solid #ef4444; border-radius: 10px; padding: 16px; color: #991b1b; font-weight: bold;">
            ❌ שגיאה בביצוע ההעברה: {str(exc)}
        </div>
        """
        yield (error_html, "", "", f"❌ **שגיאה:** `{str(exc)}`")

    finally:
        if temp_file_path:
            safe_remove(temp_file_path)
            logger.info("Cleaned up temporary file: %s", temp_file_path)


def build_interface() -> gr.Blocks:
    """Constructs and returns the Gradio web interface."""
    with gr.Blocks(title="Magicode Uploader 🚀") as demo:
        with gr.Column():
            gr.HTML("""
            <div class="main-header">
                <h1>🚀 Magicode Cloud Uploader</h1>
                <p>הדבק קישור ישיר לקובץ, סרטון או שידור וידאו – והורד ישירות ל-Magicode (send.magicode.me) במהירות שיא!</p>
            </div>
            """)

            with gr.Row():
                with gr.Column(scale=3):
                    url_input = gr.Textbox(
                        label="🔗 כתובת הקישור (URL)",
                        placeholder="הדבק כאן קישור ישיר להורדה (HTTP/HTTPS), קישור וידאו (YouTube, TikTok, Twitter וכו') או שידור m3u8...",
                        lines=2,
                        autofocus=True,
                        rtl=True
                    )
                    custom_filename = gr.Textbox(
                        label="✏️ שם קובץ מותאם אישית (אופציונלי)",
                        placeholder="השאר ריק לחילוץ אוטומטי של שם הקובץ המקורי...",
                        lines=1,
                        rtl=True
                    )
                    submit_btn = gr.Button(
                        "⚡ הורד והעלה למג'יקוד",
                        variant="primary",
                        size="lg"
                    )

                with gr.Column(scale=2):
                    status_output = gr.HTML(
                        value="<div style='color: #64748b;'>⏳ ממתין להזנת קישור...</div>",
                        label="סטטוס התקדמות"
                    )
                    direct_link_box = gr.Textbox(
                        label="📥 קישור ישיר להורדה (Magicode Direct Link)",
                        interactive=False,
                        placeholder="הקישור יופיע כאן ברגע ההקצאה..."
                    )
                    view_link_box = gr.Textbox(
                        label="👁️ קישור דף צפייה (Magicode View Link)",
                        interactive=False,
                        placeholder="קישור דף צפייה יופיע כאן..."
                    )

            with gr.Accordion("ℹ️ הנחיות וסוגי קישורים נתמכים", open=False):
                gr.Markdown("""
### 📋 מאפיינים וסוגי קבצים נתמכים:
* **קישורים ישירים (Direct URLs):** כל קובץ בחיבור ישיר (HTTP/HTTPS) כולל קבצי ISO, ZIP, RAR, PDF, וידאו ושמע.
* **רשתות חברתיות ואתרי וידאו:** YouTube, Instagram, TikTok, Twitter/X, Facebook, Vimeo (באמצעות `yt-dlp`).
* **שידורי וידאו HLS (`m3u8`):** הורדה והמרה ישירה ל-MP4 (באמצעות `ffmpeg`).
* **אבטחה ופרטיות:** הקבצים אינם נשמרים בשרת – הם מועברים ישירות ל-Magicode ונמחקים מיד בסיום.
                """)

            # Event triggers
            submit_btn.click(
                fn=process_transfer,
                inputs=[url_input, custom_filename],
                outputs=[status_output, direct_link_box, view_link_box, status_output]
            )
            url_input.submit(
                fn=process_transfer,
                inputs=[url_input, custom_filename],
                outputs=[status_output, direct_link_box, view_link_box, status_output]
            )

    return demo


if __name__ == "__main__":
    app = build_interface()
    # Launch on Hugging Face Spaces port (7860) or configured port
    app.queue().launch(
        server_name=SERVER_NAME,
        server_port=SERVER_PORT,
        theme=gr.themes.Soft(),
        css=CUSTOM_CSS
    )

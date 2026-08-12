# Changelog

All notable changes to the `telegram-magicode-uploader` project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-08-12

### Added
- **Serverless Telegram Webhook & GitHub Actions Architecture**:
  - Cloudflare Worker (`worker/index.js`) for zero-maintenance, serverless Telegram Webhook handling.
  - GitHub Actions Workflow (`.github/workflows/upload.yml`) executing on high-bandwidth Ubuntu runners (1–2 Gbps).
  - CLI Orchestrator (`uploader.py`) supporting direct downloads, Google Drive, and m3u8 streams with automated Telegram notifications.
  - Dedicated Google Drive async downloader (`downloaders/gdrive_dl.py`) supporting large files (>100MB) with virus warning bypass.
  - Seamless Telegram responses with Hebrew formatting, file metadata, and direct download buttons.
- **Privacy & Security Enhancements**:
  - Masked inputs in GitHub Actions logs using `::add-mask::`.
  - Zero-token exposure in public repositories.
  - Generic rejection for unsupported URLs.

### Removed
- Removed `yt-dlp` and social media video scrapers to maintain strict compliance with third-party platform terms of service.
- Removed legacy Gradio UI dependencies.

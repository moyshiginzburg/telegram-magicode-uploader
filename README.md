# Telegram Magicode Uploader 🤖⚡

A serverless, 100% free, and completely private Telegram Bot that receives download links (Direct HTTP/HTTPS, Google Drive, and HLS/m3u8 live streams), downloads them on high-speed **GitHub Actions** cloud runners (1–2 Gbps), and uploads them directly to [send.magicode.me](https://send.magicode.me) — delivering instant direct download links straight to your Telegram chat.

---

## 🌟 Key Features

* 🔒 **100% Private:** Operates entirely within a 1-on-1 private Telegram chat. No public issues, no shared download history.
* ⚡ **High-Speed Cloud Bandwidth (1–2 Gbps):** Downloads and uploads are processed directly on GitHub Actions cloud infrastructure.
* 📂 **Supported Link Types:**
  * 🔗 **Direct HTTP/HTTPS:** Standard web downloads (`.zip`, `.mp4`, `.iso`, `.pdf`, `.apk`, etc.).
  * 📁 **Google Drive:** Publicly shared files (includes automated bypass for large files with Google virus scan confirmation).
  * 📺 **HLS / m3u8 Video Streams:** Direct stream remuxing to `.mp4` using `ffmpeg`.
* 🛡️ **Zero-Secrets Exposure:** Sensitive tokens (Telegram Bot Token and GitHub PAT) remain strictly encrypted inside Cloudflare Worker and GitHub repository Secrets.
* 💰 **100% Free Forever:** Uses Cloudflare Workers free tier (up to 100,000 requests/day) and GitHub Actions.

---

## 🏗️ Architecture Overview

```
User (Telegram) 
   │
   ▼ (Sends link)
Telegram Bot API
   │
   ▼ (Webhook POST)
Cloudflare Worker (worker/index.js)
   │
   ▼ (GitHub REST API: workflow_dispatch)
GitHub Actions Cloud Runner (.github/workflows/upload.yml)
   │  ├── 1. Downloads file (Direct / Google Drive / m3u8)
   │  ├── 2. Uploads chunks to send.magicode.me
   │  └── 3. Sends formatted message with Magicode link to user via Telegram Bot API
   ▼
User receives instant Magicode download link in Telegram!
```

---

## 🚀 Quick Setup Guide (3 Minutes)

### Step 1: Create a Telegram Bot
1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, choose a display name and a unique username (e.g., `MyMagicodeUploaderBot`).
3. Copy the **Bot Token** provided (format: `123456789:ABCdef...`).

### Step 2: Create a GitHub Personal Access Token (PAT)
1. Go to your GitHub account settings: [Personal Access Tokens](https://github.com/settings/tokens?type=beta).
2. Generate a new **Fine-Grained Token** (or Classic Token) with **Actions (Read and write)** permissions on this repository.
3. Copy and save the generated token.

### Step 3: Add Repository Secret in GitHub
1. In your GitHub repository, navigate to **Settings** ➔ **Secrets and variables** ➔ **Actions**.
2. Click **New repository secret**.
3. Name: `TELEGRAM_BOT_TOKEN`.
4. Value: Paste your Telegram Bot Token from Step 1.

### Step 4: Deploy Cloudflare Worker
1. Sign in to your free [Cloudflare Dashboard](https://dash.cloudflare.com).
2. Go to **Workers & Pages** ➔ **Create application** ➔ **Create Worker**.
3. Replace the default code with the contents of [`worker/index.js`](worker/index.js) and click **Deploy**.
4. In Worker **Settings** ➔ **Variables and Secrets**, add:
   * `TELEGRAM_BOT_TOKEN` (Secret / Encrypt): Your Telegram Bot Token.
   * `GITHUB_PAT` (Secret / Encrypt): Your GitHub Personal Access Token.
   * `GITHUB_REPO` (Text): `your-username/telegram-magicode-uploader`.
   * `GITHUB_BRANCH` (Text): `main`.
5. Copy your public Worker URL (e.g., `https://telegram-magicode-worker.your-subdomain.workers.dev`).

### Step 5: Set Telegram Webhook
Open your web browser and navigate to the following URL (substitute your real values):
```
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<WORKER_NAME>.<SUBDOMAIN>.workers.dev
```
You should see: `{"ok":true,"result":true,"description":"Webhook was set"}`.

🎉 **Done!** Send any supported link to your Telegram Bot and receive your Magicode download link instantly!

---

## 💻 Local CLI Usage

You can also run the uploader CLI locally on your system:

```bash
# Clone repository
git clone https://github.com/your-username/telegram-magicode-uploader.git
cd telegram-magicode-uploader

# Setup virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run upload directly
python uploader.py --url "https://example.com/file.zip" --filename "my_file.zip"
```

---

## 📄 License

MIT License. Open source and free for personal and commercial use.

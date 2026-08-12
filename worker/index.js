/**
 * Cloudflare Worker: Serverless Telegram Webhook & GitHub Actions Dispatcher.
 * 
 * Purpose:
 *     Receives incoming Telegram updates via Webhook, validates message URLs,
 *     sends immediate intermediate feedback in Telegram, and securely triggers
 *     the GitHub Actions workflow runner via the GitHub REST API.
 * 
 * Method of operation:
 *     1. Handles incoming POST requests from Telegram Bot API webhook.
 *     2. Verifies optional Telegram Webhook Secret Token (X-Telegram-Bot-Api-Secret-Token).
 *     3. Parses the update and extracts message text or caption.
 *     4. Handles commands like /start and /help with formatted Hebrew guidance.
 *     5. Validates URL format and rejects unsupported social platforms.
 *     6. Sends an instant status message to Telegram ("⏳ מעבד את הבקשה...").
 *     7. Dispatches the 'upload.yml' workflow in GitHub Actions with url, chat_id, and message_id.
 */

const URL_REGEX = /https?:\/\/[^\s]+/i;

const UNSUPPORTED_DOMAINS = [
  "youtube.com", "youtu.be", "m.youtube.com",
  "instagram.com", "instagr.am",
  "tiktok.com", "vm.tiktok.com",
  "twitter.com", "x.com",
  "facebook.com", "fb.watch", "fb.com",
  "vimeo.com", "dailymotion.com", "reddit.com"
];

function isSupportedUrl(urlStr) {
  try {
    const parsed = new URL(urlStr);
    const host = parsed.hostname.toLowerCase();
    
    // Check if domain is blocked
    for (const domain of UNSUPPORTED_DOMAINS) {
      if (host === domain || host.endsWith("." + domain)) {
        return false;
      }
    }
    return true;
  } catch {
    return false;
  }
}

async function sendTelegram(botToken, method, payload) {
  const url = `https://api.telegram.org/bot${botToken}/${method}`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return await resp.json();
}

async function triggerGitHubWorkflow(env, urlToDownload, chatId, messageId, statusMessageId) {
  const repo = env.GITHUB_REPO; // e.g. "username/telegram-magicode-uploader"
  const pat = env.GITHUB_PAT;
  const ref = env.GITHUB_BRANCH || "main";

  if (!repo || !pat) {
    throw new Error("Missing GITHUB_REPO or GITHUB_PAT in Worker environment variables.");
  }

  const endpoint = `https://api.github.com/repos/${repo}/actions/workflows/upload.yml/dispatches`;

  const payload = {
    ref: ref,
    inputs: {
      url: urlToDownload,
      chat_id: String(chatId),
      message_id: String(messageId || ""),
      status_message_id: String(statusMessageId || ""),
    },
  };

  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${pat}`,
      "User-Agent": "Telegram-Magicode-Worker",
      "X-GitHub-Api-Version": "2022-11-28",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`GitHub API error (${response.status}): ${errorText}`);
  }

  return true;
}

export default {
  async fetch(request, env, ctx) {
    // 1. Health check / status page
    if (request.method === "GET") {
      return new Response(
        `<!DOCTYPE html>
        <html dir="rtl" lang="he">
          <head>
            <meta charset="UTF-8">
            <title>Magicode Telegram Worker</title>
            <style>
              body { font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
              .card { background: #1e293b; padding: 2rem; border-radius: 1rem; box-shadow: 0 10px 25px rgba(0,0,0,0.5); text-align: center; max-width: 400px; }
              h1 { color: #38bdf8; margin-top: 0; }
              p { color: #94a3b8; line-height: 1.5; }
              .badge { background: #059669; color: white; padding: 0.25rem 0.75rem; border-radius: 9999px; font-size: 0.875rem; font-weight: bold; }
            </style>
          </head>
          <body>
            <div class="card">
              <h1>בוט Magicode פעיל! 🚀</h1>
              <p><span class="badge">Webhook מוכן ומחובר</span></p>
              <p>ה-Worker פועל ומקשיב להודעות טלגרם להפעלת העלאות ל-Magicode.</p>
            </div>
          </body>
        </html>`,
        { headers: { "Content-Type": "text/html; charset=utf-8" } }
      );
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    // 2. Validate optional Telegram Webhook Secret Token
    const secretToken = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (env.SECRET_WEBHOOK_TOKEN && secretToken !== env.SECRET_WEBHOOK_TOKEN) {
      return new Response("Unauthorized", { status: 401 });
    }

    const botToken = env.TELEGRAM_BOT_TOKEN;
    if (!botToken) {
      return new Response("TELEGRAM_BOT_TOKEN not configured", { status: 500 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("Invalid JSON", { status: 400 });
    }

    const message = update.message || update.edited_message;
    if (!message) {
      return new Response("OK", { status: 200 });
    }

    const chatId = message.chat.id;
    const messageId = message.message_id;
    const text = (message.text || message.caption || "").trim();
    const userId = message.from ? String(message.from.id) : null;
    const adminId = env.ADMIN_CHAT_ID ? String(env.ADMIN_CHAT_ID) : null;
    
    // Dynamic KV Whitelist
    let allowedUsers = [];
    if (env.MAGICODE_USERS) {
      const stored = await env.MAGICODE_USERS.get("whitelist", { type: "json" });
      allowedUsers = stored || [];
    }

    // Admin commands handling
    if (userId === adminId && userId !== null) {
      if (text.startsWith("/adduser ")) {
        const newId = text.split(" ")[1].trim();
        if (!allowedUsers.includes(newId)) {
          allowedUsers.push(newId);
          await env.MAGICODE_USERS.put("whitelist", JSON.stringify(allowedUsers));
        }
        await sendTelegram(botToken, "sendMessage", { chat_id: chatId, text: `✅ המשתמש <code>${newId}</code> נוסף בהצלחה לרשימה המורשית.`, parse_mode: "HTML" });
        return new Response("OK", { status: 200 });
      }
      
      if (text.startsWith("/removeuser ")) {
        const removeId = text.split(" ")[1].trim();
        allowedUsers = allowedUsers.filter(id => id !== removeId);
        await env.MAGICODE_USERS.put("whitelist", JSON.stringify(allowedUsers));
        await sendTelegram(botToken, "sendMessage", { chat_id: chatId, text: `🗑️ המשתמש <code>${removeId}</code> הוסר בהצלחה.`, parse_mode: "HTML" });
        return new Response("OK", { status: 200 });
      }
      
      if (text === "/listusers") {
        const usersList = allowedUsers.length > 0 ? allowedUsers.map(id => `• <code>${id}</code>`).join("\n") : "הרשימה ריקה.";
        await sendTelegram(botToken, "sendMessage", { chat_id: chatId, text: `📋 <b>משתמשים מורשים:</b>\n${usersList}`, parse_mode: "HTML" });
        return new Response("OK", { status: 200 });
      }
    }

    // Enforce Whitelist (Admin is always allowed)
    const isAllowed = (userId === adminId) || allowedUsers.includes(userId);
    if (userId && !isAllowed) {
      await sendTelegram(botToken, "sendMessage", {
        chat_id: chatId,
        text: "⛔ <b>אין לך הרשאה להשתמש בבוט זה.</b>",
        parse_mode: "HTML",
      });
      return new Response("OK", { status: 200 });
    }

    // 3. Handle /start and /help commands
    if (text === "/start" || text === "/help") {
      const welcomeText =
        `👋 <b>שלום וברוך הבא לבוט Magicode Uploader!</b> 🚀\n\n` +
        `שלח לי קישור ישיר, קישור מ-Google Drive או שידור m3u8, ואני אוריד את הקובץ ואעלה אותו ישירות ל-<b>Magicode</b> במהירות שיא!\n\n` +
        `📌 <b>סוגי קישורים נתמכים:</b>\n` +
        `• 🔗 <b>קישור ישיר (HTTP/HTTPS):</b> קובצי zip, mp4, iso, pdf, apk ועוד\n` +
        `• 📁 <b>Google Drive:</b> קבצים משותפים ציבוריים\n` +
        `• 📺 <b>שידורי וידאו:</b> רשימות השמעה בפורמט <code>m3u8</code>\n\n` +
        `⚡ <i>פשוט הדבק את הקישור כאן והבוט יתחיל מיד לעבוד!</i>`;

      await sendTelegram(botToken, "sendMessage", {
        chat_id: chatId,
        text: welcomeText,
        parse_mode: "HTML",
      });
      return new Response("OK", { status: 200 });
    }

    // 4. Extract URL
    const match = text.match(URL_REGEX);
    if (!match) {
      await sendTelegram(botToken, "sendMessage", {
        chat_id: chatId,
        text: "❌ <b>לא זוהה קישור תקין בהודעה.</b>\nאנא שלח קישור ישיר, Google Drive או שידור m3u8.",
        parse_mode: "HTML",
        reply_to_message_id: messageId,
      });
      return new Response("OK", { status: 200 });
    }

    const targetUrl = match[0];

    // 5. Check URL support
    if (!isSupportedUrl(targetUrl)) {
      await sendTelegram(botToken, "sendMessage", {
        chat_id: chatId,
        text: "❌ <b>קישור זה אינו נתמך.</b>\nהבוט תומך בקישורים ישירים, Google Drive ושידורי m3u8 בלבד.",
        parse_mode: "HTML",
        reply_to_message_id: messageId,
      });
      return new Response("OK", { status: 200 });
    }

    // 6. Send immediate pending message
    const pendingResp = await sendTelegram(botToken, "sendMessage", {
      chat_id: chatId,
      text: "⏳ <b>מעבד את הבקשה...</b>\nמפעיל שרת ענן להורדה והעלאה ל-Magicode...",
      parse_mode: "HTML",
      reply_to_message_id: messageId,
    });
    
    let statusMessageId = "";
    if (pendingResp.ok && pendingResp.result) {
      statusMessageId = pendingResp.result.message_id;
    }

    // 7. Trigger GitHub Action
    try {
      await triggerGitHubWorkflow(env, targetUrl, chatId, messageId, statusMessageId);
    } catch (err) {
      await sendTelegram(botToken, "sendMessage", {
        chat_id: chatId,
        text: `❌ <b>שגיאה בהפעלת מנוע הענן ב-GitHub:</b>\n<code>${err.message || err}</code>`,
        parse_mode: "HTML",
        reply_to_message_id: messageId,
      });
    }

    return new Response("OK", { status: 200 });
  },
};

import os
import re
import asyncio
import tempfile
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import yt_dlp

# ===================== SETTINGS =====================

BOT_TOKEN = os.getenv("BOT_TOKEN")

DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "videobot_downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=3)

URL_PATTERN = re.compile(r'https?://[^\s]+')

def is_url(text: str) -> bool:
    return bool(URL_PATTERN.match(text.strip()))

# ===================== YT-DLP CONFIG =====================

def get_ydl_opts(quality: str, output_path: str) -> dict:
    format_map = {
        "best":  "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
        "720p":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best",
        "480p":  "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best",
        "audio": "bestaudio/best",
    }

    opts = {
        "format": format_map.get(quality, format_map["best"]),
        "outtmpl": output_path,
        "merge_output_format": "mp4",
        "quiet": True,
        "socket_timeout": 30,
    }

    if quality == "audio":
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    return opts

# ===================== SYNC FUNCTIONS =====================

def _fetch_info(url: str):
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return info, None
    except Exception as e:
        return None, str(e)

def _download(url: str, quality: str, output_path: str):
    try:
        with yt_dlp.YoutubeDL(get_ydl_opts(quality, output_path)) as ydl:
            ydl.download([url])
        return True, None
    except Exception as e:
        return False, str(e)

# ===================== HANDLERS =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome!\nSend me any video link and choose quality."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send any video URL and choose quality.\nMax size: 50MB"
    )

# ---------- URL HANDLER ----------

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if not is_url(url):
        await update.message.reply_text("❌ Send valid URL")
        return

    msg = await update.message.reply_text("⏳ Fetching...")

    loop = asyncio.get_running_loop()

    # 🔥 FIX: use _fetch_info (NOT fetch_info)
    info, error = await loop.run_in_executor(executor, _fetch_info, url)

    if info is None:
        await msg.edit_text(f"❌ Error:\n{error}")
        return

    title = str(info.get("title", "Video"))[:60]
    uploader = str(info.get("uploader") or info.get("channel") or "Unknown")

    duration = info.get("duration") or 0
    mins = int(duration) // 60
    secs = int(duration) % 60
    duration_str = f"{mins}:{secs:02d}" if duration else "Unknown"

    context.user_data["url"] = url
    context.user_data["title"] = title

    keyboard = [
        [
            InlineKeyboardButton("🎬 Best", callback_data="q_best"),
            InlineKeyboardButton("720p", callback_data="q_720p"),
        ],
        [
            InlineKeyboardButton("480p", callback_data="q_480p"),
            InlineKeyboardButton("🎵 MP3", callback_data="q_audio"),
        ],
        [InlineKeyboardButton("Cancel", callback_data="q_cancel")]
    ]

    await msg.edit_text(
        f"✅ {title}\n👤 {uploader}\n⏱ {duration_str}\n\nChoose quality:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------- QUALITY HANDLER ----------

async def handle_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "q_cancel":
        await query.edit_message_text("Cancelled")
        return

    quality = query.data.replace("q_", "")
    url = context.user_data.get("url")
    title = context.user_data.get("title", "video")

    if not url:
        await query.edit_message_text("Session expired")
        return

    await query.edit_message_text("⬇️ Downloading...")

    safe = re.sub(r'[^\w\s-]', '', title, flags=re.UNICODE)[:40]
    output_path = str(DOWNLOAD_DIR / f"{safe}.%(ext)s")

    loop = asyncio.get_running_loop()
    success, error = await loop.run_in_executor(
        executor, _download, url, quality, output_path
    )

    if not success:
        await query.edit_message_text(f"❌ Download error:\n{error}")
        return

    files = sorted(DOWNLOAD_DIR.glob(f"{safe}.*"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        await query.edit_message_text("❌ File not found")
        return

    file_path = files[0]
    size_mb = file_path.stat().st_size / (1024 * 1024)

    if size_mb > 50:
        file_path.unlink(missing_ok=True)
        await query.edit_message_text("⚠️ File too large (>50MB)")
        return

    await query.edit_message_text("📤 Sending...")

    try:
        with open(file_path, "rb") as f:
            if quality == "audio":
                await query.message.reply_audio(audio=f, title=title)
            else:
                await query.message.reply_video(video=f, caption=title)

        file_path.unlink(missing_ok=True)
        await query.edit_message_text("✅ Done")

    except Exception as e:
        await query.edit_message_text(f"❌ Send error:\n{str(e)}")

# ---------- FALLBACK ----------

async def handle_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send a video URL")

# ===================== MAIN =====================

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'https?://'), handle_url))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_other))
    app.add_handler(CallbackQueryHandler(handle_quality, pattern=r'^q_'))

    logger.info("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()

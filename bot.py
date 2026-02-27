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
BOT_TOKEN = os.getenv("BOT_TOKEN", "8715935868:AAGQdTaUjubzKktepbyd6rpRMLfq4nCxAlM")

DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "videobot_downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

# Thread pool for blocking operations
executor = ThreadPoolExecutor(max_workers=3)

URL_PATTERN = re.compile(r'https?://[^\s]+')

def is_url(text: str) -> bool:
    return bool(URL_PATTERN.match(text.strip()))

def get_ydl_opts(quality: str, output_path: str) -> dict:
    format_map = {
        "best":  "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "720p":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best",
        "480p":  "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]/best",
        "audio": "bestaudio[ext=m4a]/bestaudio",
    }
    opts = {
        "format": format_map.get(quality, format_map["best"]),
        "outtmpl": output_path,
        "quiet": False,
        "no_warnings": False,
        "merge_output_format": "mp4",
        "postprocessors": [],
        "socket_timeout": 30,
    }
    if quality == "audio":
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    return opts

# ---- Pure sync functions (no async, no coroutines) ----

def _fetch_info(url: str):
    """100% synchronous - safe to run in executor"""
    logger.info(f"Fetching: {url}")
    opts = {"quiet": False, "skip_download": True, "socket_timeout": 30}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            logger.info(f"OK: {info.get('title')}")
            return info, None
    except Exception as e:
        logger.error(f"Fetch error: {e}")
        return None, str(e)

def _download(url: str, quality: str, output_path: str):
    """100% synchronous download"""
    logger.info(f"Downloading quality={quality}")
    try:
        with yt_dlp.YoutubeDL(get_ydl_opts(quality, output_path)) as ydl:
            ydl.download([url])
        logger.info("Download done")
        return True, None
    except Exception as e:
        logger.error(f"Download error: {e}")
        return False, str(e)

# ===================== HANDLERS =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Welcome to Video Downloader Bot!*\n\n"
        "📌 *How to use:*\n"
        "Just send me a video link from:\n"
        "▶️ YouTube | 🎵 TikTok | 📘 Facebook\n"
        "📸 Instagram | 🐦 Twitter/X | and more!\n\n"
        "I'll download it for you in high quality 🚀"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Help*\n\n"
        "• Send any video URL directly\n"
        "• Choose quality\n"
        "• Receive your file!\n\n"
        "⚠️ Max file size: 50MB",
        parse_mode="Markdown"
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if not is_url(url):
        await update.message.reply_text("❌ Please send a valid video URL!")
        return

    msg = await update.message.reply_text("⏳ Fetching video info...")

    # Run sync function in thread pool
    loop = asyncio.get_running_loop()
    info, error = await loop.run_in_executor(executor, _fetch_info, url)

    if info is None:
        await msg.edit_text(
            f"❌ *Couldn't get this video.*\n\n`{str(error)[:200]}`",
            parse_mode="Markdown"
        )
        return

    title = str(info.get("title", "Video"))[:60]
    duration = info.get("duration") or 0
    uploader = str(info.get("uploader") or info.get("channel") or "Unknown")
    mins = int(duration) // 60
    secs = int(duration) % 60
    duration_str = f"{mins}:{secs:02d}" if duration else "Unknown"

    context.user_data["url"] = url
    context.user_data["title"] = title

    keyboard = [
        [
            InlineKeyboardButton("🎬 Best Quality", callback_data="q_best"),
            InlineKeyboardButton("📺 720p", callback_data="q_720p"),
        ],
        [
            InlineKeyboardButton("📱 480p", callback_data="q_480p"),
            InlineKeyboardButton("🎵 Audio MP3", callback_data="q_audio"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="q_cancel")],
    ]

    await msg.edit_text(
        f"✅ *Video found!*\n\n"
        f"📝 *Title:* {title}\n"
        f"👤 *Channel:* {uploader}\n"
        f"⏱ *Duration:* {duration_str}\n\n"
        "Choose quality:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "q_cancel":
        await query.edit_message_text("❌ Cancelled.")
        return

    quality = query.data.replace("q_", "")
    url = context.user_data.get("url")
    title = context.user_data.get("title", "video")

    if not url:
        await query.edit_message_text("❌ Session expired. Send the link again.")
        return

    labels = {"best": "Best Quality", "720p": "720p", "480p": "480p", "audio": "Audio MP3"}
    await query.edit_message_text(
        f"⬇️ *Downloading...*\n📊 {labels.get(quality, quality)}\n⏳ Please wait...",
        parse_mode="Markdown"
    )

    safe = re.sub(r'[^\w\s-]', '', title)[:40].strip() or "video"
    output_path = str(DOWNLOAD_DIR / f"{safe}.%(ext)s")

    loop = asyncio.get_running_loop()
    success, dl_error = await loop.run_in_executor(executor, _download, url, quality, output_path)

    if not success:
        await query.edit_message_text(
            f"❌ *Download failed!*\n\n`{str(dl_error)[:200]}`",
            parse_mode="Markdown"
        )
        return

    # Find the file
    files = sorted(DOWNLOAD_DIR.glob(f"{safe}.*"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        files = sorted(DOWNLOAD_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)

    if not files:
        await query.edit_message_text("❌ File not found after download.")
        return

    file_path = files[0]
    size_mb = file_path.stat().st_size / (1024 * 1024)
    logger.info(f"Sending: {file_path.name} ({size_mb:.1f}MB)")

    if size_mb > 50:
        file_path.unlink(missing_ok=True)
        await query.edit_message_text(
            f"⚠️ File too large ({size_mb:.1f}MB). Try lower quality."
        )
        return

    await query.edit_message_text("📤 *Sending...*", parse_mode="Markdown")

    try:
        with open(file_path, "rb") as f:
            if quality == "audio":
                await query.message.reply_audio(
                    audio=f,
                    title=title[:64],
                    caption="🎵 Done!"
                )
            else:
                await query.message.reply_video(
                    video=f,
                    caption=f"🎬 *{title}*\n\n✅ Done!",
                    parse_mode="Markdown",
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                )
        file_path.unlink(missing_ok=True)
        await query.edit_message_text("✅ *Enjoy!* 🎉", parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Send error: {e}")
        await query.edit_message_text(f"❌ Failed to send.\n\n`{str(e)[:200]}`", parse_mode="Markdown")

async def handle_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📎 Send a video URL please!\nExample: https://youtube.com/watch?v=...")

def main():
    logger.info("Bot starting...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'https?://'), handle_url))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_other))
    app.add_handler(CallbackQueryHandler(handle_quality, pattern=r'^q_'))
    logger.info("🤖 Running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

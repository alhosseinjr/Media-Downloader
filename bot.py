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

COOKIES_FILE = Path("/app/cookies.txt")
COOKIES_PATH = str(COOKIES_FILE) if COOKIES_FILE.exists() else None

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)
logger.info(f"Cookies: {'found' if COOKIES_PATH else 'not found'}")

executor = ThreadPoolExecutor(max_workers=3)
URL_PATTERN = re.compile(r'https?://[^\s]+')

def is_url(text: str) -> bool:
    return bool(URL_PATTERN.match(text.strip()))

# ===================== YT-DLP OPTIONS =====================

def get_video_opts(output_path: str) -> dict:
    """
    Download best single-file video (no merge needed).
    Picks the best pre-muxed format that already has video+audio together.
    """
    opts = {
        # best single file that already contains video+audio — no ffmpeg needed
        "format": "best[ext=mp4]/best",
        "outtmpl": output_path,
        "quiet": False,
        "no_warnings": False,
        "socket_timeout": 30,
        "noplaylist": True,
    }
    if COOKIES_PATH:
        opts["cookiefile"] = COOKIES_PATH
    return opts

def get_audio_opts(output_path: str) -> dict:
    """Download best audio and convert to mp3 using ffmpeg."""
    opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "quiet": False,
        "no_warnings": False,
        "socket_timeout": 30,
        "noplaylist": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    if COOKIES_PATH:
        opts["cookiefile"] = COOKIES_PATH
    return opts

def get_info_opts() -> dict:
    opts = {
        "quiet": False,
        "skip_download": True,
        "socket_timeout": 30,
        "noplaylist": True,
    }
    if COOKIES_PATH:
        opts["cookiefile"] = COOKIES_PATH
    return opts

# ===================== SYNC FUNCTIONS =====================

def _fetch_info(url: str):
    logger.info(f"Fetching: {url}")
    try:
        with yt_dlp.YoutubeDL(get_info_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
            logger.info(f"OK: {info.get('title')}")
            return info, None
    except Exception as e:
        logger.error(f"Fetch error: {e}")
        return None, str(e)

def _download_video(url: str, output_path: str):
    logger.info("Downloading video...")
    try:
        with yt_dlp.YoutubeDL(get_video_opts(output_path)) as ydl:
            ydl.download([url])
        logger.info("Video download done")
        return True, None
    except Exception as e:
        logger.error(f"Video download error: {e}")
        return False, str(e)

def _download_audio(url: str, output_path: str):
    logger.info("Downloading audio...")
    try:
        with yt_dlp.YoutubeDL(get_audio_opts(output_path)) as ydl:
            ydl.download([url])
        logger.info("Audio download done")
        return True, None
    except Exception as e:
        logger.error(f"Audio download error: {e}")
        return False, str(e)

# ===================== HANDLERS =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome to Video Downloader Bot!*\n\n"
        "Send me any video link from:\n"
        "▶️ Facebook | 📸 Instagram | 🐦 Twitter/X\n"
        "🎵 TikTok | and more!\n\n"
        "I'll download it for you 🚀",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Help*\n\n"
        "• Send any video URL\n"
        "• Choose Video or Audio\n"
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

    loop = asyncio.get_running_loop()
    info, error = await loop.run_in_executor(executor, _fetch_info, url)

    if info is None:
        await msg.edit_text(
            f"❌ *Couldn't get this video.*\n\n`{str(error)[:300]}`",
            parse_mode="Markdown"
        )
        return

    title = str(info.get("title", "Video"))[:60]
    uploader = str(info.get("uploader") or info.get("channel") or "Unknown")
    duration = info.get("duration") or 0
    duration_str = f"{int(duration)//60}:{int(duration)%60:02d}" if duration else "Unknown"

    context.user_data["url"] = url
    context.user_data["title"] = title

    keyboard = [
        [
            InlineKeyboardButton("🎬 Video", callback_data="dl_video"),
            InlineKeyboardButton("🎵 Audio MP3", callback_data="dl_audio"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="dl_cancel")],
    ]

    await msg.edit_text(
        f"✅ *Video found!*\n\n"
        f"📝 *Title:* {title}\n"
        f"👤 *Channel:* {uploader}\n"
        f"⏱ *Duration:* {duration_str}\n\n"
        "Choose format:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "dl_cancel":
        await query.edit_message_text("❌ Cancelled.")
        return

    choice = query.data  # dl_video or dl_audio
    url = context.user_data.get("url")
    title = context.user_data.get("title", "video")

    if not url:
        await query.edit_message_text("❌ Session expired. Send the link again.")
        return

    await query.edit_message_text("⬇️ *Downloading...*\n⏳ Please wait...", parse_mode="Markdown")

    safe = re.sub(r'[^\w\s-]', '', title)[:40].strip() or "video"
    output_path = str(DOWNLOAD_DIR / f"{safe}.%(ext)s")

    loop = asyncio.get_running_loop()

    if choice == "dl_video":
        success, dl_error = await loop.run_in_executor(executor, _download_video, url, output_path)
    else:
        success, dl_error = await loop.run_in_executor(executor, _download_audio, url, output_path)

    if not success:
        await query.edit_message_text(
            f"❌ *Download failed!*\n\n`{str(dl_error)[:300]}`",
            parse_mode="Markdown"
        )
        return

    # Find the downloaded file
    files = sorted(DOWNLOAD_DIR.glob(f"{safe}.*"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        files = sorted(DOWNLOAD_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)

    if not files:
        await query.edit_message_text("❌ File not found after download.")
        return

    file_path = files[0]
    size_mb = file_path.stat().st_size / (1024 * 1024)
    logger.info(f"File: {file_path.name} ({size_mb:.1f}MB)")

    if size_mb > 50:
        file_path.unlink(missing_ok=True)
        await query.edit_message_text(
            f"⚠️ File too large ({size_mb:.1f}MB).\nTelegram limit is 50MB."
        )
        return

    await query.edit_message_text("📤 *Sending file...*", parse_mode="Markdown")

    try:
        with open(file_path, "rb") as f:
            if choice == "dl_audio":
                await query.message.reply_audio(
                    audio=f,
                    title=title[:64],
                    caption="🎵 Done!",
                    read_timeout=120,
                    write_timeout=120,
                )
            else:
                await query.message.reply_video(
                    video=f,
                    caption=f"🎬 {title}\n\n✅ Done!",
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                )

        file_path.unlink(missing_ok=True)
        await query.edit_message_text("✅ *Enjoy!* 🎉", parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Send error: {e}")
        await query.edit_message_text(
            f"❌ *Failed to send.*\n\n`{str(e)[:200]}`",
            parse_mode="Markdown"
        )

async def handle_other(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📎 Send a video URL!\nExample: https://facebook.com/...")

def main():
    logger.info("Bot starting...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'https?://'), handle_url))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_other))
    app.add_handler(CallbackQueryHandler(handle_choice, pattern=r'^dl_'))
    logger.info("🤖 Bot running!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

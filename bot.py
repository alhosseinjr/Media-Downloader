import os
import re
import asyncio
import tempfile
import logging
from pathlib import Path

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

def fetch_info_sync(url: str):
    """Synchronous fetch - runs in executor"""
    ydl_opts = {
        "quiet": False,
        "no_warnings": False,
        "skip_download": True,
        "socket_timeout": 30,
        "extractor_args": {},
    }
    logger.info(f"Fetching info for URL: {url}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            logger.info(f"Successfully fetched: {info.get('title', 'No title')}")
            return info, None
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError: {e}")
        return None, str(e)
    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__}: {e}")
        return None, str(e)

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
    text = (
        "📖 *Help*\n\n"
        "• Send any video URL directly\n"
        "• Choose your preferred quality\n"
        "• Wait a moment and receive your file!\n\n"
        "⚠️ *Note:* Videos larger than 50MB cannot be sent via Telegram."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if not is_url(url):
        await update.message.reply_text(
            "❌ That doesn't look like a valid URL!\n"
            "Please send a video link from YouTube, TikTok, Instagram, etc."
        )
        return

    msg = await update.message.reply_text("⏳ Fetching video info...")

    loop = asyncio.get_event_loop()
    info, error = await loop.run_in_executor(None, fetch_info_sync, url)

    if not info:
        error_msg = error or "Unknown error"
        logger.error(f"Failed to fetch info: {error_msg}")
        await msg.edit_text(
            f"❌ *Couldn't retrieve this video.*\n\n"
            f"Reason: `{error_msg[:200]}`\n\n"
            f"Please check the link and try again.",
            parse_mode="Markdown"
        )
        return

    title = info.get("title", "Video")[:60]
    duration = info.get("duration", 0)
    uploader = info.get("uploader") or info.get("channel") or "Unknown"
    duration_str = f"{int(duration) // 60}:{int(duration) % 60:02d}" if duration else "Unknown"

    context.user_data["pending_url"] = url
    context.user_data["video_title"] = title

    keyboard = [
        [
            InlineKeyboardButton("🎬 Best Quality", callback_data="quality_best"),
            InlineKeyboardButton("📺 720p", callback_data="quality_720p"),
        ],
        [
            InlineKeyboardButton("📱 480p", callback_data="quality_480p"),
            InlineKeyboardButton("🎵 Audio only (MP3)", callback_data="quality_audio"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]

    caption = (
        f"✅ *Video found!*\n\n"
        f"📝 *Title:* {title}\n"
        f"👤 *Channel:* {uploader}\n"
        f"⏱ *Duration:* {duration_str}\n\n"
        f"Choose your preferred quality:"
    )
    await msg.edit_text(caption, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_quality_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        return

    quality = query.data.replace("quality_", "")
    url = context.user_data.get("pending_url")
    title = context.user_data.get("video_title", "video")

    if not url:
        await query.edit_message_text("❌ Session expired. Please send the link again.")
        return

    quality_labels = {"best": "Best Quality", "720p": "720p", "480p": "480p", "audio": "Audio MP3"}
    await query.edit_message_text(
        f"⬇️ *Downloading...*\n📊 Quality: {quality_labels.get(quality)}\n⏳ Please wait...",
        parse_mode="Markdown"
    )

    safe_title = re.sub(r'[^\w\s-]', '', title)[:40].strip() or "video"
    output_path = str(DOWNLOAD_DIR / f"{safe_title}.%(ext)s")

    def do_download():
        logger.info(f"Starting download: {url} quality={quality}")
        with yt_dlp.YoutubeDL(get_ydl_opts(quality, output_path)) as ydl:
            ydl.download([url])
        logger.info("Download complete")

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, do_download)

        # Find downloaded file
        files = sorted(DOWNLOAD_DIR.glob(f"{safe_title}.*"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not files:
            files = sorted(DOWNLOAD_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)

        if not files:
            await query.edit_message_text("❌ Download failed - file not found. Please try again.")
            return

        file_path = files[0]
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        logger.info(f"File ready: {file_path} ({file_size_mb:.1f}MB)")

        if file_size_mb > 50:
            await query.edit_message_text(
                f"⚠️ File too large ({file_size_mb:.1f}MB).\n"
                "Telegram limit is 50MB. Please try a lower quality."
            )
            file_path.unlink(missing_ok=True)
            return

        await query.edit_message_text("📤 *Sending file...*", parse_mode="Markdown")

        with open(file_path, "rb") as f:
            if quality == "audio":
                await query.message.reply_audio(
                    audio=f,
                    title=title[:64],
                    caption="🎵 Downloaded successfully!"
                )
            else:
                await query.message.reply_video(
                    video=f,
                    caption=f"🎬 *{title[:200]}*\n\n✅ Downloaded successfully!",
                    parse_mode="Markdown",
                    supports_streaming=True,
                    read_timeout=120,
                    write_timeout=120,
                )

        file_path.unlink(missing_ok=True)
        await query.edit_message_text("✅ *Done! Enjoy* 🎉", parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Download/send error: {type(e).__name__}: {e}")
        await query.edit_message_text(
            f"❌ *Failed!*\n\n`{str(e)[:200]}`\n\nPlease try another link.",
            parse_mode="Markdown"
        )

async def handle_non_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📎 Please send a video URL!\nExample: https://youtube.com/watch?v=..."
    )

def main():
    logger.info("Starting bot...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'https?://'), handle_url))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_non_url))
    app.add_handler(CallbackQueryHandler(handle_quality_choice, pattern=r'^quality_|^cancel$'))
    logger.info("🤖 Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

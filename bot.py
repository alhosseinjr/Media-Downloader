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
    level=logging.INFO
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
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "postprocessors": [],
    }
    if quality == "audio":
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    return opts

async def fetch_info(url: str):
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        logger.error(f"fetch_info error: {e}")
        return None

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
        "⚠️ *Note:* Videos larger than 50MB cannot be sent via Telegram.\n"
        "In that case, try a lower quality."
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
    info = await asyncio.get_event_loop().run_in_executor(None, lambda: fetch_info(url))

    if not info:
        await msg.edit_text("❌ Couldn't retrieve this video.\nPlease check the link and try again.")
        return

    title = info.get("title", "Video")[:60]
    duration = info.get("duration", 0)
    uploader = info.get("uploader", "Unknown")
    duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "Unknown"

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

    safe_title = re.sub(r'[^\w\s-]', '', title)[:40].strip()
    output_path = str(DOWNLOAD_DIR / f"{safe_title}.%(ext)s")

    try:
        def do_download():
            with yt_dlp.YoutubeDL(get_ydl_opts(quality, output_path)) as ydl:
                ydl.download([url])

        await asyncio.get_event_loop().run_in_executor(None, do_download)

        files = list(DOWNLOAD_DIR.glob(f"{safe_title}.*"))
        if not files:
            files = sorted(DOWNLOAD_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)

        if not files:
            await query.edit_message_text("❌ Download failed. Please try again.")
            return

        file_path = files[0]
        file_size_mb = file_path.stat().st_size / (1024 * 1024)

        if file_size_mb > 50:
            await query.edit_message_text(
                f"⚠️ File too large ({file_size_mb:.1f}MB). Telegram limit is 50MB.\nTry a lower quality."
            )
            file_path.unlink(missing_ok=True)
            return

        await query.edit_message_text("📤 *Sending file...*", parse_mode="Markdown")

        with open(file_path, "rb") as f:
            if quality == "audio":
                await query.message.reply_audio(audio=f, title=title[:64], caption="🎵 Downloaded successfully!")
            else:
                await query.message.reply_video(
                    video=f,
                    caption=f"🎬 *{title[:200]}*\n\n✅ Downloaded successfully!",
                    parse_mode="Markdown",
                    supports_streaming=True
                )

        file_path.unlink(missing_ok=True)
        await query.edit_message_text("✅ *Done! Enjoy* 🎉", parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Download error: {e}")
        await query.edit_message_text(
            "❌ *Download failed!*\n\nPossible reasons:\n"
            "• Video is private or protected\n"
            "• Link has expired\n"
            "• Platform not supported\n\nPlease try another link.",
            parse_mode="Markdown"
        )

async def handle_non_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📎 Please send a video URL!\nExample: https://youtube.com/watch?v=...")

def main():
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

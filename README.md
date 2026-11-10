# Media-Downloader Bot

A Telegram bot for downloading videos from social media platforms (YouTube, Instagram, TikTok, X/Twitter, and more) using `yt-dlp`.

## Features

- Send a video link, get the video back as a document/stream
- Inline quality selection via inline keyboard
- Optional browser-cookie support for age-restricted or login-required content (`cookies.txt` mounted at `/app/cookies.txt` — never commit this file)
- Deployed on Railway (`railway.toml` included)

## Setup

```bash
pip install -r requirements.txt
export BOT_TOKEN="your-telegram-bot-token"   # get one from @BotFather
python bot.py
```

> ⚠️ **Never commit `BOT_TOKEN` or `cookies.txt`.** Keep them in environment variables / local files only.

## Railway deployment

Set the `BOT_TOKEN` environment variable in the Railway service settings and deploy the repo. Optional: mount the cookies file at `/app/cookies.txt`.

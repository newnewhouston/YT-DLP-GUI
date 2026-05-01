# YT-DLP GUI

A minimal browser-based GUI for [yt-dlp](https://github.com/yt-dlp/yt-dlp). Paste a URL, pick a quality, download. Supports Twitter/X, YouTube, Instagram, Reddit, and 1800+ other sites.

![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue) ![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

## Requirements

- Python 3.8 or newer
- Windows 10/11 (for auto-install via winget; other platforms work manually)

Everything else — Flask, yt-dlp, ffmpeg, and Node.js — is installed automatically on first run.

## Usage

```
python yt-dlp-gui.py
```

The script opens `http://localhost:7331` in your browser automatically.

## What it does on first run

| Dependency | How it's installed |
|---|---|
| `flask` | `pip install flask` |
| `yt-dlp` | `pip install yt-dlp` |
| `ffmpeg` | `winget install Gyan.FFmpeg` |
| `Node.js` | `winget install OpenJS.NodeJS` |

ffmpeg is required for merging separate video and audio streams (needed for 1080p and for MP3 extraction). Node.js is required for YouTube extraction. If either is already installed, the step is skipped.

If `winget` is not available, the script will print manual install instructions and continue with reduced functionality.

## Features

- Paste a URL and download in one click
- Quality options: Best, 1080p, 720p, 480p, Audio only (MP3)
- Quality options automatically adjust if ffmpeg is not installed
- Live progress bar with speed and ETA
- Download log
- Cancel button
- Saves to `~/Downloads` by default; path is editable

## Manual dependency install (non-Windows / no winget)

**ffmpeg**
- macOS: `brew install ffmpeg`
- Linux: `sudo apt install ffmpeg`
- Windows: [ffmpeg.org/download.html](https://ffmpeg.org/download.html)

**Node.js**
- All platforms: [nodejs.org](https://nodejs.org)

## Notes

- The Flask "development server" warning in the terminal is expected and harmless — this tool only listens on `localhost` and is not exposed to the network.
- The YouTube JS runtime warning is resolved by installing Node.js.
- Files are saved as `Uploader - Title.mp4` (or `.mp3` for audio).

## License

MIT

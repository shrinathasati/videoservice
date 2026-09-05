# Shrinath's Web Service — YouTube Downloader

A single-page, mobile-responsive site that downloads a YouTube video (or Short)
as an MP4 file.

## How it works

1. Paste a YouTube video or Shorts link and press **Submit**.
2. The button switches to a loading spinner while the server fetches and
   merges the video with `yt-dlp`.
3. Once it's ready, the button turns into **Download** — press it again to
   save the MP4 to your device.

## Run it locally

```bash
# 1. Create a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the server
python app.py
```

Then open **http://localhost:5000** in your browser (or your phone, if it's
on the same network — use your computer's local IP instead of `localhost`).

## Notes

- Requires `ffmpeg` on your system PATH so `yt-dlp` can merge video + audio
  into a single MP4 (`brew install ffmpeg` on Mac, `apt install ffmpeg` on
  Ubuntu/Debian, or download a build for Windows).
- Downloaded files are stored temporarily in the `downloads/` folder and are
  deleted automatically a few seconds after the download starts, and any file
  older than 30 minutes is cleaned up on the next request.
- Only download videos you own or have permission/rights to save — respect
  YouTube's Terms of Service and copyright law in your region.
- This is a simple single-user/demo setup (in-memory job tracking). For real
  production use behind multiple users, you'd want a proper task queue
  (e.g. Celery + Redis) instead of the in-memory dictionary.

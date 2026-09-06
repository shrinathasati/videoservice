import os
import re
import time
import uuid
import threading

from flask import Flask, render_template, request, jsonify, send_file, after_this_request

try:
    import yt_dlp
except ImportError:  # pragma: no cover
    yt_dlp = None

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# In-memory job store: job_id -> {"status", "filepath", "title", "error"}
JOBS = {}
JOBS_LOCK = threading.Lock()

YOUTUBE_URL_PATTERN = re.compile(
    r"^(https?://)?(www\.)?(m\.)?(youtube\.com|youtu\.be)/.+", re.IGNORECASE
)


def is_valid_youtube_url(url: str) -> bool:
    return bool(YOUTUBE_URL_PATTERN.match(url.strip()))


def cleanup_old_files(max_age_minutes=30):
    """Delete leftover files older than max_age_minutes."""
    now = time.time()
    for fname in os.listdir(DOWNLOAD_DIR):
        fpath = os.path.join(DOWNLOAD_DIR, fname)
        try:
            if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > max_age_minutes * 60:
                os.remove(fpath)
        except OSError:
            pass


def run_download(job_id: str, url: str):
    """Background worker: downloads the video/short and merges to MP4."""
    try:
        cleanup_old_files()
        output_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

        cookie_path = "/etc/secrets/cookies.txt" if os.path.exists("/etc/secrets/cookies.txt") else "cookies.txt"
        print("COOKIE FILE EXISTS:", os.path.exists(cookie_path), cookie_path, flush=True)

        ydl_opts = {
            "format": "bv*+ba/b",
            "outtmpl": output_template,
            "cookiefile": cookie_path if os.path.exists(cookie_path) else None,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "web"]
                }
            },
        }


        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")
            filename = ydl.prepare_filename(info)
            base, _ = os.path.splitext(filename)
            final_path = base + ".mp4"
            if not os.path.exists(final_path):
                final_path = filename

        with JOBS_LOCK:
            JOBS[job_id] = {
                "status": "done",
                "filepath": final_path,
                "title": title,
                "error": None,
            }
    except Exception as exc:
        with JOBS_LOCK:
            JOBS[job_id] = {
                "status": "error",
                "filepath": None,
                "title": None,
                "error": str(exc),
            }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start_download():
    if yt_dlp is None:
        return jsonify({"error": "Server is missing the yt-dlp dependency. Run: pip install yt-dlp"}), 500

    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"error": "Paste a YouTube video or Shorts link first."}), 400
    if not is_valid_youtube_url(url):
        return jsonify({"error": "That doesn't look like a YouTube link."}), 400

    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "processing", "filepath": None, "title": None, "error": None}

    threading.Thread(target=run_download, args=(job_id, url), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def check_status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job."}), 404
    return jsonify({"status": job["status"], "title": job.get("title"), "error": job.get("error")})


@app.route("/api/download/<job_id>")
def download_file(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)

    if not job or job["status"] != "done" or not job["filepath"] or not os.path.exists(job["filepath"]):
        return jsonify({"error": "File isn't ready yet."}), 404

    filepath = job["filepath"]
    title = job.get("title") or "video"
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)[:80].strip() or "video"

    @after_this_request
    def cleanup(response):
        def _delayed_remove():
            time.sleep(5)
            try:
                os.remove(filepath)
            except OSError:
                pass
            with JOBS_LOCK:
                JOBS.pop(job_id, None)
        threading.Thread(target=_delayed_remove, daemon=True).start()
        return response

    return send_file(
        filepath,
        as_attachment=True,
        download_name=f"{safe_title}.mp4",
        mimetype="video/mp4",
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

import os
import re
import time
import uuid
import shutil
import subprocess
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

BGUTIL_SERVER_DIR = os.path.join(BASE_DIR, "bgutil-ytdlp-pot-provider", "server")


def start_bgutil_server():
    build_file = os.path.join(BGUTIL_SERVER_DIR, "build", "main.js")
    if os.path.exists(build_file):
        subprocess.Popen(
            ["node", "build/main.js"],
            cwd=BGUTIL_SERVER_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("Started bgutil PO Token server", flush=True)
    else:
        print("bgutil server not built — check build logs", flush=True)


start_bgutil_server()

JOBS = {}
JOBS_LOCK = threading.Lock()

YOUTUBE_URL_PATTERN = re.compile(
    r"^(https?://)?(www\.)?(m\.)?(youtube\.com|youtu\.be)/.+", re.IGNORECASE
)


def is_valid_youtube_url(url: str) -> bool:
    return bool(YOUTUBE_URL_PATTERN.match(url.strip()))


def get_cookie_path():
    secret_path = "/etc/secrets/cookies.txt"
    writable_path = "/tmp/cookies.txt"
    local_path = os.path.join(BASE_DIR, "cookies.txt")

    if os.path.exists(secret_path):
        if not os.path.exists(writable_path):
            shutil.copyfile(secret_path, writable_path)
        return writable_path

    if os.path.exists(local_path):
        return local_path

    return None


def cleanup_old_files(max_age_minutes=30):
    now = time.time()
    for fname in os.listdir(DOWNLOAD_DIR):
        fpath = os.path.join(DOWNLOAD_DIR, fname)
        try:
            if os.path.isfile(fpath) and now - os.path.getmtime(fpath) > max_age_minutes * 60:
                os.remove(fpath)
        except OSError:
            pass


def run_download(job_id: str, url: str):
    try:
        cleanup_old_files()
        output_template = os.path.join(DOWNLOAD_DIR, f"{job_id}.%(ext)s")

        cookie_path = get_cookie_path()
        print("COOKIE FILE EXISTS:", cookie_path is not None, cookie_path, flush=True)

        ydl_opts = {
            "format": "bv*+ba/b",
            "outtmpl": output_template,
            "proxy": "http://oxesqivg:f37o0ztqvoo6@45.38.107.97:6014",
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": False,
            "verbose": True,
            "no_warnings": False,
            "restrictfilenames": True,
            "retries": 10,
            "fragment_retries": 10,
            "socket_timeout": 30,
            "js_runtimes": {"node": {}},
            "remote_components": {"ejs:github"},
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios"],
                }
            },
        }
        # NOTE: cookiefile intentionally left out for this attempt -- the
        # android/ios clients skip cookie-based auth entirely (they rely on
        # the PO Token server instead), and passing cookies was causing
        # yt-dlp to skip those two clients ("does not support cookies").
        # if cookie_path:
        #     ydl_opts["cookiefile"] = cookie_path

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
    app.run(debug=False, host="0.0.0.0", port=port)
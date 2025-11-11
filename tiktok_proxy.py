import json
import os
import sys
import random
import requests
import subprocess
from flask import Flask, jsonify, request, send_file
from urllib.parse import quote

app = Flask(__name__)
SESSION = requests.Session()

# -------------------------------
# Load TikTok cookies
# -------------------------------
COOKIES_FILE = os.path.join(os.path.dirname(__file__), "cookies.json")
if not os.path.exists(COOKIES_FILE):
    print("❌ cookies.json not found.")
    sys.exit(1)

with open(COOKIES_FILE, "r") as f:
    cookies_data = json.load(f)

for c in cookies_data:
    try:
        SESSION.cookies.set(
            c.get("name") or c["Name"],
            c.get("value") or c["Value"],
            domain=c.get("domain") or c.get("Domain", ".tiktok.com")
        )
    except Exception as e:
        print(f"[!] Skipping bad cookie: {e}")

# -------------------------------
# Basic constants
# -------------------------------
MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 15_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.5 Mobile/15E148 Safari/604.1"
    ),
    "Referer": "https://www.tiktok.com/foryou",
    "Accept": "application/json, text/plain, */*",
}

TIKTOK_BASE = "https://m.tiktok.com/"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "video_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


# -------------------------------
# Infinite Scroll FYP Endpoint
# -------------------------------
@app.route("/fyp")
def fyp():
    print("[+] Fetching TikTok feed (infinite scroll enabled)")

    # Accept cursor parameter for pagination
    cursor = request.args.get("cursor", str(random.randint(1000, 999999)))
    count = int(request.args.get("count", 10))

    params = {
        "count": count,
        "aid": 1988,
        "cookie_enabled": "true",
        "screen_width": 720,
        "screen_height": 1280,
        "region": "US",
        "language": "en",
        "cursor": cursor,  # random cursor for infinite scroll
    }

    try:
        r = SESSION.get(
            TIKTOK_BASE + "api/recommend/item_list/",
            headers=MOBILE_HEADERS,
            params=params,
            timeout=15
        )
        print("[+] TikTok status:", r.status_code)
        data = r.json()
    except Exception as e:
        print(f"[!] Request or JSON error: {e}")
        return jsonify({"error": str(e), "videos": []})

    items = []
    for video in data.get("itemList", []):
        if not isinstance(video, dict):
            continue

        video_id = video.get("id")
        desc = video.get("desc", "(no title)")
        video_info = video.get("video", {})
        play_addr = video_info.get("playAddr") or {}

        # Handle all URL formats (dict, list, or string)
        urls = []
        if isinstance(play_addr, dict):
            urls = play_addr.get("url_list", [])
        elif isinstance(play_addr, list):
            urls = play_addr
        elif isinstance(play_addr, str):
            urls = [play_addr]

        if not urls:
            continue

        first_url = urls[0]
        safe_name = f"{video_id}.mp4"
        proxied_url = f"http://{request.host}/video_proxy?file={quote(safe_name)}&url={quote(first_url)}"

        items.append({
            "id": video_id,
            "desc": desc,
            "video_url": proxied_url
        })

    # Compute next cursor (randomized so TikTok gives fresh results)
    next_cursor = str(random.randint(1000, 999999))

    print(f"[+] Delivered {len(items)} videos (next_cursor={next_cursor})")

    return jsonify({
        "cursor": next_cursor,
        "videos": items
    })


# -------------------------------
# Video Proxy (iOS6 compatible)
# -------------------------------
@app.route("/video_proxy")
def video_proxy():
    file_name = request.args.get("file")
    original_url = request.args.get("url")
    if not file_name or not original_url:
        return jsonify({"error": "missing file or url"}), 400

    cached_path = os.path.join(CACHE_DIR, file_name)
    if not os.path.exists(cached_path):
        try:
            print(f"[+] Downloading and converting {file_name}...")
            r = SESSION.get(original_url, headers=MOBILE_HEADERS, stream=True, timeout=30)
            if r.status_code != 200:
                return jsonify({"error": f"download failed {r.status_code}"}), 500

            tmp_path = cached_path + ".tmp"
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)

            # Convert to iOS6-compatible baseline H.264
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", tmp_path,
                "-c:v", "libx264",
                "-profile:v", "baseline",
                "-level", "3.0",
                "-pix_fmt", "yuv420p",
                "-preset", "ultrafast",
                "-c:a", "aac",
                "-movflags", "+faststart",
                cached_path
            ]
            subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.remove(tmp_path)

        except Exception as e:
            print(f"[!] Proxy error: {e}")
            return jsonify({"error": str(e)}), 500

    return send_file(cached_path, mimetype="video/mp4")


# -------------------------------
# Run Server
# -------------------------------
if __name__ == "__main__":
    print("✅ TikTok proxy ready on http://0.0.0.0:5000/fyp (infinite scroll mode)")
    app.run(host="0.0.0.0", port=5000, debug=True)

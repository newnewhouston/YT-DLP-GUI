"""
YT-DLP GUI
A browser-based GUI for yt-dlp. Supports Twitter/X, YouTube, Instagram, and 1800+ other sites.
Run:  python yt-dlp-gui.py
Flask, yt-dlp, ffmpeg, and Node.js are auto-installed on first run.
"""

import sys
import subprocess
import os
import shutil


def _refresh_windows_path():
    """Re-read PATH from the Windows registry into the current process."""
    try:
        import winreg
        parts = []
        for hive, subkey in [
            (winreg.HKEY_LOCAL_MACHINE,
             r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            (winreg.HKEY_CURRENT_USER, r"Environment"),
        ]:
            try:
                with winreg.OpenKey(hive, subkey) as k:
                    val, _ = winreg.QueryValueEx(k, "PATH")
                    parts.extend(val.split(";"))
            except OSError:
                pass
        if parts:
            os.environ["PATH"] = ";".join(p for p in parts if p)
    except Exception:
        pass


def _winget_install(display_name: str, package_id: str) -> bool:
    """Install a package via winget. Returns True on success."""
    print(f"  Installing {display_name} via winget …")
    try:
        subprocess.check_call([
            "winget", "install", package_id,
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--silent",
        ])
        print(f"  {display_name} installed ✓")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(f"  Could not install {display_name} automatically.")
        print(f"  Install manually: winget install {package_id}")
        return False


def ensure_system_deps():
    """Install ffmpeg and Node.js via winget if they are missing."""
    need_ffmpeg = not shutil.which("ffmpeg")
    need_node   = not shutil.which("node")

    if not (need_ffmpeg or need_node):
        return

    if not shutil.which("winget"):
        if need_ffmpeg:
            print("  ffmpeg not found. Install from https://ffmpeg.org/download.html")
        if need_node:
            print("  Node.js not found. Install from https://nodejs.org")
        return

    if need_ffmpeg:
        _winget_install("ffmpeg", "Gyan.FFmpeg")
    if need_node:
        _winget_install("Node.js", "OpenJS.NodeJS")

    _refresh_windows_path()

    if need_ffmpeg and not shutil.which("ffmpeg"):
        print("  ffmpeg installed but not yet on PATH — restart the script if needed.")
    if need_node and not shutil.which("node"):
        print("  Node.js installed but not yet on PATH — restart the script if needed.")


def ensure_deps():
    pkgs = []
    try:
        import flask  # noqa: F401
    except ImportError:
        pkgs.append("flask")
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        pkgs.append("yt-dlp")
    if pkgs:
        print(f"  Installing Python packages: {', '.join(pkgs)} …")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet"] + pkgs
        )


ensure_system_deps()
ensure_deps()

import re
import uuid
import queue
import json
import time
import threading
import webbrowser

from flask import Flask, Response, request, jsonify
import yt_dlp

app = Flask(__name__)
jobs: dict = {}

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

# Quality options differ based on whether ffmpeg is present.
# Without ffmpeg, yt-dlp cannot merge separate video+audio streams,
# so we use "best" which picks a pre-merged single file.
if FFMPEG_AVAILABLE:
    QUALITY_OPTIONS = {
        "Best available":   "bestvideo+bestaudio/best",
        "1080p":            "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "720p":             "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "480p":             "bestvideo[height<=480]+bestaudio/best[height<=480]",
        "Audio only (MP3)": "bestaudio/best",
    }
else:
    # Single-stream formats only — no merging required
    QUALITY_OPTIONS = {
        "Best available":   "best",
        "720p or lower":    "best[height<=720]",
        "480p or lower":    "best[height<=480]",
        "Audio only (MP3)": "bestaudio/best",
    }

# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def build_html():
    ffmpeg_warn = "" if FFMPEG_AVAILABLE else (
        '<div class="ffmpeg-warn">'
        '⚠ ffmpeg not found — quality options limited to pre-merged streams. '
        '<a href="https://ffmpeg.org/download.html" target="_blank">Install ffmpeg</a> for 1080p and merging.'
        '</div>'
    )
    quality_opts = "\n".join(
        f'<option value="{v}">{k}</option>'
        for k, v in QUALITY_OPTIONS.items()
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>YT-DLP GUI</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: #111;
    color: #e8e8e8;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    padding: 24px;
  }}

  .card {{
    background: #1c1c1c;
    border: 1px solid #2e2e2e;
    border-radius: 8px;
    width: 100%;
    max-width: 520px;
    padding: 28px;
  }}

  h1 {{
    font-size: 17px;
    font-weight: 600;
    color: #fff;
    margin-bottom: 20px;
  }}

  .ffmpeg-warn {{
    background: #2a1f00;
    border: 1px solid #5a3e00;
    border-radius: 5px;
    color: #ffb347;
    font-size: 12px;
    padding: 9px 12px;
    margin-bottom: 18px;
    line-height: 1.5;
  }}
  .ffmpeg-warn a {{ color: #ffb347; }}

  label {{
    display: block;
    font-size: 12px;
    color: #888;
    margin-bottom: 5px;
  }}

  .field {{ margin-bottom: 14px; }}

  .row {{ display: flex; gap: 6px; }}

  input[type="text"], select {{
    width: 100%;
    background: #141414;
    border: 1px solid #333;
    border-radius: 5px;
    color: #e8e8e8;
    font-size: 13px;
    padding: 8px 11px;
    outline: none;
    transition: border-color .15s;
  }}
  input[type="text"]:focus, select:focus {{
    border-color: #555;
  }}
  input::placeholder {{ color: #444; }}
  select option {{ background: #1c1c1c; }}

  button {{
    background: #2a2a2a;
    border: 1px solid #3a3a3a;
    border-radius: 5px;
    color: #e8e8e8;
    font-size: 13px;
    padding: 8px 14px;
    cursor: pointer;
    white-space: nowrap;
    transition: background .15s, border-color .15s;
  }}
  button:hover:not(:disabled) {{
    background: #333;
    border-color: #555;
  }}
  button:disabled {{ opacity: .35; cursor: default; }}

  .btn-primary {{
    background: #1a56db;
    border-color: #1a56db;
    color: #fff;
    flex: 1;
  }}
  .btn-primary:hover:not(:disabled) {{
    background: #1e63f5;
    border-color: #1e63f5;
  }}
  .btn-danger {{
    background: transparent;
    border-color: #555;
    color: #aaa;
  }}
  .btn-danger:hover:not(:disabled) {{
    background: #3a1010;
    border-color: #c0392b;
    color: #e74c3c;
  }}

  .progress-wrap {{ margin: 18px 0 0; }}
  .progress-meta {{
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    color: #666;
    margin-bottom: 6px;
  }}
  .progress-meta .pct {{ color: #aaa; }}

  .progress-track {{
    height: 6px;
    background: #252525;
    border-radius: 3px;
    overflow: hidden;
  }}
  .progress-fill {{
    height: 100%;
    width: 0%;
    background: #1a56db;
    border-radius: 3px;
    transition: width .3s ease;
  }}

  .status {{
    font-size: 12px;
    color: #666;
    margin-top: 7px;
    min-height: 16px;
  }}
  .status.ok  {{ color: #27ae60; }}
  .status.err {{ color: #e74c3c; }}

  .actions {{ display: flex; gap: 8px; margin-top: 16px; }}

  .log-label {{
    font-size: 11px;
    color: #555;
    margin: 16px 0 5px;
    text-transform: uppercase;
    letter-spacing: .05em;
  }}
  .log {{
    height: 90px;
    overflow-y: auto;
    background: #141414;
    border: 1px solid #252525;
    border-radius: 5px;
    padding: 8px 10px;
    font-family: "Menlo", "Consolas", monospace;
    font-size: 11px;
    line-height: 1.6;
    color: #666;
  }}
  .log::-webkit-scrollbar {{ width: 4px; }}
  .log::-webkit-scrollbar-thumb {{ background: #333; border-radius: 2px; }}
  .log .ok  {{ color: #27ae60; }}
  .log .err {{ color: #e74c3c; }}
  .log .inf {{ color: #999; }}
</style>
</head>
<body>
<div class="card">
  <h1>YT-DLP GUI</h1>

  {ffmpeg_warn}

  <div class="field">
    <label>URL</label>
    <div class="row">
      <input type="text" id="url" placeholder="https://x.com/…  or  youtube.com/watch?v=…" />
      <button onclick="pasteUrl()">Paste</button>
    </div>
  </div>

  <div class="field">
    <label>Save to</label>
    <input type="text" id="folder" />
  </div>

  <div class="field">
    <label>Quality</label>
    <select id="quality">
      {quality_opts}
    </select>
  </div>

  <div class="progress-wrap">
    <div class="progress-meta">
      <span id="prog-label">Ready</span>
      <span class="pct" id="pct-label"></span>
    </div>
    <div class="progress-track">
      <div class="progress-fill" id="prog-fill"></div>
    </div>
    <div class="status" id="status"></div>
  </div>

  <div class="actions">
    <button class="btn-primary" id="dl-btn" onclick="startDownload()">Download</button>
    <button class="btn-danger" id="abort-btn" disabled onclick="cancelDownload()">Cancel</button>
  </div>

  <div class="log-label">Log</div>
  <div class="log" id="log"></div>
</div>

<script>
  fetch('/default-folder').then(r => r.json()).then(d => {{
    document.getElementById('folder').value = d.path;
  }}).catch(() => {{}});

  function pasteUrl() {{
    navigator.clipboard.readText()
      .then(t => {{ document.getElementById('url').value = t.trim(); }})
      .catch(() => {{ document.getElementById('url').focus(); }});
  }}

  function logLine(txt, cls) {{
    const box = document.getElementById('log');
    const d = document.createElement('div');
    if (cls) d.className = cls;
    d.textContent = txt;
    box.appendChild(d);
    box.scrollTop = box.scrollHeight;
  }}

  function setStatus(txt, cls) {{
    const el = document.getElementById('status');
    el.textContent = txt;
    el.className = 'status ' + (cls || '');
  }}

  function setPct(pct) {{
    document.getElementById('prog-fill').style.width = pct + '%';
    document.getElementById('pct-label').textContent = pct > 0 ? pct.toFixed(1) + '%' : '';
  }}

  let jobId = null, evtSrc = null;

  function startDownload() {{
    const url    = document.getElementById('url').value.trim();
    const folder = document.getElementById('folder').value.trim();
    const fmt    = document.getElementById('quality').value;
    if (!url) {{ setStatus('Enter a URL first.', 'err'); return; }}

    document.getElementById('dl-btn').disabled    = true;
    document.getElementById('abort-btn').disabled = false;
    document.getElementById('prog-label').textContent = 'Downloading…';
    setPct(0);
    setStatus('Starting…');
    logLine('URL: ' + url, 'inf');

    fetch('/download', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        url, folder, format: fmt,
        is_audio: fmt.includes('bestaudio') && !fmt.includes('bestvideo')
      }})
    }})
    .then(r => r.json())
    .then(d => {{
      jobId  = d.job_id;
      evtSrc = new EventSource('/events/' + jobId);
      evtSrc.onmessage = onEvent;
      evtSrc.onerror   = () => {{ setStatus('Connection lost.', 'err'); finish(false); }};
    }})
    .catch(e => {{ setStatus('Error: ' + e.message, 'err'); finish(false); }});
  }}

  function onEvent(e) {{
    const m = JSON.parse(e.data);
    if (m.type === 'ping') return;
    if (m.type === 'progress') {{
      if (m.pct != null) setPct(m.pct);
      const parts = [m.speed && m.speed, m.eta && 'ETA ' + m.eta, m.size].filter(Boolean).join('  ');
      if (parts) setStatus(parts);
    }} else if (m.type === 'log') {{
      logLine(m.msg, m.msg.startsWith('✓') ? 'ok' : 'inf');
    }} else if (m.type === 'done') {{
      setPct(100);
      document.getElementById('prog-label').textContent = 'Done';
      setStatus('Download complete.', 'ok');
      logLine('✓ Done', 'ok');
      finish(true);
    }} else if (m.type === 'error') {{
      setStatus(m.msg, 'err');
      logLine('✗ ' + m.msg, 'err');
      finish(false);
    }}
  }}

  function cancelDownload() {{
    if (jobId) fetch('/cancel/' + jobId, {{method: 'POST'}});
    logLine('Cancelled.', 'err');
    finish(false);
  }}

  function finish(ok) {{
    if (evtSrc) {{ evtSrc.close(); evtSrc = null; }}
    document.getElementById('dl-btn').disabled    = false;
    document.getElementById('abort-btn').disabled = true;
    if (!ok) document.getElementById('prog-label').textContent = 'Stopped';
  }}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return build_html()


@app.route("/default-folder")
def default_folder():
    return jsonify({"path": os.path.expanduser("~/Downloads")})


@app.route("/download", methods=["POST"])
def start_download():
    data = request.json
    job_id = str(uuid.uuid4())[:8]
    q: queue.Queue = queue.Queue()
    jobs[job_id] = {"queue": q, "cancelled": False}
    threading.Thread(target=download_worker, args=(job_id, data), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/events/<job_id>")
def events(job_id):
    def generate():
        job = jobs.get(job_id)
        if not job:
            yield 'data: {"type":"error","msg":"Job not found"}\n\n'
            return
        q = job["queue"]
        while True:
            try:
                msg = q.get(timeout=25)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("type") in ("done", "error"):
                    break
            except queue.Empty:
                yield 'data: {"type":"ping"}\n\n'

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/cancel/<job_id>", methods=["POST"])
def cancel(job_id):
    if job_id in jobs:
        jobs[job_id]["cancelled"] = True
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def download_worker(job_id: str, data: dict):
    job = jobs[job_id]
    q: queue.Queue = job["queue"]
    url      = data["url"]
    folder   = data.get("folder") or os.path.expanduser("~/Downloads")
    fmt      = data["format"]
    is_audio = data.get("is_audio", False)

    def strip_ansi(s: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", s or "").strip()

    def progress_hook(d):
        if job["cancelled"]:
            raise Exception("Cancelled")
        if d["status"] == "downloading":
            total      = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            pct = (downloaded / total * 100) if total else 0
            q.put({
                "type":  "progress",
                "pct":   round(pct, 1),
                "speed": strip_ansi(d.get("_speed_str", "")),
                "eta":   strip_ansi(d.get("_eta_str", "")),
                "size":  strip_ansi(
                    d.get("_total_bytes_str") or d.get("_total_bytes_estimate_str", "")
                ),
            })
        elif d["status"] == "finished":
            fname = os.path.basename(d.get("filename", ""))
            q.put({"type": "log", "msg": f"✓ {fname}"})
            q.put({"type": "progress", "pct": 95})

    outtmpl = os.path.join(folder, "%(uploader)s - %(title)s.%(ext)s")
    postprocessors = []
    if is_audio:
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        })

    ydl_opts = {
        "format":         fmt,
        "outtmpl":        outtmpl,
        "noplaylist":     True,
        "quiet":          True,
        "progress_hooks": [progress_hook],
        "postprocessors": postprocessors,
    }
    if FFMPEG_AVAILABLE:
        ydl_opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info     = ydl.extract_info(url, download=False)
            title    = info.get("title", "Unknown")
            uploader = info.get("uploader", "")
            q.put({"type": "log", "msg": f"→ {title}"})
            if uploader:
                q.put({"type": "log", "msg": f"   {uploader}"})
            if not job["cancelled"]:
                ydl.download([url])

        if not job["cancelled"]:
            q.put({"type": "done"})
        else:
            q.put({"type": "error", "msg": "Cancelled."})

    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc)
        if "Private" in msg:
            msg = "Private video — access denied."
        elif "Unsupported URL" in msg:
            msg = "URL not supported."
        elif "ffmpeg" in msg.lower():
            msg = "ffmpeg required for this quality. Install from ffmpeg.org or choose a lower quality."
        elif "429" in msg:
            msg = "Rate limited — try again in a minute."
        else:
            msg = msg[:150]
        q.put({"type": "error", "msg": msg})
    except Exception as exc:
        q.put({"type": "error", "msg": str(exc)[:150]})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    PORT = 7331

    ffmpeg_status = "ffmpeg: found ✓" if FFMPEG_AVAILABLE else "ffmpeg: not found (limited quality options)"
    print()
    print(f"  YT-DLP GUI  —  http://localhost:{PORT}")
    print(f"  {ffmpeg_status}")
    print(f"  Ctrl+C to stop")
    print()

    threading.Thread(
        target=lambda: (time.sleep(1.2), webbrowser.open(f"http://localhost:{PORT}")),
        daemon=True
    ).start()

    app.run(port=PORT, debug=False, threaded=True)

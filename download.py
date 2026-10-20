import csv
import json
import subprocess
import sys
from pathlib import Path

# Ensure Windows terminal handles Unicode characters
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
RAW.mkdir(exist_ok=True)

# Try importing gsheet module
try:
    import gsheet
except ImportError:
    gsheet = None

# Collect links from links.txt and from the Google Sheet
links_file = ROOT / "links.txt"
links = []

if links_file.exists():
    links.extend([l.strip() for l in links_file.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")])

if gsheet:
    try:
        for sl in gsheet.get_links_from_sheet():
            if sl not in links:
                links.append(sl)
    except Exception as e:
        print(f"[Google Sheet] Note: Could not read existing links from sheet: {e}")

if not links:
    print("No links found in links.txt or Google Sheet.")
    exit(0)

FIELDNAMES = ["id", "platform", "link", "title", "channel", "duration_min", "topic", "code_switching"]
rows = []

for url in links:
    print(f"\nProcessing: {url}")
    is_tiktok = "tiktok.com" in url.lower()
    platform = "TikTok" if is_tiktok else "YouTube"

    # Platform-specific extractor arguments
    extractor_args = []
    if not is_tiktok:
        # YouTube Android client bypasses bot blocks
        extractor_args = ["--extractor-args", "youtube:player_client=android"]

    # 1. Fetch metadata
    meta = subprocess.run(
        ["yt-dlp", *extractor_args, "--encoding", "utf-8", "--dump-json", "--no-playlist", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if meta.returncode != 0:
        print(f"FAILED (info from {platform}):", url)
        print(meta.stderr[-500:])
        continue

    info = json.loads(meta.stdout)
    vid = str(info.get("id", ""))
    duration_sec = info.get("duration") or 0
    title = info.get("title", "")
    channel = info.get("channel") or info.get("uploader", "")

    # 2. Download + convert to 16kHz mono wav if not already present
    wav_target = RAW / f"{vid}.wav"
    if wav_target.exists():
        print(f"[OK] Raw audio already exists: {wav_target.name}")
    else:
        print(f"Downloading [{platform}] and converting to 16kHz mono WAV: {vid}...")
        dl = subprocess.run([
            "yt-dlp", *extractor_args,
            "-x", "--audio-format", "wav",
            "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1",
            "--no-playlist",
            "-o", str(RAW / f"{vid}.%(ext)s"),
            url
        ])
        if dl.returncode != 0:
            print("FAILED (download):", url)
            continue
        print(f"[OK] Downloaded: {wav_target.name}")

    # 3. Add / sync to Google Sheet directly!
    sheet_id = None
    if gsheet:
        try:
            sheet_id = gsheet.add_video_to_sheet(url, title, duration_sec, platform=platform)
        except Exception as e:
            print(f"[Google Sheet] Error syncing to sheet: {e}")

    # 4. Also keep local tracking.csv for offline backup
    rows.append({
        "id": sheet_id or vid,
        "platform": platform,
        "link": url,
        "title": title,
        "channel": channel,
        "duration_min": round(duration_sec / 60, 2),
        "topic": "",
        "code_switching": "",
    })

# Update local backup tracking.csv
out = ROOT / "tracking.csv"
is_new_or_empty = not out.exists() or out.stat().st_size == 0

if rows:
    with open(out, "w" if is_new_or_empty else "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if is_new_or_empty:
            w.writeheader()
        w.writerows(rows)
    print(f"\n[DONE] Finished processing links. tracking.csv and Google Sheet updated!")
else:
    print("\nNo rows downloaded or processed.")
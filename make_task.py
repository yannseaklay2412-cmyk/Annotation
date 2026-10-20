import csv
import json
import re
import sys
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
METADATA_FILE = ROOT / "chunks_metadata.csv"
TRACKING_FILE = ROOT / "tracking.csv"
TASKS_FILE = ROOT / "tasks.json"
SUSPICIOUS_FILE = ROOT / "suspicious_chunks.csv"
RAW_DIR = ROOT / "raw"
LABEL_CONFIG_FILE = ROOT / "label_studio_config.xml"
LABEL_STUDIO_DB = Path.home() / "AppData" / "Local" / "label-studio" / "label-studio" / "label_studio.sqlite3"

# Audio URL prefix for Label Studio audio player
AUDIO_PREFIX = "http://localhost:8001/chunks/"


def clean_text(text: str) -> str:
    """Removes HTML/VTT tags and noise tokens while preserving Khmer script and English words."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_subtitle_words(video_id: str) -> List[Dict[str, Any]]:
    """
    Extracts timed words for a given video ID from available subtitle files (.json3 or .vtt).
    Preserves Khmer and English script without altering characters.
    """
    candidates = [
        RAW_DIR / f"{video_id}_sub.km-orig.json3",
        RAW_DIR / f"{video_id}_sub.km.json3",
        RAW_DIR / f"{video_id}.km-orig.json3",
        ROOT / "test_sub.km.json3",
    ]

    for p in candidates:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                events = data.get("events", [])
                timed_words = []
                for ev in events:
                    ev_start = ev.get("tStartMs", 0) / 1000.0
                    ev_dur = ev.get("dDurationMs", 0) / 1000.0
                    ev_end = ev_start + ev_dur
                    segs = ev.get("segs", [])
                    has_offsets = any(s.get("tOffsetMs") is not None for s in segs)

                    if has_offsets:
                        for s in segs:
                            off = s.get("tOffsetMs", 0)
                            w_start = ev_start + (off / 1000.0)
                            txt = clean_text(s.get("utf8", ""))
                            if txt:
                                for w in txt.split():
                                    timed_words.append({
                                        "word": w,
                                        "start": w_start,
                                        "end": min(ev_end, w_start + 1.2)
                                    })
                    else:
                        full_text = clean_text("".join(s.get("utf8", "") for s in segs))
                        if full_text:
                            words = full_text.split()
                            dur_per_word = ev_dur / max(1, len(words))
                            for i, w in enumerate(words):
                                w_start = ev_start + i * dur_per_word
                                timed_words.append({
                                    "word": w,
                                    "start": w_start,
                                    "end": w_start + dur_per_word
                                })
                if timed_words:
                    return timed_words
            except Exception as e:
                print(f"[!] Warning reading {p.name}: {e}")

    # Fallback to VTT if json3 is not found
    vtt_candidates = [
        RAW_DIR / f"{video_id}.km-orig.vtt",
        RAW_DIR / f"{video_id}.vtt",
    ]
    for p in vtt_candidates:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
                cue_pattern = re.compile(
                    r'(\d+:\d+:\d+\.\d+)\s+-->\s+(\d+:\d+:\d+\.\d+)[^\n]*\n(.*?)(?=\n\n|\Z)',
                    re.DOTALL
                )
                timed_words = []
                for m in cue_pattern.finditer(content):
                    parts = m.group(1).split(":")
                    c_start = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                    lines = [l.strip() for l in m.group(3).split("\n") if l.strip()]
                    for l in lines:
                        if l.startswith("align:") or l.startswith("position:"):
                            continue
                        clean_line = clean_text(l)
                        for w in clean_line.split():
                            timed_words.append({"word": w, "start": c_start, "end": c_start + 1.5})
                if timed_words:
                    return timed_words
            except Exception as e:
                print(f"[!] Warning reading {p.name}: {e}")

    return []


def get_chunk_transcript(start_sec: float, end_sec: float, timed_words: List[Dict[str, Any]], fallback: str = "") -> str:
    """
    Extracts only words spoken inside that exact audio chunk [start_sec, end_sec].
    Keeps Khmer script and English words together in the same string without altering them.
    """
    if not timed_words:
        return fallback.strip()

    selected = [
        w["word"] for w in timed_words
        if (start_sec <= w["start"] <= end_sec) or 
           (w["start"] < start_sec and w["end"] > start_sec + 0.3)
    ]

    # Deduplicate consecutive identical words
    deduped = []
    for w in selected:
        if not deduped or deduped[-1] != w:
            deduped.append(w)

    transcript = " ".join(deduped).strip()
    return transcript if transcript else fallback.strip()


def load_tracking_metadata() -> Dict[str, Dict[str, str]]:
    """Loads source tracking metadata from tracking.csv (platform, domain/topic, title, link)."""
    mapping = {}
    if not TRACKING_FILE.exists():
        return mapping

    try:
        with open(TRACKING_FILE, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                vid = row.get("id", "").strip()
                if vid:
                    mapping[vid] = row
    except Exception as e:
        print(f"[!] Warning reading {TRACKING_FILE.name}: {e}")

    return mapping


def sync_to_label_studio_db(tasks: List[Dict[str, Any]], project_id: int = 2):
    """
    Directly updates or inserts tasks and syncs XML config into Label Studio's local SQLite database
    so the user does not have to re-upload manually.
    """
    if not LABEL_STUDIO_DB.exists():
        return

    try:
        conn = sqlite3.connect(LABEL_STUDIO_DB)
        cur = conn.cursor()

        # Update Project label_config from label_studio_config.xml if available
        if LABEL_CONFIG_FILE.exists():
            xml_content = LABEL_CONFIG_FILE.read_text(encoding="utf-8")
            cur.execute("UPDATE project SET label_config = ? WHERE id = ?", (xml_content, project_id))
            print(f"[Label Studio DB] Synced latest label_studio_config.xml into Project {project_id}.")

        # Check existing tasks for project
        cur.execute("SELECT id FROM task WHERE project_id = ? ORDER BY id ASC", (project_id,))
        existing_task_ids = [r[0] for r in cur.fetchall()]

        if len(existing_task_ids) == len(tasks):
            # Update existing tasks in place
            for task_id, t in zip(existing_task_ids, tasks):
                data_json = json.dumps(t["data"], ensure_ascii=False)
                cur.execute("UPDATE task SET data = ? WHERE id = ?", (data_json, task_id))
            conn.commit()
            print(f"[Label Studio DB] Updated {len(tasks)} tasks in Project {project_id} database directly.")
        else:
            # Clear old tasks and insert new tasks cleanly
            cur.execute("DELETE FROM task_completion WHERE project_id = ?", (project_id,))
            cur.execute("DELETE FROM prediction WHERE project_id = ?", (project_id,))
            cur.execute("DELETE FROM task WHERE project_id = ?", (project_id,))
            import datetime
            now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
            for idx, t in enumerate(tasks, start=1):
                data_json = json.dumps(t["data"], ensure_ascii=False)
                cur.execute(
                    """
                    INSERT INTO task (data, created_at, updated_at, is_labeled, project_id, overlap, inner_id, total_annotations, cancelled_annotations, total_predictions, comment_count, unresolved_comment_count)
                    VALUES (?, ?, ?, 0, ?, 1, ?, 0, 0, 0, 0, 0)
                    """,
                    (data_json, now_iso, now_iso, project_id, idx)
                )
            conn.commit()
            print(f"[Label Studio DB] Replaced with {len(tasks)} tasks in Project {project_id} database directly.")

        conn.close()
    except Exception as e:
        print(f"[Label Studio DB] Note: Could not auto-sync directly to DB: {e}")


def main():
    if not METADATA_FILE.exists():
        print(f"Error: {METADATA_FILE} not found. Please run cut.py first.")
        return

    tracking_map = load_tracking_metadata()
    timed_words_cache = {}
    tasks = []
    suspicious_chunks = []

    with open(METADATA_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            filename = row["file_name"]
            video_id = row.get("video_id", "")
            chunk_id = row.get("chunk_id", filename.replace(".wav", ""))
            start_sec = float(row.get("start_sec", 0.0))
            end_sec = float(row.get("end_sec", 0.0))
            duration = float(row.get("duration_sec", 0.0))
            fallback_text = row.get("draft_text", "")

            # Metadata lookup from tracking.csv
            trk = tracking_map.get(video_id, {})
            platform = trk.get("platform", "YouTube")
            domain = trk.get("topic", "Education") or "Education"
            title = trk.get("title", "")
            source_url = trk.get("link", f"https://youtu.be/{video_id}" if video_id else "")

            # Load and cache subtitle word timestamps for this video
            if video_id not in timed_words_cache:
                timed_words_cache[video_id] = load_subtitle_words(video_id)

            timed_words = timed_words_cache[video_id]

            # 1. Use the exact ~10-word code-switching snippet from draft_text
            if fallback_text and fallback_text.strip():
                transcript = fallback_text.strip()
            else:
                transcript = get_chunk_transcript(start_sec, end_sec, timed_words, fallback_text)

            # 2. Format task JSON with rich metadata for Capstone 1 annotation
            task = {
                "data": {
                    "audio": f"{AUDIO_PREFIX}{filename}",
                    "transcript": transcript,
                    "chunk_id": chunk_id,
                    "platform": platform,
                    "domain": domain,
                    "title": title,
                    "source_url": source_url,
                    "duration": round(duration, 2)
                }
            }
            tasks.append(task)

            # 3. Check: if chunk > 3.0s but transcript has < 3 words -> log to suspicious_chunks.csv
            words = transcript.strip().split() if transcript.strip() else []
            word_count = len(words)

            if duration > 3.0 and word_count < 3:
                suspicious_chunks.append({
                    "chunk_filename": filename,
                    "duration": round(duration, 3),
                    "word_count": word_count,
                    "transcript": transcript
                })

    # Save tasks.json
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2, ensure_ascii=False)

    print(f"\n[DONE] Generated {len(tasks)} tasks in {TASKS_FILE.name}")
    print(f"       Task JSON Format: {{\"data\": {{\"audio\": \"...\", \"transcript\": \"...\", \"chunk_id\": \"...\", \"platform\": \"...\"}}}}")

    # Save suspicious_chunks.csv
    with open(SUSPICIOUS_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["chunk_filename", "duration", "word_count", "transcript"])
        writer.writeheader()
        writer.writerows(suspicious_chunks)

    print(f"[CHECK] Logged {len(suspicious_chunks)} suspicious chunk(s) (duration > 3s, words < 3) to {SUSPICIOUS_FILE.name}")
    if suspicious_chunks:
        print("\n--- Suspicious Chunks Sample ---")
        for sc in suspicious_chunks[:5]:
            print(f"  * {sc['chunk_filename']}: {sc['duration']}s, {sc['word_count']} words -> \"{sc['transcript']}\"")
        if len(suspicious_chunks) > 5:
            print(f"  ... and {len(suspicious_chunks) - 5} more.")

    # Auto-sync to Label Studio database
    sync_to_label_studio_db(tasks, project_id=2)

    print("\nAll tasks are ready! You can now view them in Label Studio or refresh your browser.")


if __name__ == "__main__":
    main()

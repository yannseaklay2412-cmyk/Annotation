import os
import re
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure Windows terminal prints Khmer and English properly without crashing
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "raw"
CHUNKS_DIR = ROOT / "chunks"
CHUNKS_DIR.mkdir(exist_ok=True)
METADATA_FILE = ROOT / "chunks_metadata.csv"
LINKS_FILE = ROOT / "links.txt"

# Try importing gsheet module for automatic dashboard updating
try:
    import gsheet
except ImportError:
    gsheet = None

# Configuration: Short chunks around ~10 words (2.0s to 4.5s)
WHISPER_MODEL = "base"
MIN_DURATION_SEC = 2.0
MAX_DURATION_SEC = 4.5
TARGET_WORDS = 10
MAX_SNIPPET_CHARS = 55   # Around ~10 words in Khmer/English
PRE_ROLL_SEC = 0.25      # Clean boundary padding
POST_ROLL_SEC = 0.25     # Clean boundary padding

FIELDNAMES = [
    "chunk_id",
    "video_id",
    "file_name",
    "start_sec",
    "end_sec",
    "duration_sec",
    "draft_text",
    "has_code_switching",
]


def clean_text(text: str) -> str:
    """Removes noise tokens like [applause] and extra whitespace."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_code_switching(text: str) -> bool:
    """
    Returns True if the text contains BOTH:
    1. Khmer script (Unicode range U+1780 to U+17FF)
    2. English words (2 or more Latin letters)
    """
    clean = clean_text(text)
    has_khmer = bool(re.search(r"[\u1780-\u17FF]", clean))
    has_english = bool(re.search(r"[a-zA-Z]{2,}", clean))
    return has_khmer and has_english


def get_short_snippet(text: str, max_chars: int = MAX_SNIPPET_CHARS) -> str:
    """Keeps the text centered on code-switching while preserving Khmer script and English words."""
    text = clean_text(text)
    words = text.split()
    if len(words) > 15:
        return " ".join(words[:15])
    return text


def slice_audio_ffmpeg(input_wav: Path, output_wav: Path, start_sec: float, duration_sec: float):
    """
    Fast audio slicing using ffmpeg at 16kHz mono PCM.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{start_sec:.3f}",
        "-t", f"{duration_sec:.3f}",
        "-i", str(input_wav),
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(output_wav),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def fetch_youtube_subtitles_json3(video_id: str) -> Optional[Path]:
    """Attempts to download YouTube auto-subtitles in json3 format."""
    out_prefix = str(RAW_DIR / f"{video_id}_sub")
    candidates = list(RAW_DIR.glob(f"{video_id}*.json3"))
    if candidates:
        return candidates[0]

    url = f"https://youtu.be/{video_id}"
    cmd = [
        "yt-dlp",
        "--extractor-args", "youtube:player_client=android",
        "--write-auto-sub",
        "--sub-lang", "km,km-orig",
        "--sub-format", "json3",
        "--skip-download",
        "-o", out_prefix,
        url,
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        pass

    candidates = list(RAW_DIR.glob(f"{video_id}*.json3"))
    return candidates[0] if candidates else None


def snap_clean_boundary(text: str, start_idx: int, end_idx: int) -> tuple[int, int]:
    """Snaps start and end character positions to whitespace and preserves Khmer syllable clusters."""
    left_space = text.rfind(" ", max(0, start_idx - 8), min(len(text), start_idx + 8))
    if left_space != -1 and left_space < end_idx - 10:
        start_idx = left_space + 1

    right_space = text.find(" ", max(start_idx + 10, end_idx - 8), min(len(text), end_idx + 8))
    if right_space != -1 and right_space > start_idx + 10:
        end_idx = right_space

    while start_idx > 0 and ('\u17B6' <= text[start_idx] <= '\u17D3' or text[start_idx - 1] == '\u17D2'):
        start_idx -= 1

    while end_idx < len(text) and ('\u17B6' <= text[end_idx] <= '\u17D3' or (end_idx > 0 and text[end_idx - 1] == '\u17D2')):
        end_idx += 1

    return start_idx, end_idx


def extract_chunks_from_json3(json3_file: Path) -> List[Dict[str, Any]]:
    """
    Extracts tight, ~10-word code-switching segments (~2.2s to 4.5s) centered
    strictly on the English-Khmer transition, rather than long multi-sentence monologues.
    """
    try:
        with open(json3_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading {json3_file}: {e}")
        return []

    events = data.get("events", [])
    raw_chunks = []

    for ev in events:
        segs = ev.get("segs", [])
        raw_text = "".join(s.get("utf8", "") for s in segs).replace("\n", " ")
        raw_text = clean_text(raw_text)

        if not is_code_switching(raw_text):
            continue

        t_start = ev.get("tStartMs", 0) / 1000.0
        d_dur = ev.get("dDurationMs", 0) / 1000.0
        total_len = len(raw_text)
        if total_len == 0 or d_dur <= 0:
            continue

        # Find English word clusters (at least 2 letters)
        en_matches = list(re.finditer(r"[a-zA-Z0-9\-_/]+(?:\s+[a-zA-Z0-9\-_/]+)*", raw_text))
        valid_en_matches = [m for m in en_matches if re.search(r"[a-zA-Z]{2,}", m.group(0))]

        if not valid_en_matches:
            continue

        for en in valid_en_matches:
            en_start_char = en.start()
            en_end_char = en.end()
            en_text = en.group(0).strip()
            en_words_count = len(en_text.split())

            # Target ~10 words total. The rest will be Khmer words (~6 chars per word)
            target_khmer_words = max(3, 10 - en_words_count)
            target_khmer_chars = target_khmer_words * 6

            # Center window around English occurrence
            if en_start_char < 15:
                snippet_start = 0
                snippet_end = min(total_len, en_end_char + target_khmer_chars + 12)
            elif total_len - en_end_char < 15:
                snippet_start = max(0, en_start_char - (target_khmer_chars + 12))
                snippet_end = total_len
            else:
                half_chars = (target_khmer_chars + 12) // 2
                snippet_start = max(0, en_start_char - half_chars)
                snippet_end = min(total_len, en_end_char + half_chars)

            snippet_start, snippet_end = snap_clean_boundary(raw_text, snippet_start, snippet_end)
            snippet_text = raw_text[snippet_start:snippet_end].strip()

            if len(snippet_text) < 4 or not is_code_switching(snippet_text):
                continue

            # Calculate proportional audio timestamps
            char_rate = d_dur / total_len
            slice_start = t_start + (snippet_start * char_rate) - PRE_ROLL_SEC
            slice_end = t_start + (snippet_end * char_rate) + POST_ROLL_SEC
            slice_start = max(0.0, slice_start)
            slice_dur = slice_end - slice_start

            # Enforce strict ~10 words duration bounds: 2.0s <= dur <= 4.5s
            if slice_dur < MIN_DURATION_SEC:
                diff = MIN_DURATION_SEC - slice_dur
                slice_start = max(0.0, slice_start - diff / 2)
                slice_end = slice_end + diff / 2
                slice_dur = MIN_DURATION_SEC
            elif slice_dur > MAX_DURATION_SEC:
                slice_end = slice_start + MAX_DURATION_SEC
                slice_dur = MAX_DURATION_SEC

            raw_chunks.append({
                "start": slice_start,
                "end": slice_end,
                "duration": slice_dur,
                "text": snippet_text,
            })

    # Filter out heavy overlapping segments so annotators don't hear duplicated audio
    non_overlapping = []
    last_end = 0.0
    for c in raw_chunks:
        if c["start"] >= last_end - 0.7:
            non_overlapping.append(c)
            last_end = c["end"]

    return non_overlapping


def transcribe_with_whisper(wav_path: Path) -> List[Dict[str, Any]]:
    """Fallback transcription using OpenAI Whisper with bilingual code-switching prompt."""
    try:
        import whisper
    except ImportError:
        print("Whisper is not installed. Run: pip install openai-whisper")
        return []

    print(f"Loading Whisper model ({WHISPER_MODEL})...")
    model = whisper.load_model(WHISPER_MODEL)

    prompt = (
        "Khmer and English code-switching conversation. Words like school, university, degree, "
        "computer, IT, online, program, course, teacher, student, team, business, marketing, project, tech."
    )

    result = model.transcribe(
        str(wav_path),
        language="km",
        initial_prompt=prompt,
        temperature=0.0,
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
        verbose=True,
        fp16=False,
    )

    segments = result.get("segments", [])
    chunks = []
    for s in segments:
        txt = clean_text(s.get("text", ""))
        start = s.get("start", 0.0)
        end = s.get("end", 0.0)
        dur = end - start
        if MIN_DURATION_SEC <= dur <= MAX_DURATION_SEC and is_code_switching(txt):
            snippet = get_short_snippet(txt)
            chunks.append({"start": start, "end": end, "duration": dur, "text": snippet})
    return chunks


def get_target_videos() -> List[Path]:
    """Finds all audio files in raw/ matching links.txt or existing raw/*.wav."""
    if LINKS_FILE.exists():
        links = [l.strip() for l in LINKS_FILE.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
        target_ids = []
        for l in links:
            if "youtu.be/" in l:
                vid = l.split("youtu.be/")[1].split("?")[0].split("&")[0]
                target_ids.append(vid)
            elif "v=" in l:
                vid = l.split("v=")[1].split("&")[0]
                target_ids.append(vid)

        target_wavs = [RAW_DIR / f"{vid}.wav" for vid in target_ids if (RAW_DIR / f"{vid}.wav").exists()]
        if target_wavs:
            return target_wavs

    return sorted(RAW_DIR.glob("*.wav"))


def main():
    if not RAW_DIR.exists():
        print(f"Error: {RAW_DIR} does not exist.")
        return

    wav_files = get_target_videos()
    if not wav_files:
        print(f"No matching .wav files found in {RAW_DIR}.")
        return

    print("\n" + "=" * 60)
    print("      KHMER-ENGLISH SHORT CODE-SWITCHING CUTTER (~10 words)")
    print(f"      Target Duration: {MIN_DURATION_SEC}s - {MAX_DURATION_SEC}s per chunk")
    print(f"      Found {len(wav_files)} audio file(s) to process")
    print("=" * 60 + "\n")

    # Load existing metadata so we can replace chunks for this video cleanly
    existing_rows = []
    if METADATA_FILE.exists() and METADATA_FILE.stat().st_size > 0:
        with open(METADATA_FILE, "r", encoding="utf-8-sig") as f:
            existing_rows = list(csv.DictReader(f))

    total_chunks_saved = 0

    for wav_path in wav_files:
        video_id = wav_path.stem
        print(f"\n---> Processing: {wav_path.name}")

        # Remove old chunks for this specific video from chunks/ folder
        for old_chunk in CHUNKS_DIR.glob(f"{video_id}_*.wav"):
            try:
                old_chunk.unlink()
            except Exception:
                pass

        # Remove old rows for this video from existing metadata
        existing_rows = [r for r in existing_rows if r.get("video_id") != video_id]

        # 1. Check for / download json3 subtitles
        json3_file = fetch_youtube_subtitles_json3(video_id)
        segments = []
        if json3_file and json3_file.exists():
            print(f"[*] Found YouTube subtitles: {json3_file.name}")
            print(f"    Extracting short code-switching phrases (~10 words / 2-7.5s)...")
            segments = extract_chunks_from_json3(json3_file)

        # 2. Fallback to Whisper if no subtitles available
        if not segments:
            print("[!] No subtitle cues found. Running Whisper fallback...")
            segments = transcribe_with_whisper(wav_path)

        print(f"--> Found {len(segments)} short code-switching segments for {video_id}.")

        cs_count = 0
        video_useful_sec = 0.0
        new_video_rows = []

        for seg in segments:
            text = seg["text"].strip()
            start = seg["start"]
            end = seg["end"]
            duration = end - start

            cs_count += 1
            start_cut = max(0.0, start)
            end_cut = end
            duration_cut = end_cut - start_cut

            video_useful_sec += duration_cut
            total_chunks_saved += 1
            chunk_id = f"{video_id}_{cs_count:04d}"
            chunk_filename = f"{chunk_id}.wav"
            chunk_path = CHUNKS_DIR / chunk_filename

            # Slice immediately with ffmpeg
            slice_audio_ffmpeg(wav_path, chunk_path, start_cut, duration_cut)

            row = {
                "chunk_id": chunk_id,
                "video_id": video_id,
                "file_name": chunk_filename,
                "start_sec": round(start_cut, 3),
                "end_sec": round(end_cut, 3),
                "duration_sec": round(duration_cut, 3),
                "draft_text": text,
                "has_code_switching": "yes",
            }
            new_video_rows.append(row)

            print(f"  [CHUNK #{cs_count:02d}] {chunk_filename} ({duration_cut:.1f}s) -> {text}")
            sys.stdout.flush()

        # Update metadata CSV
        existing_rows.extend(new_video_rows)
        with open(METADATA_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(existing_rows)

        useful_min = video_useful_sec / 60
        print(f"\n[OK] Finished {wav_path.name}:")
        print(f"     Saved: {cs_count} short chunks")
        print(f"     Useful Speech: {video_useful_sec:.1f}s (~{useful_min:.2f} mins)")

        # Sync Useful Duration to Google Sheet!
        if gsheet:
            try:
                gsheet.update_useful_duration(video_id, video_useful_sec)
            except Exception as e:
                print(f"[Google Sheet] Note: Could not update duration: {e}")

    print("\n" + "=" * 60)
    print(f"[ALL COMPLETE] Extracted {total_chunks_saved} short code-switching chunks.")
    print(f"Audio files saved to: {CHUNKS_DIR}")
    print(f"Metadata saved to:    {METADATA_FILE}")
    print("Next step: run 'python make_task.py' to regenerate tasks.json.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()

import csv
import json
import re
import sys
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Tuple

# Ensure Windows terminal handles Unicode
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
LABEL_STUDIO_DB = Path.home() / "AppData" / "Local" / "label-studio" / "label-studio" / "label_studio.sqlite3"
EXPORTED_JSON = ROOT / "export.json"
OUTPUT_JSON = ROOT / "annotated_dataset.json"
OUTPUT_CSV = ROOT / "annotated_dataset.csv"


def auto_tag_token(token: str) -> List[Tuple[str, str]]:
    """
    Classifies a token as [km], [en], [num], or [punct].
    If a token combines both Khmer and English (e.g. missing space like 'រៀនcode'),
    it splits them by script boundary into separate [km] and [en] tokens.
    """
    clean_tok = re.sub(r"[^\w\u1780-\u17FF]", "", token)
    if not clean_tok:
        return [(token, "[punct]")]

    has_khmer = bool(re.search(r"[\u1780-\u17FF]", clean_tok))
    has_english = bool(re.search(r"[a-zA-Z]", clean_tok))

    if has_khmer and has_english:
        sub_tokens = re.findall(r"[\u1780-\u17FF]+|[a-zA-Z]+|\d+|[^\w\s\u1780-\u17FF]+", token)
        results = []
        for st in sub_tokens:
            results.extend(auto_tag_token(st))
        return results
    elif has_english:
        return [(token, "[en]")]
    elif has_khmer:
        return [(token, "[km]")]
    elif clean_tok.isdigit():
        return [(token, "[num]")]
    else:
        return [(token, "[other]")]


def tag_sentence(sentence: str) -> Tuple[str, List[Dict[str, str]]]:
    """
    Takes raw sentence and produces:
    1. Formatted tagged text: "ការពារ [km] traditional [en] clothes [en]"
    2. Structured list: [{"word": "ការពារ", "tag": "km"}, ...]
    """
    raw_tokens = sentence.split()
    formatted_parts = []
    token_records = []

    for tok in raw_tokens:
        for word, tag in auto_tag_token(tok):
            formatted_parts.append(f"{word} {tag}")
            token_records.append({"word": word, "tag": tag.replace("[", "").replace("]", "")})

    return " ".join(formatted_parts), token_records


def fetch_annotations_from_db(project_id: int = 2) -> List[Dict[str, Any]]:
    """Loads annotations directly from Label Studio SQLite database."""
    if not LABEL_STUDIO_DB.exists():
        return []

    records = []
    try:
        conn = sqlite3.connect(LABEL_STUDIO_DB)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT t.id, t.data, tc.result, tc.created_at
            FROM task t
            INNER JOIN task_completion tc ON t.id = tc.task_id
            WHERE t.project_id = ? AND tc.was_cancelled = 0
            """,
            (project_id,)
        )
        for task_id, task_data_json, result_json, created_at in cur.fetchall():
            task_data = json.loads(task_data_json) if task_data_json else {}
            results = json.loads(result_json) if result_json else []
            records.append({
                "task_id": task_id,
                "data": task_data,
                "annotations": results,
                "created_at": created_at
            })
        conn.close()
    except Exception as e:
        print(f"[!] Warning reading SQLite DB: {e}")

    return records


def parse_annotation_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Parses a single Label Studio task + annotation into a standardized dataset record."""
    task_data = item.get("data", {})
    annotations = item.get("annotations", [])
    if isinstance(annotations, list) and annotations and "result" in annotations[0]:
        results = annotations[0]["result"]
    else:
        results = annotations

    # Default fields from task metadata
    chunk_id = task_data.get("chunk_id", "")
    platform = task_data.get("platform", "YouTube")
    domain = task_data.get("domain", "")
    video_id = task_data.get("video_id", "")
    source_url = task_data.get("source_url", "")
    duration = task_data.get("duration", 0.0)

    # Annotated values
    transcript = task_data.get("transcript", "")
    language_combo = "Khmer-English"
    quality_flags = []
    cs_boundaries = []

    for res in results:
        from_name = res.get("from_name", "")
        res_type = res.get("type", "")
        value = res.get("value", {})

        if from_name == "transcription" and "text" in value:
            # Verified human transcription
            transcript = "\n".join(value["text"]).strip()
        elif from_name == "language_combo" and "choices" in value:
            language_combo = value["choices"][0]
        elif from_name == "quality_flags" and "choices" in value:
            quality_flags = value["choices"]
        elif from_name == "domain" and "choices" in value:
            domain = value["choices"][0]
        elif from_name == "audio_regions" and res_type == "labels":
            start_time = round(value.get("start", 0.0), 3)
            end_time = round(value.get("end", 0.0), 3)
            labels = value.get("labels", [])
            cs_boundaries.append({
                "label": labels[0] if labels else "Code-Switching",
                "start_sec": start_time,
                "end_sec": end_time,
                "duration_sec": round(end_time - start_time, 3)
            })

    # Word-level language tagging
    tagged_text, token_list = tag_sentence(transcript)
    has_cs = any(t["tag"] == "en" for t in token_list) and any(t["tag"] == "km" for t in token_list)

    return {
        "chunk_id": chunk_id,
        "video_id": video_id,
        "platform": platform,
        "domain": domain,
        "source_url": source_url,
        "duration_sec": duration,
        "raw_transcript": transcript,
        "tagged_transcript": tagged_text,
        "token_count": len(token_list),
        "tokens": token_list,
        "language_combo": language_combo,
        "has_code_switching": "yes" if has_cs else "no",
        "cs_boundaries": cs_boundaries,
        "quality_flags": "; ".join(quality_flags),
        "is_uncertain": "yes" if "Uncertain Language Decision (Review Needed)" in quality_flags else "no",
        "is_unintelligible": "yes" if "Unintelligible" in "; ".join(quality_flags) else "no"
    }


def main():
    print("=" * 60)
    print("Khmer-English Code-Switching Annotation Exporter & Tagger")
    print("=" * 60)

    records_raw = []

    # 1. Check if user exported JSON file manually
    if EXPORTED_JSON.exists():
        print(f"[Source] Found manual export: {EXPORTED_JSON.name}")
        try:
            with open(EXPORTED_JSON, "r", encoding="utf-8") as f:
                records_raw = json.load(f)
        except Exception as e:
            print(f"[!] Error reading {EXPORTED_JSON.name}: {e}")

    # 2. Otherwise load directly from SQLite DB
    if not records_raw:
        print("[Source] Reading completed annotations from Label Studio SQLite DB...")
        records_raw = fetch_annotations_from_db(project_id=2)

    if not records_raw:
        print("\nNo completed annotations found yet.")
        print("Tip: After you finish annotating tasks in Label Studio, run this script to export & tag tokens!")
        return

    processed = [parse_annotation_item(r) for r in records_raw]
    print(f"\n[OK] Processed {len(processed)} annotation records.")

    # Save to JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(processed, f, indent=2, ensure_ascii=False)
    print(f"[Saved] Standardized JSON dataset -> {OUTPUT_JSON.name}")

    # Save to CSV
    csv_fields = [
        "chunk_id", "video_id", "platform", "domain", "duration_sec",
        "raw_transcript", "tagged_transcript", "language_combo",
        "has_code_switching", "quality_flags", "is_uncertain", "source_url"
    ]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(processed)
    print(f"[Saved] Tabular CSV dataset -> {OUTPUT_CSV.name}")

    # Print a sample
    sample = processed[0]
    print("\n--- Sample Output ---")
    print(f"Chunk ID:          {sample['chunk_id']}")
    print(f"Domain:            {sample['domain']}")
    print(f"Raw Transcript:    {sample['raw_transcript']}")
    print(f"Tagged Transcript: {sample['tagged_transcript']}")
    print("=" * 60)


if __name__ == "__main__":
    main()

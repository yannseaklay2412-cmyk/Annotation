import re
from pathlib import Path
from typing import Optional, List, Dict, Any
import gspread

ROOT = Path(__file__).resolve().parent
SERVICE_ACCOUNT_FILE = ROOT / "service_account.json"
SPREADSHEET_ID = "1o6_Nj8YeTNZ4xCf3OS5vm5_TLkSlfAdoXsyvBwVo_wQ"

_worksheet = None


def get_worksheet() -> gspread.Worksheet:
    """Connects to Google Sheets using service_account.json."""
    global _worksheet
    if _worksheet is None:
        if not SERVICE_ACCOUNT_FILE.exists():
            raise FileNotFoundError(f"Missing {SERVICE_ACCOUNT_FILE}. Please check your setup.")
        gc = gspread.service_account(filename=str(SERVICE_ACCOUNT_FILE))
        sh = gc.open_by_key(SPREADSHEET_ID)
        _worksheet = sh.sheet1
    return _worksheet


def format_duration(seconds: float) -> str:
    """Converts seconds into HH:MM:SS duration string."""
    seconds = max(0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}"


def extract_video_id(url: str) -> str:
    """Extracts YouTube ID from full URL or short URL."""
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0].split("&")[0]
    if "v=" in url:
        return url.split("v=")[1].split("&")[0]
    return url.strip()


def get_tracked_rows() -> List[Dict[str, Any]]:
    """
    Returns all existing entries from the table starting after Header row (row 7).
    Each item contains: row_index, id, platform, link, topic, video_length, useful_duration
    """
    ws = get_worksheet()
    all_rows = ws.get_all_values()

    header_idx = None
    for idx, r in enumerate(all_rows):
        if r and r[0].strip().upper() == "ID":
            header_idx = idx
            break

    if header_idx is None:
        return []

    entries = []
    for offset, row in enumerate(all_rows[header_idx + 1:], start=header_idx + 2):
        if not row or not any(row):
            continue
        entries.append({
            "row_index": offset,
            "id": row[0].strip() if len(row) > 0 else "",
            "platform": row[1].strip() if len(row) > 1 else "",
            "link": row[2].strip() if len(row) > 2 else "",
            "topic": row[3].strip() if len(row) > 3 else "",
            "video_length": row[4].strip() if len(row) > 4 else "",
            "useful_duration": row[5].strip() if len(row) > 5 else "",
        })
    return entries


def get_next_id(prefix: str = "YT") -> str:
    """Finds next available ID like YT001, YT002, etc."""
    entries = get_tracked_rows()
    nums = []
    for e in entries:
        item_id = e["id"]
        if item_id.startswith(prefix):
            m = re.search(r"\d+", item_id)
            if m:
                nums.append(int(m.group(0)))
    next_num = max(nums) + 1 if nums else 1
    return f"{prefix}{next_num:03d}"


def add_video_to_sheet(url: str, title: str, duration_sec: float, platform: str = "YouTube") -> str:
    """
    Adds a new video row to Google Sheet if not already present.
    Returns the assigned ID (e.g. YT002).
    """
    ws = get_worksheet()
    entries = get_tracked_rows()
    vid = extract_video_id(url)

    # Check if already present
    for e in entries:
        if vid in e["link"] or (e["link"] and e["link"] == url):
            print(f"[Google Sheet] Video {vid} is already tracked as {e['id']}.")
            return e["id"]

    new_id = get_next_id("YT")
    length_str = format_duration(duration_sec)
    
    # Columns: ID, Platform, Video Link, Topic, Video Length, Useful Duration
    # Use video title as initial topic hint if blank
    row_data = [new_id, platform, url, title, length_str, ""]
    ws.append_row(row_data, value_input_option="USER_ENTERED")
    print(f"[Google Sheet] Added {new_id}: {title} ({length_str})")
    return new_id


def update_useful_duration(video_id_or_url: str, useful_sec: float) -> bool:
    """
    Updates the Useful Duration (Column F) for a video in the Google Sheet.
    """
    ws = get_worksheet()
    entries = get_tracked_rows()
    target_vid = extract_video_id(video_id_or_url)

    for e in entries:
        if target_vid in e["link"] or e["id"] == video_id_or_url:
            row_num = e["row_index"]
            formatted = format_duration(useful_sec)
            # Column F is column 6
            ws.update_cell(row_num, 6, formatted)
            print(f"[Google Sheet] Updated {e['id']} row {row_num} Useful Duration -> {formatted}")
            return True

    print(f"[Google Sheet] Warning: Video {video_id_or_url} not found in sheet to update duration.")
    return False


def get_links_from_sheet() -> List[str]:
    """Retrieves all video URLs currently listed in the Google Sheet."""
    entries = get_tracked_rows()
    return [e["link"] for e in entries if e["link"].startswith("http")]


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("      GOOGLE SHEETS CONNECTION CHECK")
    print("=" * 50)
    try:
        ws = get_worksheet()
        print(f"Status: Connected successfully!")
        print(f"Spreadsheet ID: {SPREADSHEET_ID}")
        
        # Read summary metrics from Row 5
        target_goal = ws.acell("A5").value or "10:00:00"
        collected = ws.acell("C5").value or "0:00:00"
        remaining = ws.acell("E5").value or "10:00:00"
        percent = ws.acell("G5").value or "0%"

        print("\n--- Current Dataset Progress ---")
        print(f"Target Goal:        {target_goal}")
        print(f"Collected Duration: {collected}")
        print(f"Remaining Duration: {remaining}")
        print(f"Progress:           {percent}")

        entries = get_tracked_rows()
        print(f"\n--- Tracked Videos ({len(entries)}) ---")
        for e in entries:
            useful = e['useful_duration'] or '(pending cut.py)'
            print(f"[{e['id']}] {e['platform']} | {e['video_length']} total | {useful} useful")
            print(f"       {e['link']}")
        print("=" * 50 + "\n")
    except Exception as err:
        print(f"Connection failed: {err}")


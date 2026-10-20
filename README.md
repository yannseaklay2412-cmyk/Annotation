# Khmer–English Code-Switching Speech Dataset & Annotation Pipeline

This repository hosts the semi-automated data curation, audio preprocessing, Label Studio annotation integration, and code-switching token tagging toolchain for **Capstone 1: Khmer–English Code-Switching Speech Dataset**.

---

## 📌 Project Overview
* **Goal:** Curate, validate, and document a 60+ hour human-validated Khmer–English code-switching speech dataset from eligible public YouTube and TikTok videos across 6 target domains.
* **Target Domains:**
  1. Podcasts & Interviews
  2. Education
  3. Social Issues
  4. Politics & Current Affairs
  5. Technology
  6. Entertainment & Lifestyle
* **Key Annotation Granularities:**
  * Dual-script verbatim transcripts (Khmer script + Latin script for English words).
  * Word-level and segment-level timestamps.
  * Code-switch boundaries and language tags (`[km]`, `[en]`, `[mixed]`).
  * Quality and uncertainty markers.

Full specifications and project proposals can be found in the [`docs/`](docs/) directory:
* [Master Specification (`PROJECT_MASTER_SPEC.md`)](docs/PROJECT_MASTER_SPEC.md)
* [Capstone Proposal PDF](docs/Capstone_Proposal_Khmer_English_Code_Switching_Speech_Dataset.pdf)
* [Advisor Request Document](docs/Group7_Capstone_Request_Advisor.pdf)

---

## 🗂 Directory Structure

```text
├── cut.py                     # Slices raw WAV into 1.5s - 15s chunks at natural pauses
├── download.py                # Downloads audio/subtitles via yt-dlp & syncs with Google Sheets
├── export_and_tag.py          # Exports annotations & auto-tags tokens ([km], [en], [mixed])
├── gsheet.py                  # Google Sheets tracking integration (gspread)
├── label_studio_config.xml    # Label Studio interface XML configuration
├── links.txt                  # List of target YouTube/TikTok URLs to process
├── make_task.py               # Generates Label Studio import tasks with pre-annotations
├── serve.py                   # Local audio streaming server with CORS enabled (port 8001)
├── tracking.csv               # Local source metadata tracking cache
├── tasks.json                 # Formatted tasks ready for Label Studio import
├── chunks_metadata.csv        # Metadata for generated chunks (timestamps, duration, text)
├── suspicious_chunks.csv      # Quality control report of edge-case chunks
├── annotated_dataset.csv      # Exported human-annotated dataset (CSV)
├── annotated_dataset.json     # Exported human-annotated dataset with token breakdowns (JSON)
├── chunks/                    # Directory of sliced 16kHz mono WAV audio clips
├── raw/                       # Raw downloads and timed subtitles (.vtt / .json3)
├── docs/                      # Capstone proposals and master specification documents
├── service_account.json.example # Template for Google Sheets service account credentials
├── requirements.txt           # Python dependencies
└── .gitignore                 # Protects private keys and caches from being tracked
```

---

## ⚙️ Prerequisites & Setup

### 1. System Requirements
* **Python 3.10+**
* **FFmpeg**: Must be installed and accessible from your system `PATH` (used for 16kHz mono audio slicing).
  * On Windows via winget: `winget install Gyan.FFmpeg`
  * On macOS via Homebrew: `brew install ffmpeg`
  * On Linux: `sudo apt install ffmpeg`

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Google Sheets Integration (Optional)
If syncing metadata with Google Sheets:
1. Copy `service_account.json.example` to `service_account.json`:
   ```bash
   cp service_account.json.example service_account.json
   ```
2. Replace with your actual Google Cloud Service Account credentials that have Editor access to the tracking sheet.
> ⚠️ **Note:** `service_account.json` is strictly listed in `.gitignore` to prevent leaking credentials.

---

## 🚀 End-to-End Workflow

### Step 1: Add Links & Download Audio
Add video URLs to `links.txt` (or add them directly into the Google Sheet), then run:
```bash
python download.py
```
This downloads 16kHz mono WAV audio and Khmer/English timed subtitle cues (`.json3` or `.vtt`) into `raw/`.

### Step 2: Slice Audio into Natural Chunks
Run the chunking script:
```bash
python cut.py
```
* Slices continuous speech into chunks between **1.5s** and **15s** (aiming for ~4s) at natural punctuation/pauses.
* Discards music-only and silent intervals.
* Generates sliced audio clips in `chunks/` and writes `chunks_metadata.csv`.

### Step 3: Start the Local Audio Server
Label Studio requires HTTP access to stream audio chunks in the browser:
```bash
python serve.py
```
* Runs on `http://localhost:8001` with full CORS support.
* Keep this terminal window open while annotating.

### Step 4: Generate Label Studio Import Tasks
In a separate terminal, run:
```bash
python make_task.py
```
This generates `tasks.json`, mapping audio URLs (`http://localhost:8001/chunks/...`), subtitle drafts, and metadata into Label Studio's pre-annotation schema.

### Step 5: Configure & Annotate in Label Studio
1. Start Label Studio:
   ```bash
   label-studio start
   ```
2. Create a new project.
3. In **Settings -> Labeling Interface -> Code**, paste the XML from [`label_studio_config.xml`](label_studio_config.xml).
4. In **Data Import**, upload `tasks.json`.
5. Listen to audio, drag waveform regions to label Khmer vs. English segments, correct the verbatim text, and assign quality flags.

### Step 6: Export & Tag Code-Switching Tokens
Once annotation batches are complete:
1. Export annotations from Label Studio as JSON (save as `export.json` in the root folder, or let the script query the local SQLite database directly).
2. Run:
   ```bash
   python export_and_tag.py
   ```
This produces:
* `annotated_dataset.csv`: Clean tabular dataset.
* `annotated_dataset.json`: Structured dataset with exact word-level tags (`[km]`, `[en]`, `[mixed]`, `[num]`, `[punct]`), code-switching boundaries, and quality flags.

---

## 📊 Dataset Schema (`annotated_dataset.json`)

```json
[
  {
    "chunk_id": "t_Sp8-9L9yQ_0001",
    "video_id": "t_Sp8-9L9yQ",
    "platform": "YouTube",
    "domain": "Education",
    "source_url": "https://youtu.be/t_Sp8-9L9yQ",
    "duration_sec": 3.92,
    "raw_transcript": "after school program អីចឹងទៅប៉ុន្តែចុះឡើងៗ",
    "tagged_transcript": "after [en] school [en] program [en] អីចឹងទៅប៉ុន្តែចុះឡើងៗ [km]",
    "token_count": 4,
    "tokens": [
      {"word": "after", "tag": "en"},
      {"word": "school", "tag": "en"},
      {"word": "program", "tag": "en"},
      {"word": "អីចឹងទៅប៉ុន្តែចុះឡើងៗ", "tag": "km"}
    ],
    "language_combo": "Khmer-English",
    "has_code_switching": "yes",
    "cs_boundaries": [
      {"label": "English [en]", "start_sec": 0.005, "end_sec": 1.503, "duration_sec": 1.498},
      {"label": "Khmer [km]", "start_sec": 1.499, "end_sec": 3.916, "duration_sec": 2.417}
    ],
    "quality_flags": "Clear Speech",
    "is_uncertain": "no",
    "is_unintelligible": "no"
  }
]
```

---

## ⚖️ License & Ethical Data Collection
* This dataset is curated for academic research under fair-use principles for speech processing and code-switching linguistic analysis.
* All audio clips are traceable back to their original source URLs, platforms, and non-sensitive identifiers.
* Full audio redistribution follows the guidelines outlined in [`docs/PROJECT_MASTER_SPEC.md`](docs/PROJECT_MASTER_SPEC.md).

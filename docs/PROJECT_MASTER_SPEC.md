# Khmer–English Code-Switching Speech Dataset (Capstone 1 Master Specification)

**Project Title:** Khmer–English Code-Switching Speech Dataset  
**Project Phase:** Capstone 1 (3-Month Project, 12 Weeks)  
**Primary Language Scope:** Primarily Khmer–English (allowing other language combinations where present)  
**Source Platforms:** Publicly accessible **YouTube** and **TikTok** videos  
**Target Volume:** At least **60 hours** of usable, validated speech  

---

## 1. Project Overview & Problem Statement
* **Problem:** In Cambodia, code-switching (mixing two or more languages within an utterance) is ubiquitous in daily life, interviews, podcasts, education, and digital media. However, speech technology for Cambodia is severely bottlenecked by the absence of well-organized, time-aligned, and human-validated code-switching speech corpora.
* **Goal:** Curate, validate, and document a 60+ hour dataset from eligible public YouTube and TikTok videos across 6 target domains.
* **Deliverables:**
  1. Human-validated speech transcripts.
  2. Word-level timestamps (start and end times).
  3. Code-switching segment boundaries (start and end of switches).
  4. Language labels for words and segments.
  5. Repeatable semi-automated curation workflow and comprehensive dataset statistics.
  6. Feedback on the advisor's annotation platform (currently in its testing phase).
  7. Responsible access, licensing, and metadata package respecting copyright and platform terms.

---

## 2. Six Target Domains & Source Distribution

Sources are selected across **6 specific domains** using an explicit inclusion/exclusion checklist:
1. **Podcasts & Interviews** (conversational, multi-speaker dialogue)
2. **Education** (tutorials, lectures, academic discussions)
3. **Social Issues** (community discussions, forums, public topics)
4. **Politics & Current Affairs** (news commentary, political interviews)
5. **Technology** (programming, gadgets, software development, IT discussions)
6. **Entertainment & Lifestyle** (vlogs, reviews, casual storytelling)

---

## 3. Specific Annotation Requirements (Granularity)

Human annotators use the platform provided by the project advisor to produce:

| Component | Requirement | Guideline / Rule |
| :--- | :--- | :--- |
| **Dual-Script Transcripts** | Khmer script + English Latin words | Verbatim acoustic transcription. No phonetic transliteration. |
| **Word-Level Timestamps** | Exact `start_time` and `end_time` | Precise alignment per token/word. |
| **Code-Switch Boundaries** | Segment start and end boundaries | Clearly identifies where the speaker transitions from Khmer to English (and back). |
| **Language Labels** | Token/Segment language tags | Primarily `[km]` (Khmer) and `[en]` (English); other language codes where present. |
| **Uncertainty & Noise** | Explicit standardized markers | **Mark unintelligible speech and uncertain language decisions consistently rather than guessing.** |
| **Quality Tags** | Acoustic quality categories | Clear speech, background music, noise, overlapping voices. |

---

## 4. 12-Week Project Milestone Schedule

| Period | Activities | Deliverables / Milestones |
| :--- | :--- | :--- |
| **Weeks 1–2** | **Project Setup & Protocol:** Finalize 6 domain definitions, inclusion/exclusion criteria, metadata schema, annotation guide, responsible collection checklist. | Approved protocol & pilot source list. |
| **Weeks 3–4** | **Workflow & Platform Testing:** Build & test semi-automated source tracking and audio preparation workflow; pilot test the advisor's annotation platform. | Pilot batch annotated; workflow & platform issues documented. |
| **Weeks 5–7** | **Active Curation & Initial Annotation:** Screen candidate media, prepare standardized audio (16 kHz mono WAV); begin transcription, word-level timestamps, language labels, and code-switch boundaries. | ~20–25 hours curated/in annotation; interim quality review. |
| **Weeks 8–10** | **Continuous Curation & Peer Review:** Continue annotation; second-person review on defined sample, disagreement resolution, track progress toward 60 hours. | $\ge 45$ hours curated; quality-control report. |
| **Weeks 11–12** | **Final Quality Control & Delivery:** Final quality checks, compile statistics by domain/platform/language, review redistribution restrictions, package permitted deliverables. | $\ge 60$ hours usable curated speech; final dataset package and report. |

---

## 5. Responsible Collection, Copyright & Access Plan
* **No Blind Scraping:** Public accessibility is **not** assumed to be authorization to redistribute raw media files.
* **Traceability:** Every audio clip is traceable back to its source URL, platform, non-sensitive identifier, access date, duration, domain, and permissions.
* **Distribution Strategy:**
  * Where full audio redistribution is restricted by copyright or platform Terms of Service, provide permitted metadata, source URLs, timestamps, annotation files, and processing scripts.
  * Establish clear takedown and contact procedures.

---

## 6. Technical Toolchain & Architecture in Workspace (`/YTV`)

1. **Source Discovery & Tracking:**
   * YouTube & TikTok link tracking via Google Sheets (`gsheet.py`) and `tracking.csv`.
   * Metadata recording: `id`, `platform`, `link`, `title`, `channel`, `duration_min`, `domain/topic`, `code_switching`.
2. **Audio Standardizer (`download.py`, `cut.py`):**
   * Standardizes audio to **16 kHz, 16-bit, mono PCM WAV**.
   * Removes music-only sections, excessive noise, and unusable intervals.
   * Employs Whisper as an initial baseline draft (never as ground truth).
3. **Annotation Integration:**
   * Supports the advisor's annotation platform testing stage, alongside local Label Studio pipelines (`make_task.py`, `serve.py`, `label_studio_config.xml`).

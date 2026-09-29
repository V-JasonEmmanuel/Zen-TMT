# Zensar Content Studio

Offline enterprise tool that turns documents (PDF, DOCX, PPTX, TXT, Markdown, HTML), **demo videos**
and **code repositories** (zip upload or GitHub URL) into **on-brand PowerPoint decks, individual
visuals, motion-graphics MP4 videos and PDFs**, with a source reference for every statement.

Everything runs on the local machine: no cloud APIs, no telemetry. After a one-time setup
the application works with the network disconnected.

```
Upload → Instruct → Select brand → Generate → Review → Present / Play → Edit / Regenerate → Download
```

---

## Quick start (Windows 10/11)

Double-click **`start.bat`**. That's all.

On a new PC the first run needs internet and takes roughly 5–15 minutes. It installs whatever is missing and skips anything already done:

| Step | What happens |
|---|---|
| Python | uses an installed Python 3.10–3.12, or installs Python 3.12 via `winget` |
| Packages | creates a private `.venv` and installs `requirements.txt` (~300 MB) |
| Model | downloads the ONNX embedding model (~90 MB, no torch needed) |
| Interface | installs Node.js LTS via `winget` if needed, then builds the UI |
| Local AI (optional, asks) | installs Ollama and the `qwen2.5:3b` model (~2 GB) and selects it automatically |
| Video understanding (optional, asks) | downloads the `qwen2.5vl:3b` vision model (~3.2 GB) used to read demo videos frame by frame |
| Launch | runs the system check, starts the server and opens **http://localhost:8000** |

Later runs start in seconds and work fully offline. Close the minimised "Zensar Content Studio"
window (or run `stop.bat`) to stop the server. Setup logs are in `logs\`.

Unattended install: `set ZCS_ASSUME_YES=1` (accept all prompts) or `set ZCS_SKIP_AI=1` (no Ollama) before `start.bat`.

Developer mode (hot reload):

```bat
python backend\main.py          :: API on http://127.0.0.1:8000
npm run dev --prefix frontend   :: UI on  http://localhost:3000  (proxies /api to :8000)
```

Check the machine at any time:

```bat
python scripts\check_environment.py
```

### Requirements

| Component | Required | Notes |
|---|---|---|
| Python 3.10–3.12 | yes | installed automatically by `start.bat` |
| Node.js 18+ | yes | installed automatically by `start.bat` (builds the interface) |
| Ollama + a small instruct model | recommended | enables AI writing; without it the app uses **extractive mode** (real source sentences only) |
| Embedding model (ONNX) | yes | downloaded automatically by `start.bat` (`scripts/fetch_models.py`) |
| FFmpeg | for video | bundled automatically via `imageio-ffmpeg`, or set `FFMPEG_PATH` |
| Offline TTS | for narration | Windows voices (SAPI) work out of the box; Piper optional |
| OCR engine | optional | only for scanned PDFs: `pip install rapidocr_onnxruntime` |

### Choosing a local model (16 GB RAM / 4 GB VRAM class)

| Model | Size | Notes |
|---|---|---|
| `qwen2.5:3b` | ~1.9 GB | fits fully in 4 GB VRAM - **fastest**, good wording |
| `qwen2.5:7b` (Q4_K_M) | ~4.7 GB | best wording; partially offloaded to CPU. Measured on an RTX 3050 laptop: **~30 s per slide, ~5 min for a 10-slide deck** |
| `phi3:mini`, `llama3.2:3b` | ~2 GB | alternatives |

```bat
ollama pull qwen2.5:3b
```

Select the model in **Settings → Local AI**. Only one model is loaded at a time, and it is
unloaded after each generation run to free memory for rendering.

---

## How it works

The pipeline is deliberately structured. The document is never simply pasted into an LLM with
"make a presentation".

```
Document ─► Adapter (PDF/DOCX/PPTX/TXT/MD/HTML) ─► blocks with page numbers
         ─► Structure analysis (title, sections, canonical types, tables, figures)
         ─► Section-aware chunks (each keeps document / page / section / table / figure)
         ─► Local embeddings (ONNX MiniLM, cached per document)
Instruction ─► Content Contract (rules + optional LLM; explicit facts from the rules win)
         ─► Relevance ranking (semantic + keyword + section importance + content type, with hard exclusions)
         ─► Deterministic outline (slide slots from topics, structure and relevance)
         ─► Per-slide writing (LLM sees ONLY that slot's passages and must cite them; or extractive)
         ─► Verification (numbers must exist in the cited source; semantic + lexical support; re-grounding)
         ─► ContentPlan (canonical JSON) ─► Brand theme tokens ─► Layout engine ─► Scene
         ─► Renderers: PPTX (native editable) · PNG/JPG · SVG · PDF · MP4 (FFmpeg + offline TTS)
```

Responsibilities stay separate:

| Concern | Decided by | Code |
|---|---|---|
| What should be included | the user's instruction → `ContentContract` | `backend/planning/content_contract.py` |
| Which facts are allowed | the source document → relevance + verification | `backend/intelligence/` |
| How content is worded | local LLM (optional), constrained per slide | `backend/planning/content_planner.py`, `backend/llm/prompts/` |
| How it looks | the brand profile → theme tokens | `backend/branding/` |
| How files are produced | renderers drawing one shared scene | `backend/rendering/` |

### Hallucination control

* The LLM writes one slide at a time from 2–6 labelled source passages (`S1…Sn`) and must cite them.
* Every statement, step, KPI and quote is verified against its cited chunks:
  * **Numbers are a hard rule.** Any number, including ones with units like `12x` or `45ms`, that does not appear in the cited source makes the statement *unsupported*, and it is removed.
  * **Semantic and lexical support** give a confidence score. Statements below the threshold (Settings) are kept but flagged *needs review*, or removed if you choose that setting.
  * **Uncited statements** are re-grounded against the slide's candidate passages, or dropped.
* Narration sentences with unsupported numbers are removed.
* Charts are built deterministically from extracted tables, so the numbers are copied exactly. Columns with different units are never mixed on one axis.
* Architecture diagrams only keep components whose names appear in the source.
* Removed statements are reported on the slide ("Removed N statement(s) that could not be verified").

### Source mapping

Each project writes `source/source_mapping.json`:

```json
{
  "slides": { "slide_4": [ { "page": 2, "section": "5 Results", "source": "research.pdf", "table": 1 } ] },
  "claims": { "slide_4": [ { "claim": "…", "page": 2, "section": "5 Results", "confidence": 0.82, "status": "verified" } ] }
}
```

Source references also appear in the slide footers and the PPTX speaker notes, and in the UI
under **View sources** and the **Sources** tab.

---

## Brand system: the references are the source of truth

Brand profiles live in `brands/<id>/`:

```
brands/zensar/
├── brand.json        # name, logo rules, footer, template, provenance of every value
├── colors.json       # primary, secondary, accent, background, surface, text_primary, text_secondary, palette
├── typography.json   # heading/body/caption families, sizes, heading colour role
├── layouts.json      # slide size, margins, gutter, title alignment, cover style
├── components.json   # cards, accent bars, bullets, chart & table styling (as colour *roles*)
├── assets/           # logo files, fonts/
└── references/       # reference images, PowerPoint template
```

* **The Zensar profile starts empty on purpose.** No colour or font is assumed. Until values are
  set, renderers use a clearly labelled neutral greyscale/Arial fallback. Every fallback is
  listed in the Brand Manager and reported on each generation job.
* **Template analysis** (`.pptx/.potx`) reads the theme colours, theme fonts, slide size, master
  title position (margins), master logo and blank layout, and produces *suggestions with
  confidence scores*. You choose which to apply. With "use as base" on, generated decks are
  built on the template itself, so its masters, backgrounds and fixed artwork carry through.
* **Reference image analysis** extracts dominant colours, background, whitespace and alignment.
  Pixel-derived colour roles are always low confidence and pre-unselected. Typography is never
  guessed from pixels.
* Every value records its provenance (`manual`, `pptx_template`, `reference_image`) and confidence.
* Renderers never pick their own colours. Components reference colour roles (`primary`,
  `accent`, `on_primary` …), and per-slide overrides in the editor are limited to brand roles.

### Configuring Zensar (recommended order)

1. **Brand Manager → Zensar → PowerPoint template**: upload the official template, review the suggestions, and apply the correct ones.
2. **Colours / Typography**: confirm or correct each role against the official guidelines. Upload brand font files if they are not installed.
3. **Logo**: upload the logo (and a light version for dark backgrounds) and set its position.
4. **Reference images**: upload example slides, analyse them, and apply only what matches the guidelines.
5. **Preview**: renders sample slides with the current tokens.

Additional brands (e.g. for other business units) can be created without touching any code.

---

## Using the application

* **New project**
  1. **Sources.** Add as many as you like: documents, demo videos (.mp4 .mov .webm .mkv) and zipped repositories, or import a **GitHub URL**.
     For private repositories, a token is used for that one download and is never stored.
  2. **Brand & template.** Pick a design preset (Corporate, Bold, Minimal, Midnight, Tech) or an uploaded PowerPoint template, with live previews.
  3. **Instruction.** A live panel shows how it will be interpreted.
  4. **Outputs & video.**
     * Narration: an offline voice, **your own recording**, or none.
     * An optional **script** (typed, or imported from .txt/.md/.docx/.srt/.vtt).
     * **Background music.**
     * Extra **images and video clips**.
     * Transitions, slide animation, and an animated brand intro and closing card.
  5. **Generate.**
* **Demo videos.**
  * Scenes are detected automatically, and one keyframe per scene is read by the local vision model.
  * Each scene gets a narration timed to it. Numbers not visible on screen are dropped.
  * The demo is placed in the video after the explanatory slides.
  * The demo also feeds the slides: a walkthrough/workflow slide, screenshots, and the overview.
* **Repositories.**
  * README, technology stack (from the manifests), components and API endpoints.
  * An **architecture diagram** built from the real import graph.
  * A **workflow/pipeline** traced from the entry points.
* **Presentation**
  * Preview and slide navigation.
  * **Present**: full screen; ← → Space, `N` for notes, Esc.
  * Download PPTX/PDF.
* **Per slide**
  * *Edit content*: title, points, steps, KPIs, narration, layout, brand accent. Edits keep their source links, are re-checked, and show "Edited · not in source" if they add unsupported facts.
  * *Regenerate*: only that slide, with optional guidance.
  * *Change layout* and *View sources*.
* **Video editor** (project → *Video editor*)
  * A timeline of all clips (drag to reorder), with **add images, video clips, slides, intro or closing card**.
  * Per clip:
    * **trim** (sliders or "set at playhead")
    * **crop** (drag the box, or 16:9 / 4:3 / 1:1 / 9:16)
    * **speed** (0.25×–4×)
    * transition, slow zoom, original sound on/off and volume
    * narration text, or **your own recording for that clip**
  * The live preview plays exactly the trimmed range at the chosen speed with the crop applied.
  * Narration panel: voice, speed, whole-video recording, script with `## Slide N` markers.
  * Music panel: volume, ducking under narration, fades.
  * **Render preview** (fast, 960×540) or **Render final video**. Unchanged clips are reused from cache, so re-renders take seconds.
  * Clicking a clip jumps to it in the rendered video.
* **Templates / Media Library.** Browse presets and upload .pptx templates; manage images, videos and audio.
* **Images.** Gallery, full-screen lightbox, PNG/JPG/SVG per visual, download all as ZIP.
* **Sources / Content plan / Files.** Claim-level traceability, the canonical JSON, and every output file.
* **Projects.** Reopen, rename, delete, regenerate everything, re-render only, or regenerate the video only.

**Motion graphics.** Slides are animated layer by layer:
* Titles and bullets build in; diagrams build node by node; numbers count up; charts grow.
* The brand intro assembles the circle → square → triangle motif into the wordmark.
* Transitions include a Zensar grid-tile transition.

Only one feature goes online: **GitHub import**. It is an explicit action, and only `github.com` / `codeload.github.com` are allowed for it.

---

## Data & privacy

| Data | Location |
|---|---|
| Metadata (projects, jobs, plans, settings) | `data/app.db` (SQLite) |
| Uploaded documents + extraction/embedding caches | `data/documents/<document-id>/` |
| Working files (render cache, narration audio) | `projects/<project-id>/` |
| Generated outputs | `outputs/<project-slug>_<id>/` |
| Brand profiles and assets | `brands/` |
| Local models | `models/` (embeddings), Ollama's own store for LLMs |

* **Offline guard** (on by default): the backend process refuses every outbound connection to
  anything other than this machine. Loopback (Ollama, the UI) still works. Set `STRICT_OFFLINE=false` only for troubleshooting.
* Hugging Face / transformers offline flags are forced at startup.
* Only an Ollama server on localhost is accepted.
* No analytics or telemetry. The interface bundles all its assets and loads nothing from the internet.
* Logs contain identifiers, counts and timings only, never document text, prompts or model output.
* Uploaded files are treated as untrusted: filenames are sanitised, paths are contained
  (traversal is blocked), HTML scripts are discarded, and nothing uploaded is executed.

---

## Project structure

```
backend/
  main.py                 FastAPI app (+ serves the built UI in single-port mode)
  api/                    documents, projects, generation, brands, templates, settings
  ingestion/              plugin adapters: pdf, docx, pptx, txt, markdown, html (+ base registry)
  extraction/             structure analysis, OCR (optional engines)
  intelligence/           chunking, embeddings (ONNX/ST/hashing), retrieval (FAISS), relevance, verification
  llm/                    provider abstraction, Ollama provider, structured output, prompts/ (versioned)
  planning/               content contract, content planner, slide rules, visual planner, video planner
  branding/               brand profiles, theme tokens, fonts, template parser, reference analyzer
  rendering/              scene graph, layout engine + components (shared by all backends)
    ppt/                  PPTX backend (native editable shapes, tables, charts, notes)
    images/               raster (PNG/JPG) and SVG backends
    video/                narration (SAPI/Piper), storyboard, FFmpeg encoding
  pipeline/               background job runner, orchestrator (stages), output writer
  services/               document service (upload, cached processing)
  storage/                SQLite schema + data access
  schemas.py              Pydantic models: Document, DocumentChunk, ContentContract, ContentPlan, Slide, Visual, SourceReference, GenerationJob, Output
frontend/                 React + Vite + TypeScript + Tailwind
brands/  models/  data/  projects/  outputs/  templates/
scripts/                  setup.bat, check_environment.py, prepare_models.py, smoke_*.py
tests/                    pytest suite (49 tests)
```

Deviation from the suggested layout: the **layout engine and components live in
`rendering/` (shared)** instead of under `rendering/ppt/`. The PPTX, PNG, SVG, PDF and video
outputs all draw the same positioned scene, which guarantees that previews, visuals, the PDF and
video frames match the editable PowerPoint exactly.

### Extending

* New input format: add a `DocumentAdapter` subclass with `@register_adapter` in `backend/ingestion/`.
* New LLM runtime: implement `LLMProvider` (`backend/llm/base.py`).
* New layout: add a spec in `planning/slide_planner.py` and a function in `rendering/layouts.py`.
* New brand: Brand Manager → Create brand. No code changes.
* Planned extensions such as multi-document decks, CSV/Excel dashboards or document comparison fit
  the same pipeline: adapters produce chunks, the contract controls selection, and the plan drives rendering.

---

## Tests

```bat
python -m pytest            :: 49 tests, ~50 s (includes a real narrated video encode)
```

Covered areas:

* PDF, DOCX, TXT, Markdown, HTML and PPTX extraction, plus malformed files
* Structure detection and provenance
* Instruction parsing and relevance ranking, including exclusions
* JSON schema validation, repair and retry
* Fabricated-number removal
* Brand fallbacks and provenance, template and reference analysis
* PPTX output: slide count, native charts, notes, brand-only colours
* PNG/SVG visuals
* Video duration, audio and subtitle sync, and missing-FFmpeg degradation
* Full API workflow: upload, generate, download, edit, delete
* Path traversal, remote-host refusal, network guard, and the absence of cloud API keys

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Local model unavailable" | Start Ollama and select an installed model in Settings (or use Fast extractive). |
| Scanned PDF rejected | `pip install rapidocr_onnxruntime`, then retry. OCR runs only on pages without text. |
| Video has no voice | No offline voice found. Windows voices are under Settings → Time & Language → Speech. |
| Fonts look different in previews | Upload the brand font files in Brand Manager → Typography (PPTX keeps the font name regardless). |
| Slow generation | Use a 3B model (`qwen2.5:3b`), or Fast extractive mode. |

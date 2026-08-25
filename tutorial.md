# 📚 Research Assistant — Comprehensive Tutorial & Workflow Guide

A step-by-step guide to installing, configuring, and using the self-hosted AI Research Assistant workstation.

---

## 📑 Table of Contents

1. [Architecture & Overview](#1-architecture--overview)
2. [Prerequisites & System Requirements](#2-prerequisites--system-requirements)
3. [Installation & Environment Setup](#3-installation--environment-setup)
4. [Launching the Web Application](#4-launching-the-web-application)
5. [Importing Papers into Your Library](#5-importing-papers-into-your-library)
6. [Background AI Processing Pipeline](#6-background-ai-processing-pipeline)
7. [Writing Manuscripts in the LaTeX Web Editor](#7-writing-manuscripts-in-the-latex-web-editor)
8. [Real-time Semantic Highlight Search](#8-real-time-semantic-highlight-search)
9. [Interactive Semantic Knowledge Graph](#9-interactive-semantic-knowledge-graph)
10. [Grant Proposal Auditing & Visual Toolkit](#10-grant-proposal-auditing--visual-toolkit)
11. [Multi-Machine & Cloud Syncing](#11-multi-machine--cloud-syncing)
12. [Troubleshooting & FAQ](#12-troubleshooting--faq)

---

## 1. Architecture & Overview

**Research Assistant** brings together three core research workflows into a unified, local-first workstation:

```
┌─────────────────┐       ┌────────────────────────┐       ┌──────────────────────┐
│  Paper Ingestion│       │   Semantic Vector DB   │       │   LaTeX Manuscript   │
│ & Zotero Import ├──────►│  & Matryoshka Embeddings├─────►│  Editor & Citations  │
│ (SHA-256 Hashes)│       │      (ChromaDB)        │       │ (Highlight-to-Search)│
└─────────────────┘       └────────────────────────┘       └──────────────────────┘
```

- **Inbox & Ingestion (`ingest_module/`)**: SHA-256 fingerprinting ensures no duplicate papers exist in your library.
- **Content & Metadata Extraction (`extract_module/`)**: Reads PDFs (`PyMuPDF`), resolves metadata from Crossref, and generates summaries with local/remote LLMs (Ollama / Hugging Face).
- **Dual Search Engine (`db_module/`, `search_module/`)**: ChromaDB vector search (`google/embeddinggemma-300m` with 256-dim Matryoshka representation) + instant Bag-of-Words keyword index.
- **Knowledge Graph Explorer (`graph_module/`, `frontend_module/`)**: 2D UMAP projection and citation networks via Semantic Scholar API.
- **Grant Proposal Toolkit (`audit_module/`, `toolkit_module/`, `docx_module/`)**: Style auditing, quantity consistency checks, Gantt Work Schedule generator, PDF reviewer comment extraction, and Word `.docx` manipulation.

---

## 2. Prerequisites & System Requirements

- **Operating System**: macOS, Linux, or Windows (WSL2 supported).
- **Python**: Python 3.10+ (recommended via Conda/Miniconda).
- **(Optional) Local LLM via Ollama**:
  If you want offline metadata/summary extraction, install [Ollama](https://ollama.ai) and pull a model:
  ```bash
  ollama pull phi3
  # or: ollama pull llama3:8b
  ```
- **(Optional) Hugging Face Token**:
  If using `google/embeddinggemma-300m`, set `HF_TOKEN` in your environment or `.env` file to access gated weights:
  ```bash
  export HF_TOKEN="hf_your_token_here"
  ```

---

## 3. Installation & Environment Setup

### Step 1: Clone Your Repository
```bash
git clone <your-repository-url>
cd research-assistant
```

### Step 2: Create Conda Environment
Using the provided `environment.yml`:
```bash
conda env create -f environment.yml
conda activate ai_research_assistant
```

### Step 3: Configure Environment Variables (Optional)
Create a `.env` file in the project root if you want custom tokens or passwords:
```bash
AUTH_TOKEN=vibe-coding-secret
SERVER_PASSWORD=your_secure_password
ENABLE_TUNNEL=false
```

---

## 4. Launching the Web Application

### Option A: Via Terminal (Cross-Platform)
```bash
python -m server_module.main
```
Or with Uvicorn live-reload:
```bash
python -m uvicorn server_module.main:app --host 0.0.0.0 --port 8000 --reload
```

### Option B: Double-Click Launcher (macOS)
Double-click `launch.command` in Finder. It will automatically detect your conda environment, start the server, and open the UI in your default browser.

### Key Web Endpoints:
- ✍️ **LaTeX Research Editor**: [`http://localhost:8000/ui`](http://localhost:8000/ui)
- 📊 **Backend Monitor & Processing Dashboard**: [`http://localhost:8000/dashboard`](http://localhost:8000/dashboard)
- 🔭 **Knowledge Graph**: [`http://localhost:8000/ui/graph.html`](http://localhost:8000/ui/graph.html)
- 📖 **API Documentation**: [`http://localhost:8000/docs`](http://localhost:8000/docs)

---

## 5. Importing Papers into Your Library

### Method 1: 📦 One-Click Zotero Import (Recommended)
Automatically scans your local Zotero storage (`~/Zotero/storage`), deduplicates PDFs with SHA-256 hashes, queries Crossref for official metadata, and populates your library:
```bash
python scripts/import_zotero.py
```
To specify a custom Zotero path:
```bash
python scripts/import_zotero.py --path /path/to/your/Zotero/storage
```

### Method 2: 📂 Zero-Redundancy Inbox
Drop any scientific PDF directly into the `inbox/` folder:
```
research-assistant/
└── inbox/
    └── my_paper.pdf   <-- drop here
```
When you run the ingestion worker, it computes the SHA-256 hash of `my_paper.pdf`, creates `library/<hash>/`, moves the file, and avoids re-processing.

### Method 3: ☁️ Google Drive Sync
To sync from a remote shared Google Drive folder:
```bash
python scripts/gdrive_sync.py
```

---

## 6. Background AI Processing Pipeline

Open the **Backend Monitor** at `http://localhost:8000/dashboard`.

1. **Configure Processing Toggles**:
   - `Process New PDFs`: Ingests files from `inbox/` to `library/<hash>/`.
   - `Add DOI / Title / Authors`: Fetches official publication metadata.
   - `Find Keywords & Summaries`: Runs LLM content extraction.
   - `Compute Embeddings`: Generates Matryoshka vector embeddings in ChromaDB.
2. Click **"Run Process"** to trigger background processing.
3. The table automatically updates with paper statuses, titles, and extracted metadata.

---

## 7. Writing Manuscripts in the LaTeX Web Editor

Navigate to `http://localhost:8000/ui`.

### Project Management:
- Use the **PROJECT** dropdown in the left sidebar to switch between drafts or create a new project.
- Projects are saved as clean text files in `projects/<project_name>/draft.tex` and `references.bib`.
- Your work is auto-saved locally in the browser and synced with the backend.

---

## 8. Real-time Semantic Highlight Search

1. In the LaTeX editor, write or paste your text.
2. **Select / Highlight** any sentence, hypothesis, or claim (10+ characters).
3. The right-hand **Semantic Matches** panel automatically queries ChromaDB using cosine similarity over the Matryoshka embedding space.
4. Each result card displays:
   - Paper Title, Authors, and Publication Year.
   - AI Summary and Keywords.
   - Relevance Match Score (%).
   - **View PDF**: Opens the paper or supplementary files directly in an embedded viewer.
   - **Add Reference**: Automatically formats a BibTeX entry and appends it to your project's `references.bib`.

---

## 9. Interactive Semantic Knowledge Graph

Click the **"Knowledge Graph"** button in the header or visit `http://localhost:8000/ui/graph.html`.

- **Semantic 2D Projection**: Uses UMAP to map high-dimensional embeddings into intuitive 2D spatial clusters.
- **Focus Mode**: Select papers (**Shift+Click**) and click **"Set as Focus"** to re-orient distances relative to your selected subfield.
- **Citation Layer**: Overlays actual citation links retrieved from Semantic Scholar.
- **Structural Holes**: Identifies research white spaces — clusters of literature that are semantically close but lack citation bridges.

To pre-compute the knowledge graph cache from the command line:
```bash
python scripts/build_graph.py
```

---

## 10. Grant Proposal Auditing & Visual Toolkit

The repository includes command-line and API tools tailored for scientific manuscripts and grant proposals (e.g., DFG, NIH, ERC):

### 📝 Prose & Style Auditor
Scans manuscripts for formulaic AI transitions, empty negative clauses, single vs team voice imbalance, and doubled words:
```bash
python -m audit_module.prose_auditor
```

### 🔢 Numbers & Timeline Auditor
Verifies consistency of experimental quantities (animals, trials, sessions), checks milestone dates against total grant duration (e.g. 36 months), and validates arithmetic sums ($a + b = c$):
```bash
python -m audit_module.number_auditor
```

### 📅 DFG-Style Work Schedule Gantt Generator
Generates a publication-ready Work Schedule PNG image:
```bash
python -m toolkit_module.schedule_generator
```

### 💬 Reviewer Comments Extraction
Extracts native PDF sticky notes and Word margin comments:
```bash
python -m toolkit_module.pdf_comments /path/to/reviewed_paper.pdf
```

---

## 11. Multi-Machine & Cloud Syncing

The workstation supports distributed workflows across multiple computers (e.g. a GPU desktop compute worker + a laptop writing client):

- **Startup Git Pull**: The server automatically syncs with your remote git repository on startup.
- **Worker Mode**: On a powerful machine, run background embedding computation:
  ```bash
  python windows_worker.py --interval 600
  ```
- **Single-Instance Mutex**: `server.lock` prevents accidental duplicate server processes on the same machine.

---

## 12. Troubleshooting & FAQ

### Q: `ModuleNotFoundError: No module named 'chromadb'` (or other dependencies)
**A:** Ensure your active Python interpreter belongs to the conda environment:
```bash
conda activate ai_research_assistant
which python
```

### Q: How do I run the automated test suite?
**A:** Run the test verification scripts:
```bash
python test_grant_toolkit_integration.py
python test_search.py
```

### Q: Can I run without an internet connection?
**A:** Yes! Once the `embeddinggemma-300m` model weights are cached locally, vector embedding generation, Bag-of-Words search, and the LaTeX editor work completely offline.

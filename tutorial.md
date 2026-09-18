# My AI Research Assistant — User Tutorial

A step-by-step guide to setting up and using the full research pipeline.

---

## Table of Contents

1. [Setup & Installation](#1-setup--installation)
2. [Starting the Server](#2-starting-the-server)
3. [Backend Monitor Dashboard](#3-backend-monitor-dashboard)
4. [Adding Papers to Your Library](#4-adding-papers-to-your-library)
5. [Running AI Processing Tasks](#5-running-ai-processing-tasks)
6. [Writing Your Manuscript (LaTeX Editor)](#6-writing-your-manuscript-latex-editor)
7. [Semantic Search While Writing](#7-semantic-search-while-writing)
8. [Knowledge Graph (Citation Network)](#8-knowledge-graph-citation-network)
9. [Adding Citations to Your .bib File](#9-adding-citations-to-your-bib-file)
10. [Multi-Computer Sync via Git](#10-multi-computer-sync-via-git)

---

## 1. Setup & Installation

### Create and activate the shared Conda environment

```bash
# Clone the repository
git clone <your-repo-url>
cd my-ai-research-assistant

# Create the environment from the shared spec
conda env create -f environment.yml

# Activate it
conda activate ai_research_assistant
```

> [!IMPORTANT]
> All collaborating computers and AI agents must use the **same `environment.yml`**. If you install a new package, always run `conda env update -f environment.yml --prune` and commit the updated `environment.yml`.

### Install and start Ollama

The extraction module uses [Ollama](https://ollama.ai) for local LLM inference.

```bash
# Download and install from https://ollama.ai
# Then pull a lightweight model (recommended):
ollama pull phi3
```

---

## 2. Starting the Server

Run the server from the **root of the repository** (important for correct path resolution):

```bash
cd my-ai-research-assistant
python -m uvicorn server_module.main:app --host 0.0.0.0 --port 8000 --reload
```

On startup the server will automatically:
- **Sync the Git repository** via `git pull --rebase` to grab any changes from other computers.
- **Acquire a lock file** (`server.lock`) to prevent two instances from running simultaneously on the same machine.
- **Start a public ngrok tunnel** (optional — set `ENABLE_TUNNEL=false` to disable).

The two main interfaces are then available:
| URL | Purpose |
|---|---|
| `http://localhost:8000/dashboard` | Backend Monitor (admin view) |
| `http://localhost:8000/ui/` | LaTeX Editor (writing view) |

---

## 3. Backend Monitor Dashboard

Navigate to `http://localhost:8000/dashboard` to open the management dashboard.

![Backend Monitor Dashboard](https://raw.githubusercontent.com/jobellet/my-ai-research-assistant/main/docs/backend_monitor.png)

> *The Backend Monitor shows all ingested papers, their processing status, and missing metadata fields. The left sidebar controls which AI tasks the background processor will perform.*

### Dashboard Layout

| Area | Description |
|---|---|
| **Left sidebar — Processing Toggles** | Enable/disable individual AI tasks (e.g. skip embedding computation on a slow laptop). |
| **"Run Process" button** | Starts the background processing loop using only the enabled toggles. Turns red when active. |
| **"Sync Repo" button** | Manually triggers a `git pull --rebase` without restarting the server. |
| **Status badge** | Shows whether the processor is **Idle** or **Running** (green pulsing dot). |
| **Library table** | One row per paper: Filename, Status, Title/Authors, Missing Fields. |

---

## 4. Adding Papers to Your Library

The system uses a **zero-redundancy inbox** design. Simply drop any PDF into the `inbox/` folder:

```
my-ai-research-assistant/
└── inbox/
    └── my_paper.pdf   ← drop here
```

The `ingest_module` will:
1. Compute a **SHA-256 hash** of the file.
2. Create a unique folder: `library/<hash>/`.
3. Move the PDF there.

This guarantees the same paper can never be processed twice, even if you drop it again.

> [!TIP]
> You can drop multiple PDFs at once. The monitor watches the folder in real-time using `watchdog` and processes them sequentially.

---

## 5. Running AI Processing Tasks

From the **Backend Monitor**, use the sidebar toggles to choose which tasks to run, then click **Run Process**.

| Toggle | What it does |
|---|---|
| **Process New PDFs** | Moves files from `inbox/` → `library/<hash>/` |
| **Add DOI** | Asks the LLM to find/extract the DOI from the PDF text |
| **Add Authors** | Extracts the author list via the local LLM (Ollama) |
| **Add Title** | Extracts the paper title |
| **Find Keywords** | Generates a set of 3–5 representative keywords |
| **Compute Embeddings** | Encodes the paper summary with SentenceTransformers and stores it in ChromaDB |

> [!NOTE]
> You can run different tasks on different computers. For example: a powerful desktop can do **Compute Embeddings** while a laptop only does **Add Title / Add Authors**. The results are merged automatically via Git sync.

All extracted metadata is saved as `library/<hash>/metadata.json`. The Library table updates automatically every 5 seconds.

---

## 6. Writing Your Manuscript (LaTeX Editor)

Navigate to `http://localhost:8000/ui/` to open the research writing environment.

![LaTeX Editor UI](https://raw.githubusercontent.com/jobellet/my-ai-research-assistant/main/docs/research_ui.png)

> *The LaTeX Editor gives you a split-pane writing environment. Your draft auto-saves to local storage. Highlighting any text triggers a live semantic search of your library in the right panel.*

### Interface Layout

| Area | Description |
|---|---|
| **Left sidebar** | File navigator showing `draft.tex` and `references.bib` |
| **Centre — Editor** | Monaco-style LaTeX writing area with monospace font |
| **"Saved" indicator** | Auto-saves to browser local storage as you type |
| **"Editor / Knowledge Graph" tabs** | Switch between writing mode and the citation graph view |
| **Right panel — Semantic Matches** | Shows papers from your library that match the highlighted text |
| **Login button** | Enter your `x-auth-token` (default: `vibe-coding-secret`) to enable API calls |

---

## 7. Semantic Search While Writing

This is the core feature: **highlight any claim or sentence** in your draft, and the system automatically searches your entire paper library for relevant references.

**How it works:**
1. Type your LaTeX manuscript in the editor.
2. Select/highlight any sentence or phrase (minimum 10 characters).
3. After a 500ms debounce, the selected text is sent to `/api/search`.
4. Results appear in the **Semantic Matches** panel ranked by relevance score.

Each result card shows:
- **Paper title and authors**
- **AI-generated summary**
- **Relevance score** (% match)
- **"View PDF"** button to open the source document in a modal viewer
- **"Add Citation"** button to append the reference to `references.bib`

> [!TIP]
> The search uses **cosine similarity** in ChromaDB's embedding space — it finds conceptually related papers even when they use different terminology.

---

## 8. Advanced Knowledge Graph Explorer

Click the **"Knowledge Graph"** button in the main header of the LaTeX editor to open the dedicated graph explorer (at `/ui/graph.html`).

This is a high-performance WebGL-based visualization (Sigma.js) that maps your entire library based on semantic similarity.

### Key Features:
- **Semantic Mapping (UMAP)**: Papers are positioned based on their high-dimensional semantic proximity. Closely related papers form visible clusters.
- **Dynamic Focus Mode**: Select one or more papers (**Shift+Click**), then click **"Set as Focus"**. The graph will re-calculate distances relative to the mean embedding of your selection, helping you explore specific sub-fields.
- **Citation Layer**: Toggle **"Show Citations"** to overlay real-world citation links fetched from the Semantic Scholar API.
- **Structural Hole Detection**: Toggle **"Highlight Gaps"** to see "Structural Holes" — areas where two clusters are semantically similar but lack citation bridges. These represent high-potential research opportunities.
- **Interactive Sidebar**: Click any paper to view its metadata, AI summary, and local PDF.

---

## 9. Adding Citations to Your .bib File

From any search result card, click **"Add Citation"**. The system will:

1. Look up the paper's metadata in ChromaDB by its hash ID.
2. Generate a BibTeX citation key (e.g. `Smith2023MachineLearning`).
3. Safely append a `@article{...}` entry to `references.bib` using `bibtexparser` — without breaking existing entries.

You can verify the result by clicking `references.bib` in the file sidebar.

> [!CAUTION]
> Do not manually edit `references.bib` while the server is running an "Add Citation" task, to avoid write conflicts.

---

## 10. Multi-Computer Sync via Git

This system is designed to run across multiple synced computers (e.g. a home desktop + a lab workstation).

### Automatic Sync
The server performs `git pull --rebase` **automatically on startup**. This means:
- Starting the server on any machine will immediately pull the latest `library/` metadata and `references.bib` committed by other computers.

### Manual Sync
At any time, click the **"Sync Repo"** button in the Backend Monitor, or run from the terminal:
```bash
git pull --rebase
```

### Recommended Workflow for Distributed Processing
```
Computer A (Fast GPU desktop)
  └── Toggles ON: Compute Embeddings
  └── Toggles OFF: Everything else

Computer B (MacBook)
  └── Toggles ON: Add Title, Add Authors, Add DOI
  └── Toggles OFF: Compute Embeddings

Computer C (Lab server)
  └── Toggles ON: Process New PDFs
  └── Toggles OFF: Everything else
```

After each run, commit the results:
```bash
git add library/ references.bib
git commit -m "chore: processed N new papers"
git push
```

### Offloading Graph Generation (Speed Up)
The Knowledge Graph requires heavy computation (UMAP) and many API calls (Semantic Scholar). If your main machine is slow, you can run the generation on a more powerful machine:
 
1. **On the powerful machine**:
   ```bash
   python scripts/build_graph.py
   ```
2. **Commit the results**:
   ```bash
   git add library/graph_cache.json library/citation_graph.json
   git commit -m "chore: pre-computed knowledge graph"
   git push
   ```
3. **On your laptop**:
   The server will detect these files on startup (or after a "Sync Repo") and load them instantly instead of rebuilding them.
 
> [!NOTE]
> The **lock file** (`server.lock`) only prevents two instances on the **same machine**. Multiple computers on the network can each run their own instance safely, as long as they work on non-overlapping tasks and sync via Git regularly.

---

*Tutorial generated for My AI Research Assistant v0.1 — 2026-04-22*

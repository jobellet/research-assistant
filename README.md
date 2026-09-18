# 🔬 Research Assistant

> A self-hosted, privacy-focused AI research workstation combining **Zotero** (PDF library management & metadata extraction), **Connected Papers** (semantic knowledge graphs & citation networks), and **Overleaf** (browser-based LaTeX manuscript editor with live semantic search).

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🚀 Quickstart in 3 Steps

### 1. Set Up Environment

```bash
# Clone the repository
git clone https://github.com/jobellet/research-assistant.git
cd research-assistant

# Create and activate conda environment
conda env create -f environment.yml
conda activate ai_research_assistant
```

*(Optional)* Set your Hugging Face token for the Matryoshka `google/embeddinggemma-300m` embedding model:
```bash
export HF_TOKEN="your_huggingface_token"
```

---

### 2. Import Your Paper Library

Choose whichever method best fits your existing workflow:

- 📦 **Zotero Library (1-Command Auto-Import)**:
  ```bash
  python scripts/import_zotero.py
  ```
  *Auto-detects `~/Zotero/storage`, calculates SHA-256 hashes for zero-duplicate ingestion, fetches metadata from Crossref, and builds the ChromaDB index.*

- 📂 **Local Inbox Folder**:
  Drop any scientific PDF directly into `inbox/`. The system hashes the file, moves it to `library/<hash>/`, extracts text, and indexes it automatically.

- ☁️ **Google Drive**:
  Run `python scripts/gdrive_sync.py` to mirror remote PDF folders.

---

### 3. Launch the Workstation

Start the local server:
```bash
python -m server_module.main
```

Open your browser and navigate to:
👉 **`http://localhost:8000/ui`**

*(On macOS, you can also simply double-click `launch.command` in Finder).*

---

## ✨ Core Features

- ✍️ **Web-Based LaTeX Manuscript Editor**: Write your papers directly in the browser with auto-save and multi-project organization (`projects/<name>/draft.tex`).
- 🔍 **Highlight-to-Search**: Select any sentence, hypothesis, or paragraph in your LaTeX draft to instantly surface relevant papers from your local library in real-time.
- 📌 **1-Click BibTeX Injection**: Click **"Add Reference"** on any search result to automatically format and append a clean BibTeX entry to `references.bib`.
- 🕸️ **Interactive Semantic Knowledge Graph**: Explore literature clusters in 2D using UMAP embeddings and visualize citation connections powered by Semantic Scholar.
- 📎 **Supplementary & Multi-File PDF Grouping**: Automatically clusters main papers and supplementary materials by DOI so you can view all associated files from a single card.
- 🛡️ **Grounded Claim Audit**: Compares each substantive manuscript sentence against supplied analysis/results text, flags unsupported or numerically conflicting claims, and returns the best evidence sentence for human review. It runs locally and never asks an LLM to fabricate evidence.
- 📊 **Grant Proposal & Manuscript QC Toolkit**: Built-in automated checks for prose style, voice balance, quantity consistency, grant timeline horizons, and DFG-style Gantt Work Schedule table generation.

---

## 💻 Handy CLI Utilities

| Command | Description |
| :--- | :--- |
| `python scripts/import_zotero.py` | Auto-detect and import all papers from local Zotero storage into library and ChromaDB. |
| `python -m audit_module.prose_auditor` | Audit manuscript/grant text for AI connectives, empty negatives, voice, rhythm & spellings. |
| `python -m audit_module.number_auditor` | Audit quantity agreement, grant timeline horizon bounds, sum checks ($a+b=c$), and ranges. |
| `python -c 'from audit_module import audit_claims; print(audit_claims("Draft claim.", "Analysis evidence."))'` | Compare draft claims with supplied analysis text; use `POST /api/audit/claims` for the authenticated API. |
| `python -m toolkit_module.schedule_generator` | Generate DFG-style Work Schedule Gantt chart PNG image for proposal submission. |
| `python -m toolkit_module.pdf_comments file.pdf` | Extract reviewer annotations and baked-in Word margin text comments from PDF. |
| `python -m toolkit_module.figure_fit fig.png` | Calculate exact figure page height fraction and text column scaling. |
| `python run_search.py` | Launch interactive desktop Tkinter search GUI. |
| `python scripts/search_bow.py "keyword"` | Perform instant Bag-of-Words keyword search on paper index without vector model overhead. |
| `python scripts/build_graph.py` | Pre-compute 2D UMAP projection and citation network cache (`library/graph_cache.json`). |
| `python test_grant_toolkit_integration.py` | Run integration test suite for auditing, schedule rendering, and docx tools. |
| `python test_search.py` | Run semantic vector search and path-traversal security test suite. |

---

## 🛡️ Grounded Claim Audit Demo

The audit compares a draft with the analysis text supplied to it. It identifies claims with matching evidence, prioritizes absolute statements for review, and detects conflicting numerical values. The matching evidence supports a reviewer’s decision; it does not itself prove scientific truth.

Binary assets are not stored in this repository. Generate the animated GIF locally with:

```bash
python scripts/record_claim_audit_demo.py --output /tmp/claim-audit-demo.gif
```

The generated demo uses real `audit_claims` output: one supported claim, one absolute claim requiring review, and one numerical contradiction.

---

## 📖 In-Depth Tutorial

For a detailed step-by-step walkthrough covering distributed processing, knowledge graph exploration, and remote tunneling, see [TUTORIAL.md](tutorial.md).

---

## 📄 License & Contributing

Open-source under the [MIT License](LICENSE). Contributions, bug reports, and feature requests are welcome!

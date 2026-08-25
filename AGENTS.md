# AGENTS.md — AI Agent Guidance & Codebase Index

> **Notice for AI Coding Agents (Claude, Jules, Codex, Antigravity, Aider, Cursor, etc.):**
> Read this file at the start of any new task to understand the codebase architecture, module responsibilities, existing functions, and conventions.

---

## 1. High-Level Description & Architecture

**Research Assistant** is a self-hosted, local-first research workstation combining:
- **PDF Management & Ingestion (`ingest_module/`, `extract_module/`)**: Monitors `inbox/` for scientific PDFs, hashes files with SHA-256 for zero-duplicate ingestion into `library/<hash>/`, extracts text using `PyMuPDF`, and queries Crossref/LLMs for metadata.
- **Vector Database & Search (`db_module/`, `search_module/`)**: Uses `google/embeddinggemma-300m` with Matryoshka Representation Learning (MRL) truncated to 256 dimensions in `ChromaDB` for semantic search, alongside a Bag-of-Words inverted index (`scripts/generate_bow.py`).
- **Citation & Knowledge Graph (`citation_module/`, `graph_module/`)**: Computes 2D UMAP projections and fetches citation networks via Semantic Scholar API; formats and updates BibTeX citations in `references.bib`.
- **Proposal Auditing & Visual Toolkit (`audit_module/`, `toolkit_module/`, `docx_module/`)**: Automated quality control for grant proposals and manuscripts, DFG-style Gantt Work Schedule table generation, reviewer comment extraction, and Word `.docx` manipulation.
- **Server & Web Interface (`server_module/`, `frontend_module/`)**: FastAPI server hosting REST API endpoints and web UI (LaTeX editor with live semantic search, PDF viewer, citation graph, library stats).

---

## 2. Primary Modules and Conventions

- **Database Manager**: `db_module.db_manager.DBManager` (uses Matryoshka 256-dim `google/embeddinggemma-300m`).
- **Semantic Search**: `search_module.searcher.SemanticSearcher` (groups main papers and supplementary materials by DOI).
- **Keyword Search**: `search_module.bow_searcher.BowSearcher` (instant lexical search).
- **Citation Manager**: `citation_module.citation_manager.CitationManager` (safe non-destructive updates to `references.bib`).

---

## 3. Running Tests

```bash
# Activate environment
conda activate ai_research_assistant

# Run test suites
python test_grant_toolkit_integration.py
python test_search.py
```

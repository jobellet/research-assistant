# AGENTS.md — AI Agent Guidance & Codebase Index

> **Notice for AI Coding Agents (Claude, Jules, Codex, Antigravity, Aider, Cursor, etc.):**
> Read this file at the start of any new task to understand the codebase architecture, module responsibilities, existing functions, and known obsolete/incompatible components without needing to re-read the full repository.

---

## 1. High-Level Description & Repository Purpose

**My AI Research Assistant** is a self-hosted, AI-powered research workstation: PDF library management with Zotero import and Crossref metadata extraction, a semantic and citation graph of papers (UMAP + Semantic Scholar), and a simple LaTeX draft editor with citation search (no compilation or collaboration). It is inspired by, and not affiliated with, Zotero, Connected Papers or Overleaf.

### Core Workflow Pipeline
1. **Ingestion (`ingest_module/`)**: Monitors `inbox/` for scientific PDFs. Computes SHA-256 binary hashes to create unique `library/<hash>/` folders and avoids duplicate processing.
2. **Content Extraction (`extract_module/`)**: Reads PDFs (`PyMuPDF`), cleans raw text (`scripts/clean_manuscript.py`), and resolves metadata (Title, Authors, Year, DOI, Summary, References) using fast Crossref API lookups with fallback to local/remote LLMs (Ollama / SLURM cluster GPU workers).
3. **Vector Database & Search (`db_module/`, `search_module/`)**: Uses **`google/embeddinggemma-300m`** with Matryoshka Representation Learning (MRL) truncated to 256 dimensions in `ChromaDB` for semantic search. Also builds a Bag-of-Words (BoW) inverted index and TF-IDF keywords (`search_module/bow_builder.py`, run automatically by the processor after new papers and by `scripts/generate_bow.py`) for instant keyword queries and the Quick Graph.
4. **Graph & Citation Management (`graph_module/`, `citation_module/`)**: Computes 2D UMAP embeddings and HDBSCAN/KMeans clusters for 2D/3D graph visualization, fetches citation networks via Semantic Scholar API, and injects BibTeX citations into LaTeX `.bib` files.
5. **Literature Discovery (`discovery_module/`)**: Searches arXiv, OpenAlex, Semantic Scholar and Crossref (merged, deduplicated, ranked with reciprocal-rank fusion), finds papers related to a library paper or to a passage of the draft, and downloads open-access PDFs into `inbox/`. Exposed as `python -m discovery_module`, `/api/discover/*` and the **Discover** tab of the editor.
6. **Server & Web Interface (`server_module/`, `frontend_module/`)**: FastAPI server hosting REST API endpoints and web UI (LaTeX editor with live semantic search, PDF viewer, citation graph, library stats). Optional `localhost.run` tunnel via `scripts/run_research_tunnel.sh` (the server itself starts no tunnel) and single-instance mutex locks (`server.lock`).

---

## 2. Capabilities (What the Repository CAN Do)

- **Unique Ingestion & Deduplication**: Hashes input PDFs using SHA-256 to ensure no paper is ingested or processed twice.
- **Hybrid Metadata Extraction**: Fast online Crossref database lookup with strict text/author verification; fallback LLM detective (multimodal image or text OCR).
- **Matryoshka Semantic Embeddings**: Uses Gemma embeddings (`google/embeddinggemma-300m`) truncated to 256 dimensions for fast vector search with low memory footprint.
- **Dual Search Engine**:
  - **Semantic Vector Search** (ChromaDB) with automatic grouping of main paper and supplementary PDFs by DOI.
  - **Bag-of-Words (BoW) Inverted Index** for instant keyword matching without embedding overhead.
- **LaTeX Manuscript Integration**: Interactive web editor that lets users highlight text, query the local library semantically, and inject references into `.bib` files.
- **Graph & Neighborhood Visualizer**: Computes UMAP dimensionality reduction and citation networks to view paper relations in 2D/3D.
- **Distributed Multi-Machine Support**: Locks single active server instance via `server.lock` and supports remote worker modes (`windows_worker.py`) for syncing Google Drive folders and offloading embedding calculation.

---

## 3. Aims & Limitations (What it aims to do and CANNOT do yet)

### Current Limitations
- **Offline Metadata Fallback**: Needs Crossref network connectivity or an active LLM worker endpoint to populate metadata for non-standard PDFs without DOIs.
- **Single-User Editing**: The LaTeX editor supports single-user sessions; multi-user real-time collaborative editing (like OT/CRDTs) is not implemented.
- **Hardcoded Cluster Paths**: Some background scripts (`run_embedding_watcher.sh`, `sync_my_ai_research.sh`) have hardcoded paths for specific HPC cluster environments (`/gpfs01/<lab>/...`).
- **Preprint / Manual PDF Handling**: Unindexed technical reports without DOIs require manual `metadata.json` editing or fallback keyword headers.

### Targeted Future Aims
- Full local offline OCR and metadata parser for papers without Crossref entries.
- PDF annotation and inline highlight synchronization into the web frontend.
- Automated multi-node worker queueing for massive PDF libraries (10,000+ papers).

---

## 4. Obsolete & Incompatible Functions / Scripts

The following scripts/functions are obsolete, contain hardcoded personal environment paths, or are incompatible with current modules:

| Script / Function | Issue Type | Details | Status / Fix Applied |
| :--- | :--- | :--- | :--- |
| **`scripts/build_graph.py`** | **Import Error (Fixed)** | Line 16 imported non-existent `ingest_module.database_manager`. | **RESOLVED**: Updated import to `from db_module.db_manager import DBManager`. |
| **`patch_years.py`** | **Hardcoded Path (Fixed)** | Line 57 used hardcoded path `/Users/<name>/.../library`. | **RESOLVED**: Replaced with `from config import LIBRARY_DIR`. |
| **`update_chroma.py`** | **Hardcoded Path (Fixed)** | Line 12 used hardcoded path `/Users/<name>/.../library`. | **RESOLVED**: Replaced with `from config import LIBRARY_DIR`. |
| **`db_module/vector_db.py`** & **`db_module/indexer.py`** | **Schema Keys (Fixed)** | Legacy implementation using uppercase metadata keys (`Title`, `Summary`). | **RESOLVED**: Updated to support both lowercase (`title`, `summary`, `keywords`) and legacy uppercase keys matching `DBManager`. |
| **`scripts/run_embedding_watcher.sh`** | **Cluster Path (Fixed)** | Referenced `/gpfs01/<lab>/.../embedding_watcher.py`. | **RESOLVED**: Updated to execute `windows_worker.py` relative to repo root. |
| **`scripts/sync_my_ai_research.sh`** | **Cluster Path (Fixed)** | Hardcoded `/gpfs01/<lab>/.../my-ai-research-assistant`. | **RESOLVED**: Updated with relative `SCRIPT_DIR` fallback resolution. |

---

## 5. Complete Function & Script Index

### Root Configuration & Core Entrypoints

#### [`config.py`](config.py)
Machine-specific configuration and path resolution.
- `get_config_summary()` -> `dict`: Returns dictionary of active paths, user, hostname, and database settings.

#### [`batch_indexer.py`](batch_indexer.py)
Batch indexing pipeline for local library folders.
- `process_single_paper(hash_id: str)` -> `tuple | None`: Loads `metadata.json` for a hash directory and returns `(hash_id, metadata, text_content)`.
- `run_batch_indexing(batch_size: int = 100)`: Scans `LIBRARY_DIR`, finds un-indexed documents, and batch inserts them into ChromaDB (and saves `embedding.json` if `WORKER_MODE=true`).

#### [`preprocess_library.py`](preprocess_library.py)
Syncs and prepares external Google Drive PDFs into hashed repository directories.
- `preprocess_google_drive(gdrive_path: str|Path, library_repo_dir: str|Path)`: Hashes PDFs, copies them to `library/<hash>/`, writes `source_info.txt`, and triggers metadata/text extraction.

#### [`windows_worker.py`](windows_worker.py)
Daemon/worker process for continuous background preprocessing and indexing.
- `run_worker_cycle()`: Runs one cycle of `preprocess_google_drive()` followed by `run_batch_indexing()`.
- `main()`: CLI entrypoint supporting `--single-run` or looping every `--interval` seconds.

#### [`run_search.py`](run_search.py)
Launcher script importing and running `scripts/search_gui.py`.

#### [`benchmark_n1.py`](benchmark_n1.py)
Benchmark testing speed of `ManuscriptProcessor._handle_indexing()` on mock synthetic libraries.
- `setup_benchmark()` -> `(tmp_library, tmp_inbox, db)`: Creates temporary folders and populates mock documents.
- `run_benchmark()` -> `float`: Measures execution time of manuscript indexing.

#### [`test_search.py`](test_search.py)
Test suite for semantic search, path traversal defense, metadata filtering, and batch queries.
- `setup_test_db()`: Populates test documents in ChromaDB.
- `test_queries()`: Verifies query retrieval and `where` filtering clauses.
- `test_path_traversal()`: Tests path traversal defense (`../../etc/passwd`) in `find_all_pdfs`.
- `test_search_batch()`: Tests batched semantic search responses.

#### [`test_potd.py`](test_potd.py)
Quick test script checking `fetch_cited_by_for_doi()` with Nature DOI (`10.1038/nature14402`).

#### [`patch_years.py`](patch_years.py) *(Obsolete/Hardcoded)*
Patches missing or incorrect publication years in `metadata.json` via Crossref API.
- `get_year_from_crossref(doi: str)` -> `str | None`: Fetches issued year from Crossref.
- `process_file(meta_path: Path)` -> `bool`: Updates a single `metadata.json` file.
- `main()`: ThreadPoolExecutor batch processing over library.

#### [`update_chroma.py`](update_chroma.py) *(Obsolete/Hardcoded)*
Syncs updated metadata (years, DOIs) from `metadata.json` files back into ChromaDB collections.
- `update_chroma_metadata()`: Reads ChromaDB IDs, updates corresponding metadata fields in batches of 100.

---

### Database Module (`db_module/`)

#### [`db_module/db_manager.py`](db_module/db_manager.py)
Primary database manager implementation.
- `GemmaMRLSafeEmbeddingFunction`: Custom ChromaDB embedding function wrapping `SentenceTransformer("google/embeddinggemma-300m")` with Matryoshka truncation (`truncate_dim=256`) and L2 normalization.
- `DBManager.__init__(db_path, collection_name, truncate_dim)`: Initializes ChromaDB client and collection with auto-recreation on dimension mismatch.
- `DBManager.index_document(hash_id, metadata, text_content)`: Upserts a single document and clean metadata into ChromaDB (uses pre-computed `embedding.json` if available).
- `DBManager.batch_index_documents(documents: list)`: Batch upserts documents `(hash_id, metadata, text_content)` into ChromaDB.
- `DBManager.query(query_text, n_results)` -> `dict`: Queries ChromaDB collection for top matching documents.

#### [`db_module/vector_db.py`](db_module/vector_db.py) *(Legacy)*
Alternate early implementation of VectorDB using uppercase metadata keys (`Title`, `Keywords`, `Summary`).

#### [`db_module/indexer.py`](db_module/indexer.py) *(Legacy)*
Wrapper class `LibraryIndexer` indexing directories using `VectorDB`.

---

### Ingestion Module (`ingest_module/`)

#### [`ingest_module/ingestor.py`](ingest_module/ingestor.py)
- `calculate_sha256(file_path: str)` -> `str`: Computes chunked SHA-256 hash of a file.
- `process_file(file_path: str, library_dir: str)` -> `str | None`: Validates PDF, hashes binary, creates `library/<hash>/`, and moves PDF file.

#### [`ingest_module/monitor.py`](ingest_module/monitor.py)
- `InboxHandler`: Watchdog `FileSystemEventHandler` listening for `on_created` and `on_moved` events in `inbox/`.
- `start_monitoring(inbox_dir: str, library_dir: str)`: Runs initial scan of `inbox/` and starts Watchdog observer loop.

#### [`ingest_module/test_ingestor.py`](ingest_module/test_ingestor.py)
Unit test creating a dummy PDF and testing `process_file()`.

---

### Extraction Module (`extract_module/`)

#### [`extract_module/extractor.py`](extract_module/extractor.py)
- `get_external_pdf_path()` -> `str`: Resolves path to external PDF directory.
- `process_paper(hash_dir, model, overwrite, delete_pdf, skip_llm)` -> `str`: Extracts text from PDF using PyMuPDF, fetches metadata via Crossref or LLM fallback, writes `full_text.txt` and `metadata.json`.
- `main(library_dir, model, overwrite, delete_pdf, workers, skip_llm, max_papers)`: ThreadPoolExecutor runner over library folders.

#### [`extract_module/llm_utils.py`](extract_module/llm_utils.py)
- `extract_doi_from_text(text: str)` -> `list`: Uses regex to extract and rank candidate DOIs by position and context.
- `search_crossref(query: str)` -> `list`: Queries Crossref API with fuzzy search.
- `calculate_confidence(pdf_text: str, official_meta: dict)` -> `float`: Strict verification scoring title and author overlap against PDF text (0.0 to 1.0).
- `map_to_metadata(item: dict)` -> `dict`: Converts Crossref API response to local JSON metadata schema.
- `fast_metadata_extract(text: str)` -> `dict | None`: Core metadata lookup attempting DOI regex -> Crossref API -> Title heuristic -> Verification.
- `get_doi_metadata(doi: str)` -> `dict | None`: Direct Crossref lookup by DOI.
- `extract_metadata_with_llm(text, image_b64, model)` -> `dict | None`: Prompt-based LLM metadata extraction fallback using local/remote LLM worker endpoints.

#### [`extract_module/pdf_utils.py`](extract_module/pdf_utils.py)
- `extract_first_page_as_image(pdf_path: str)` -> `str | None`: Renders page 1 of PDF as base64-encoded PNG using PyMuPDF (`fitz`).
- `extract_text_from_pdf(pdf_path: str, max_pages: int = None)` -> `str`: Extracts full text from PDF pages using PyMuPDF (`fitz`).

#### [`extract_module/run_llm_gpu.py`](extract_module/run_llm_gpu.py)
CLI helper script running HuggingFace `pipeline` text generation with `deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B` on CUDA GPUs.

---

### Search Module (`search_module/`)

#### [`search_module/searcher.py`](search_module/searcher.py)
- `SemanticSearcher.__init__(db_path, library_dir)`: Instantiates `DBManager` and resolves library directory.
- `SemanticSearcher.find_all_pdfs(hash_id, pdf_filename)` -> `list`: Locates local and external main paper and supplementary PDFs with path-traversal protection.
- `SemanticSearcher.search(query_text, n_results, where)` -> `list`: Performs semantic vector query and returns results grouped by DOI.
- `SemanticSearcher.search_batch(query_texts, n_results)` -> `dict`: Batched vector search against ChromaDB.
- `run_query(query_text)`: Helper CLI printing search output as JSON.

#### [`search_module/bow_searcher.py`](search_module/bow_searcher.py)
- `BowSearcher.__init__(index_path)`: Loads global Bag-of-Words index (`library/global_bow_index.json`).
- `BowSearcher.search(query, top_k)` -> `list`: Calculates relative frequency scores for query terms across papers.

---

### Discovery Module (`discovery_module/`)
- `sources.py`: rate-limit aware clients returning a common candidate schema — `arxiv_search`, `arxiv_lookup` (abstract page meta tags), `semantic_scholar_search`, `semantic_scholar_recommendations`, `semantic_scholar_links` (citations/references), `openalex_search`, `openalex_lookup`, `openalex_related`, `crossref_search`, helpers `normalize_arxiv_id`, `find_arxiv_id`. Optional keys: `S2_API_KEY`, `OPENALEX_API_KEY`.
- `discover.py`: `search_literature`, `related_to_paper`, `related_to_text`, `merge_ranked`, `library_index` (marks results already in the library), `resolve_identifier`, `download_to_inbox` (refuses non-PDF responses).
- `__main__.py`: CLI (`search`, `related`, `text`, `fetch`, `--fetch-top N`, `--json`).

### AI Module (`ai_module/`)
- `provider.py`: provider-agnostic LLM calls over HTTP (port of ADHDtools `core/ai-provider.js`): `PROVIDERS` (openai, gemini, anthropic, mistral, groq, openrouter, custom/OpenAI-compatible), `get_settings()` (ai_settings.json in DATA_DIR → `AI_*` env → auto-detect provider keys), `save_settings`, `public_settings` (key masked), `is_enabled`, `complete`, `stream` (SSE for every style), `complete_json`, `test_connection`. Used by `server_module/chat.py` (Ask / `POST /api/chat`) and `extract_module/llm_utils.extract_metadata_with_llm`; falls back to the LLM worker.

### Browser-side modules (`frontend_module/`)
- `project-store.js`: `window.ProjectStore` — projects via the server API or, in browser mode (no server, e.g. GitHub Pages on a phone), in localStorage; `snapshot()` / `applySnapshot()` for sync; project tombstones.
- `sync-merge.js` (also Node): `mergeSnapshots(local, remote, lastSyncAt)` — newest file wins, deletions win over older versions, edits on both sides kept as `<name> - conflict <date>`.
- `google-auth.js`, `drive-sync.js`: Google sign-in (Web Client ID, GIS token flow) and sync through the Drive `appDataFolder`: `research-assistant-projects.json` (merged both ways), `research-assistant-library.json` (library index uploaded by a page in server mode, from `GET /api/library/export`), `research-assistant-inbox.json` ("add to library" requests from the phone, run by the computer via `POST /api/discover/fetch`).
- `literature-core.js` (also Node): JavaScript ports of BibTeX generation (`citation_manager.py`), result merging/ranking and query terms (`discover.py`), OpenAlex/Crossref parsing, word search.
- `phone-library.js`: browser-mode library (IndexedDB copy of the index), word search, Cite, OpenAlex/Crossref Discover, add-to-library queue.
- `ask.js`, `settings.js`: Ask tab and Settings panel (AI provider, Drive sync). Tests: `tests/js/*.test.mjs` (`node --test`, run by `tests/test_js.py`).

### Server Module (`server_module/`)

#### [`server_module/main.py`](server_module/main.py)
FastAPI application backend serving REST endpoints and static web assets.
- `load_env()`: Parses `.env` configuration file.
- `get_project_path(name)` / `ensure_project_exists(name)` -> `Path`: Validates project paths with path-traversal safety.
- `update_access_file(url, password)`: Updates `SERVER_ACCESS.md` with active connection links.
- `startup_event()`: Initializes mutex lock, searchers, processor, and triggers background graph building.
- REST Endpoints:
  All `/api/*` routes except `/api/stats` require the `x-auth-token` header (or `?token=`).
  - `GET /health`, `GET /api/stats`: liveness and library statistics.
  - `GET /api/status`, `POST /api/process/start` (body: processor flags), `POST /api/process/stop`: background pipeline.
  - `GET /api/papers`: per-paper processing status and missing fields (Backend Monitor).
  - `GET /api/library`, `GET /api/library/text/{hash_id}`, `GET /api/pdf/{hash_id}[?filename=]`: library listing, extracted text, PDFs.
  - `POST /api/search`: `method` = `semantic` | `bow`; filters `year` (strict), `author` / `journal` (case-insensitive substrings); a year or library author named in a short query is a soft filter.
  - `GET/POST /api/projects`, `DELETE /api/projects/{name}` (`default` is protected), `GET/PUT /api/projects/{name}/draft`, `GET /api/projects/{name}/bib`.
  - `POST /api/citation/add` (`hash_id`, `project`): add a BibTeX entry, returns `bib_key`.
  - `GET /api/graph/semantic` (`{"status": "building"}` while rebuilding), `POST /api/graph/rebuild`, `POST /api/graph/focus`, `GET /api/graph/citations` (built in the background; poll), `GET /api/graph/neighbors/{hash_id}`, legacy `GET /api/graph`.
  - `POST /api/discover/search`, `POST /api/discover/text`, `GET /api/discover/related/{hash_id}`, `POST /api/discover/fetch`: online literature discovery (see `discovery_module/`).
  - `POST /api/audit/claims`: grounded claim audit.
  - `GET/PUT /api/ai/settings`, `POST /api/ai/test`: AI provider (key never returned). `GET /api/client-config`: public Google Client ID. `GET /api/library/export`: library index for Drive sync. `PUT /api/projects/{name}/bib`; draft/bib reads return `updated_at` and writes accept it (sync keeps timestamps).
  - `GET /api/papers_of_the_day`, `GET /api/seminal_papers`: recent papers citing the library / most-cited references not in the library (no UI yet).
  - `POST /api/chat/start|stop`, `GET /api/chat/status`, `POST /api/chat`: optional LLM worker (SLURM or local) for RAG answers.
  - `GET /dashboard`: Backend Monitor page; `/ui/`: web interface.

#### [`server_module/auth.py`](server_module/auth.py)
- `verify_auth_token(token, authorization)`: Dependency verifying HTTP bearer token or `?token=` query parameter against `SERVER_PASSWORD`.

#### [`server_module/mutex.py`](server_module/mutex.py)
- `ServerMutex.__init__(lock_file)`: File-based lock (`server.lock`) manager.
- `acquire()` -> `bool`: Attempts non-blocking file lock acquisition.
- `release()`: Releases file lock.

#### [`server_module/chat.py`](server_module/chat.py)
- `generate_chat_response(query, context_papers, model)` -> `str`: Formats paper abstracts/summaries and query into an LLM prompt and sends request to local Ollama or LLM worker service.

#### [`server_module/llm_worker.py`](server_module/llm_worker.py)
FastAPI microservice running on port 8002 serving `/generate` requests for GPU worker nodes.

---

### Citation & Graph Modules (`citation_module/`, `graph_module/`)

#### [`citation_module/citation_manager.py`](citation_module/citation_manager.py)
- `CitationManager.generate_bib_key(authors, year, title)` -> `str`: Generates unique BibTeX citation key (`AuthorYEARtitle`).
- `CitationManager.format_bib_entry(metadata)` -> `str`: Formats metadata dictionary into standard BibTeX `@article` string.
- `CitationManager.add_citation_to_project(project_name, hash_id, metadata)` -> `dict`: Appends reference to project `references.bib` if not already present.
- `CitationManager.parse_bib_file(bib_path)` -> `list`: Parses BibTeX file using `bibtexparser`.

#### [`graph_module/graph_builder.py`](graph_module/graph_builder.py)
- `build_semantic_graph(db_manager, force_rebuild)` -> `dict`: Extracts document embeddings from ChromaDB, computes 2D UMAP projection, clusters with HDBSCAN/KMeans, and saves `library/graph_cache.json`.
- `compute_focus_distances(focus_hash, db_manager, top_k)` -> `list`: Calculates vector distances between a focus paper and all library papers.

#### [`graph_module/citation_fetcher.py`](graph_module/citation_fetcher.py)
- `build_citation_graph(db_manager, force_rebuild)` -> `dict`: Queries Semantic Scholar API for incoming/outgoing paper citations and saves `library/citation_graph.json`.

#### [`graph_module/neighbor_graph.py`](graph_module/neighbor_graph.py)
- `build_neighbor_graph_bow(hash_id, top_n, library_dir)` -> `dict`: Computes paper neighborhood graphs based on shared top Bag-of-Words keywords.

---

### Processor Module (`processor_module/`)

#### [`processor_module/processor.py`](processor_module/processor.py)
- `ManuscriptProcessor.__init__(library_dir, inbox_dir)`: Pipeline orchestrator connecting ingestion, extraction, text cleaning, BoW generation, and vector indexing.
- `run_full_pipeline(config)` -> `dict`: Executes configured pipeline stages (`_handle_ingestion`, `_handle_extraction`, `_handle_cleaning`, `_handle_bow`, `_handle_indexing`).

---

### Utility Scripts (`scripts/`)

#### [`scripts/add_citations_to_metadata.py`](scripts/add_citations_to_metadata.py)
- `fetch_references_for_doi(doi: str)` -> `list`: Fetches reference DOIs/titles from Crossref API.
- `update_paper(metadata_path: Path)` -> `bool`: Appends `references` list to paper `metadata.json`.

#### [`scripts/batch_clean.py`](scripts/batch_clean.py)
- `main(library_dir)`: Iterates over all `full_text.txt` files in library and generates cleaned `preprocessed_text.txt`.

#### [`scripts/build_graph.py`](scripts/build_graph.py) *(Incompatible import)*
- Standalone CLI generating graph cache. *(Fix required: change `ingest_module.database_manager` import to `db_module.db_manager`)*.

#### [`scripts/clean_manuscript.py`](scripts/clean_manuscript.py)
- `is_metadata_block(line)` -> `bool`: Detects headers, footers, ISSNs, copyright notices.
- `clean_text(text)` -> `str`: Applies line-break joining, ligature normalization, hyphenation repair, and header/footer stripping.
- `extract_info(text)` -> `dict`: Extracts candidate DOI and Title lines.
- `process_manuscript(input_path, output_path)`: Reads raw text file and writes cleaned file with header metadata.

#### [`scripts/daily_citation_updater.py`](scripts/daily_citation_updater.py)
- `fetch_cited_by_for_doi(doi: str)` -> `list`: Queries Semantic Scholar API for papers citing a given DOI.
- `update_library_citations()`: Updates `metadata.json` files with new incoming citations (`cited_by`).
- `run_daily_loop()`: Daemon sleeping 24 hours between update cycles.

#### [`scripts/gdrive_sync.py`](scripts/gdrive_sync.py)
- `sync_gdrive(folder_id, dest_path)`: Calls `gdown` via subprocess to mirror a remote Google Drive directory into `inbox/`.

#### [`scripts/import_zotero.py`](scripts/import_zotero.py)
- `detect_zotero_storage_path()` -> `Path`: Auto-detects default Zotero storage directory (`~/Zotero/storage`) across macOS, Windows, and Linux.
- `import_zotero_library(zotero_path, library_dir, max_papers, skip_indexing, workers)`: Recursively scans Zotero PDF attachments, hashes binaries with SHA-256 to create `library/<hash>/`, resolves metadata via Crossref, and indexes vectors into ChromaDB.
- `main()`: CLI entrypoint supporting `--path`, `--max-papers`, `--workers`, and `--skip-indexing`.

#### [`scripts/generate_bow.py`](scripts/generate_bow.py)
- `process_text(text: str)` -> `dict`: Computes term relative frequencies excluding stop words.
- `main(library_dir)`: Generates individual `bow.json` for each paper and compiles global inverted index `library/global_bow_index.json`.

#### [`scripts/generate_inventory.py`](scripts/generate_inventory.py)
- `main(library_dir, output_file)`: Compiles all paper metadata into a clean tabular CSV (`papers_inventory.csv`).

#### [`scripts/search_bow.py`](scripts/search_bow.py)
- CLI tool to query terms against `library/global_bow_index.json` and display top matching papers with percentage relevance scores.

#### [`scripts/search_gui.py`](scripts/search_gui.py)
- Desktop Tkinter GUI (`SearchGUI`) providing semantic search inputs, metadata filters, paper selection lists, and full-text preview panes.

#### [`scripts/verify_cleaning.py`](scripts/verify_cleaning.py)
- `normalize_text(text: str)` -> `str`: Standardizes quotes, ligatures, dashes, and whitespace.
- `verify_folder(ground_truth_dir, library_dir)` -> `bool`: Asserts whether ground truth text snippets exist within preprocessed text files.

## MCP module
`mcp_module/server.py` is a standalone MCP server (modes `discovery`, `library`, `full`; `full` adds `tools_full.py`, which calls the local app through `app_client.py` with the server-side `AUTH_TOKEN`) (JSON-RPC over POST `/mcp/<secret>`), run with `python -m mcp_module [--mode discovery|library|full] [--tunnel]`. It reads only `library/*/metadata.json`, never PDFs or full texts. Tests: `tests/test_mcp.py`. Docs: `docs/mcp.md`.

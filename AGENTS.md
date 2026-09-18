# AGENTS.md — AI Agent Guidance & Codebase Index

> **Notice for AI Coding Agents (Claude, Jules, Codex, Antigravity, Aider, Cursor, etc.):**
> Read this file at the start of any new task to understand the codebase architecture, module responsibilities, existing functions, and known obsolete/incompatible components without needing to re-read the full repository.

---

## 1. High-Level Description & Repository Purpose

**My AI Research Assistant** is a self-hosted, AI-powered research workstation combining features of **Zotero** (pdf management & metadata extraction), **Connected Papers** (semantic paper visualization & citation graphs), and **Overleaf** (web-based LaTeX manuscript drafting).

### Core Workflow Pipeline
1. **Ingestion (`ingest_module/`)**: Monitors `inbox/` for scientific PDFs. Computes SHA-256 binary hashes to create unique `library/<hash>/` folders and avoids duplicate processing.
2. **Content Extraction (`extract_module/`)**: Reads PDFs (`PyMuPDF`), cleans raw text (`scripts/clean_manuscript.py`), and resolves metadata (Title, Authors, Year, DOI, Summary, References) using fast Crossref API lookups with fallback to local/remote LLMs (Ollama / SLURM cluster GPU workers).
3. **Vector Database & Search (`db_module/`, `search_module/`)**: Uses **`google/embeddinggemma-300m`** with Matryoshka Representation Learning (MRL) truncated to 256 dimensions in `ChromaDB` for semantic search. Also builds a Bag-of-Words (BoW) inverted index (`scripts/generate_bow.py`) for instant keyword queries.
4. **Graph & Citation Management (`graph_module/`, `citation_module/`)**: Computes 2D UMAP embeddings and HDBSCAN/KMeans clusters for 2D/3D graph visualization, fetches citation networks via Semantic Scholar API, and injects BibTeX citations into LaTeX `.bib` files.
5. **Server & Web Interface (`server_module/`, `frontend_module/`)**: FastAPI server hosting REST API endpoints and web UI (LaTeX editor with live semantic search, PDF viewer, citation graph, library stats). Supports tunneling (`ngrok`, `localhost.run`) and single-instance mutex locks (`server.lock`).

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
- **Hardcoded Cluster Paths**: Some background scripts (`run_embedding_watcher.sh`, `sync_my_ai_research.sh`) have hardcoded paths for specific HPC cluster environments (`/gpfs01/siegel/...`).
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
| **`patch_years.py`** | **Hardcoded Path (Fixed)** | Line 57 used hardcoded path `/Users/marieschmidt/.../library`. | **RESOLVED**: Replaced with `from config import LIBRARY_DIR`. |
| **`update_chroma.py`** | **Hardcoded Path (Fixed)** | Line 12 used hardcoded path `/Users/marieschmidt/.../library`. | **RESOLVED**: Replaced with `from config import LIBRARY_DIR`. |
| **`db_module/vector_db.py`** & **`db_module/indexer.py`** | **Schema Keys (Fixed)** | Legacy implementation using uppercase metadata keys (`Title`, `Summary`). | **RESOLVED**: Updated to support both lowercase (`title`, `summary`, `keywords`) and legacy uppercase keys matching `DBManager`. |
| **`scripts/run_embedding_watcher.sh`** | **Cluster Path (Fixed)** | Referenced `/gpfs01/siegel/.../embedding_watcher.py`. | **RESOLVED**: Updated to execute `windows_worker.py` relative to repo root. |
| **`scripts/sync_my_ai_research.sh`** | **Cluster Path (Fixed)** | Hardcoded `/gpfs01/siegel/.../my-ai-research-assistant`. | **RESOLVED**: Updated with relative `SCRIPT_DIR` fallback resolution. |

---

## 5. Complete Function & Script Index

### Root Configuration & Core Entrypoints

#### [`config.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/config.py)
Machine-specific configuration and path resolution.
- `get_config_summary()` -> `dict`: Returns dictionary of active paths, user, hostname, and database settings.

#### [`batch_indexer.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/batch_indexer.py)
Batch indexing pipeline for local library folders.
- `process_single_paper(hash_id: str)` -> `tuple | None`: Loads `metadata.json` for a hash directory and returns `(hash_id, metadata, text_content)`.
- `run_batch_indexing(batch_size: int = 100)`: Scans `LIBRARY_DIR`, finds un-indexed documents, and batch inserts them into ChromaDB (and saves `embedding.json` if `WORKER_MODE=true`).

#### [`preprocess_library.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/preprocess_library.py)
Syncs and prepares external Google Drive PDFs into hashed repository directories.
- `preprocess_google_drive(gdrive_path: str|Path, library_repo_dir: str|Path)`: Hashes PDFs, copies them to `library/<hash>/`, writes `source_info.txt`, and triggers metadata/text extraction.

#### [`windows_worker.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/windows_worker.py)
Daemon/worker process for continuous background preprocessing and indexing.
- `run_worker_cycle()`: Runs one cycle of `preprocess_google_drive()` followed by `run_batch_indexing()`.
- `main()`: CLI entrypoint supporting `--single-run` or looping every `--interval` seconds.

#### [`run_search.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/run_search.py)
Launcher script importing and running `scripts/search_gui.py`.

#### [`benchmark_n1.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/benchmark_n1.py)
Benchmark testing speed of `ManuscriptProcessor._handle_indexing()` on mock synthetic libraries.
- `setup_benchmark()` -> `(tmp_library, tmp_inbox, db)`: Creates temporary folders and populates mock documents.
- `run_benchmark()` -> `float`: Measures execution time of manuscript indexing.

#### [`test_search.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/test_search.py)
Test suite for semantic search, path traversal defense, metadata filtering, and batch queries.
- `setup_test_db()`: Populates test documents in ChromaDB.
- `test_queries()`: Verifies query retrieval and `where` filtering clauses.
- `test_path_traversal()`: Tests path traversal defense (`../../etc/passwd`) in `find_all_pdfs`.
- `test_search_batch()`: Tests batched semantic search responses.

#### [`test_potd.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/test_potd.py)
Quick test script checking `fetch_cited_by_for_doi()` with Nature DOI (`10.1038/nature14402`).

#### [`patch_years.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/patch_years.py) *(Obsolete/Hardcoded)*
Patches missing or incorrect publication years in `metadata.json` via Crossref API.
- `get_year_from_crossref(doi: str)` -> `str | None`: Fetches issued year from Crossref.
- `process_file(meta_path: Path)` -> `bool`: Updates a single `metadata.json` file.
- `main()`: ThreadPoolExecutor batch processing over library.

#### [`update_chroma.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/update_chroma.py) *(Obsolete/Hardcoded)*
Syncs updated metadata (years, DOIs) from `metadata.json` files back into ChromaDB collections.
- `update_chroma_metadata()`: Reads ChromaDB IDs, updates corresponding metadata fields in batches of 100.

---

### Database Module (`db_module/`)

#### [`db_module/db_manager.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/db_module/db_manager.py)
Primary database manager implementation.
- `GemmaMRLSafeEmbeddingFunction`: Custom ChromaDB embedding function wrapping `SentenceTransformer("google/embeddinggemma-300m")` with Matryoshka truncation (`truncate_dim=256`) and L2 normalization.
- `DBManager.__init__(db_path, collection_name, truncate_dim)`: Initializes ChromaDB client and collection with auto-recreation on dimension mismatch.
- `DBManager.index_document(hash_id, metadata, text_content)`: Upserts a single document and clean metadata into ChromaDB (uses pre-computed `embedding.json` if available).
- `DBManager.batch_index_documents(documents: list)`: Batch upserts documents `(hash_id, metadata, text_content)` into ChromaDB.
- `DBManager.query(query_text, n_results)` -> `dict`: Queries ChromaDB collection for top matching documents.

#### [`db_module/vector_db.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/db_module/vector_db.py) *(Legacy)*
Alternate early implementation of VectorDB using uppercase metadata keys (`Title`, `Keywords`, `Summary`).

#### [`db_module/indexer.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/db_module/indexer.py) *(Legacy)*
Wrapper class `LibraryIndexer` indexing directories using `VectorDB`.

---

### Ingestion Module (`ingest_module/`)

#### [`ingest_module/ingestor.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/ingest_module/ingestor.py)
- `calculate_sha256(file_path: str)` -> `str`: Computes chunked SHA-256 hash of a file.
- `process_file(file_path: str, library_dir: str)` -> `str | None`: Validates PDF, hashes binary, creates `library/<hash>/`, and moves PDF file.

#### [`ingest_module/monitor.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/ingest_module/monitor.py)
- `InboxHandler`: Watchdog `FileSystemEventHandler` listening for `on_created` and `on_moved` events in `inbox/`.
- `start_monitoring(inbox_dir: str, library_dir: str)`: Runs initial scan of `inbox/` and starts Watchdog observer loop.

#### [`ingest_module/test_ingestor.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/ingest_module/test_ingestor.py)
Unit test creating a dummy PDF and testing `process_file()`.

---

### Extraction Module (`extract_module/`)

#### [`extract_module/extractor.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/extract_module/extractor.py)
- `get_external_pdf_path()` -> `str`: Resolves path to external PDF directory.
- `process_paper(hash_dir, model, overwrite, delete_pdf, skip_llm)` -> `str`: Extracts text from PDF using PyMuPDF, fetches metadata via Crossref or LLM fallback, writes `full_text.txt` and `metadata.json`.
- `main(library_dir, model, overwrite, delete_pdf, workers, skip_llm, max_papers)`: ThreadPoolExecutor runner over library folders.

#### [`extract_module/llm_utils.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/extract_module/llm_utils.py)
- `extract_doi_from_text(text: str)` -> `list`: Uses regex to extract and rank candidate DOIs by position and context.
- `search_crossref(query: str)` -> `list`: Queries Crossref API with fuzzy search.
- `calculate_confidence(pdf_text: str, official_meta: dict)` -> `float`: Strict verification scoring title and author overlap against PDF text (0.0 to 1.0).
- `map_to_metadata(item: dict)` -> `dict`: Converts Crossref API response to local JSON metadata schema.
- `fast_metadata_extract(text: str)` -> `dict | None`: Core metadata lookup attempting DOI regex -> Crossref API -> Title heuristic -> Verification.
- `get_doi_metadata(doi: str)` -> `dict | None`: Direct Crossref lookup by DOI.
- `extract_metadata_with_llm(text, image_b64, model)` -> `dict | None`: Prompt-based LLM metadata extraction fallback using local/remote LLM worker endpoints.

#### [`extract_module/pdf_utils.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/extract_module/pdf_utils.py)
- `extract_first_page_as_image(pdf_path: str)` -> `str | None`: Renders page 1 of PDF as base64-encoded PNG using PyMuPDF (`fitz`).
- `extract_text_from_pdf(pdf_path: str, max_pages: int = None)` -> `str`: Extracts full text from PDF pages using PyMuPDF (`fitz`).

#### [`extract_module/run_llm_gpu.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/extract_module/run_llm_gpu.py)
CLI helper script running HuggingFace `pipeline` text generation with `deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B` on CUDA GPUs.

---

### Search Module (`search_module/`)

#### [`search_module/searcher.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/search_module/searcher.py)
- `SemanticSearcher.__init__(db_path, library_dir)`: Instantiates `DBManager` and resolves library directory.
- `SemanticSearcher.find_all_pdfs(hash_id, pdf_filename)` -> `list`: Locates local and external main paper and supplementary PDFs with path-traversal protection.
- `SemanticSearcher.search(query_text, n_results, where)` -> `list`: Performs semantic vector query and returns results grouped by DOI.
- `SemanticSearcher.search_batch(query_texts, n_results)` -> `dict`: Batched vector search against ChromaDB.
- `run_query(query_text)`: Helper CLI printing search output as JSON.

#### [`search_module/bow_searcher.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/search_module/bow_searcher.py)
- `BowSearcher.__init__(index_path)`: Loads global Bag-of-Words index (`library/global_bow_index.json`).
- `BowSearcher.search(query, top_k)` -> `list`: Calculates relative frequency scores for query terms across papers.

---

### Server Module (`server_module/`)

#### [`server_module/main.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/server_module/main.py)
FastAPI application backend serving REST endpoints and static web assets.
- `load_env()`: Parses `.env` configuration file.
- `get_project_path(name)` / `ensure_project_exists(name)` -> `Path`: Validates project paths with path-traversal safety.
- `update_access_file(url, password)`: Updates `SERVER_ACCESS.md` with active connection links.
- `startup_event()`: Initializes mutex lock, searchers, processor, and triggers background graph building.
- REST Endpoints:
  - `GET /api/config`: Server status and worker config.
  - `POST /api/search`: Multi-mode search (`semantic` or `bow`) with metadata filters.
  - `GET/POST /api/projects`: List and create research draft projects.
  - `GET/POST /api/projects/{name}/draft`: Read/save LaTeX draft content (`draft.tex`).
  - `POST /api/projects/{name}/citation`: Add BibTeX reference to project `references.bib`.
  - `GET /api/graph`: Returns 2D UMAP graph layout and paper node clusters.
  - `POST /api/chat`: LLM RAG endpoint generating answers given paper contexts.
  - `POST /api/processor/run`: Trigger manual background processing cycles.

#### [`server_module/auth.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/server_module/auth.py)
- `verify_auth_token(token, authorization)`: Dependency verifying HTTP bearer token or `?token=` query parameter against `SERVER_PASSWORD`.

#### [`server_module/mutex.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/server_module/mutex.py)
- `ServerMutex.__init__(lock_file)`: File-based lock (`server.lock`) manager.
- `acquire()` -> `bool`: Attempts non-blocking file lock acquisition.
- `release()`: Releases file lock.

#### [`server_module/chat.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/server_module/chat.py)
- `generate_chat_response(query, context_papers, model)` -> `str`: Formats paper abstracts/summaries and query into an LLM prompt and sends request to local Ollama or LLM worker service.

#### [`server_module/llm_worker.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/server_module/llm_worker.py)
FastAPI microservice running on port 8002 serving `/generate` requests for GPU worker nodes.

---

### Citation & Graph Modules (`citation_module/`, `graph_module/`)

#### [`citation_module/citation_manager.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/citation_module/citation_manager.py)
- `CitationManager.generate_bib_key(authors, year, title)` -> `str`: Generates unique BibTeX citation key (`AuthorYEARtitle`).
- `CitationManager.format_bib_entry(metadata)` -> `str`: Formats metadata dictionary into standard BibTeX `@article` string.
- `CitationManager.add_citation_to_project(project_name, hash_id, metadata)` -> `dict`: Appends reference to project `references.bib` if not already present.
- `CitationManager.parse_bib_file(bib_path)` -> `list`: Parses BibTeX file using `bibtexparser`.

#### [`graph_module/graph_builder.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/graph_module/graph_builder.py)
- `build_semantic_graph(db_manager, force_rebuild)` -> `dict`: Extracts document embeddings from ChromaDB, computes 2D UMAP projection, clusters with HDBSCAN/KMeans, and saves `library/graph_cache.json`.
- `compute_focus_distances(focus_hash, db_manager, top_k)` -> `list`: Calculates vector distances between a focus paper and all library papers.

#### [`graph_module/citation_fetcher.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/graph_module/citation_fetcher.py)
- `build_citation_graph(db_manager, force_rebuild)` -> `dict`: Queries Semantic Scholar API for incoming/outgoing paper citations and saves `library/citation_graph.json`.

#### [`graph_module/neighbor_graph.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/graph_module/neighbor_graph.py)
- `build_neighbor_graph_bow(hash_id, top_n, library_dir)` -> `dict`: Computes paper neighborhood graphs based on shared top Bag-of-Words keywords.

---

### Processor Module (`processor_module/`)

#### [`processor_module/processor.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/processor_module/processor.py)
- `ManuscriptProcessor.__init__(library_dir, inbox_dir)`: Pipeline orchestrator connecting ingestion, extraction, text cleaning, BoW generation, and vector indexing.
- `run_full_pipeline(config)` -> `dict`: Executes configured pipeline stages (`_handle_ingestion`, `_handle_extraction`, `_handle_cleaning`, `_handle_bow`, `_handle_indexing`).

---

### Utility Scripts (`scripts/`)

#### [`scripts/add_citations_to_metadata.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/scripts/add_citations_to_metadata.py)
- `fetch_references_for_doi(doi: str)` -> `list`: Fetches reference DOIs/titles from Crossref API.
- `update_paper(metadata_path: Path)` -> `bool`: Appends `references` list to paper `metadata.json`.

#### [`scripts/batch_clean.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/scripts/batch_clean.py)
- `main(library_dir)`: Iterates over all `full_text.txt` files in library and generates cleaned `preprocessed_text.txt`.

#### [`scripts/build_graph.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/scripts/build_graph.py) *(Incompatible import)*
- Standalone CLI generating graph cache. *(Fix required: change `ingest_module.database_manager` import to `db_module.db_manager`)*.

#### [`scripts/clean_manuscript.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/scripts/clean_manuscript.py)
- `is_metadata_block(line)` -> `bool`: Detects headers, footers, ISSNs, copyright notices.
- `clean_text(text)` -> `str`: Applies line-break joining, ligature normalization, hyphenation repair, and header/footer stripping.
- `extract_info(text)` -> `dict`: Extracts candidate DOI and Title lines.
- `process_manuscript(input_path, output_path)`: Reads raw text file and writes cleaned file with header metadata.

#### [`scripts/daily_citation_updater.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/scripts/daily_citation_updater.py)
- `fetch_cited_by_for_doi(doi: str)` -> `list`: Queries Semantic Scholar API for papers citing a given DOI.
- `update_library_citations()`: Updates `metadata.json` files with new incoming citations (`cited_by`).
- `run_daily_loop()`: Daemon sleeping 24 hours between update cycles.

#### [`scripts/gdrive_sync.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/scripts/gdrive_sync.py)
- `sync_gdrive(folder_id, dest_path)`: Calls `gdown` via subprocess to mirror a remote Google Drive directory into `inbox/`.

#### [`scripts/import_zotero.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/scripts/import_zotero.py)
- `detect_zotero_storage_path()` -> `Path`: Auto-detects default Zotero storage directory (`~/Zotero/storage`) across macOS, Windows, and Linux.
- `import_zotero_library(zotero_path, library_dir, max_papers, skip_indexing, workers)`: Recursively scans Zotero PDF attachments, hashes binaries with SHA-256 to create `library/<hash>/`, resolves metadata via Crossref, and indexes vectors into ChromaDB.
- `main()`: CLI entrypoint supporting `--path`, `--max-papers`, `--workers`, and `--skip-indexing`.

#### [`scripts/generate_bow.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/scripts/generate_bow.py)
- `process_text(text: str)` -> `dict`: Computes term relative frequencies excluding stop words.
- `main(library_dir)`: Generates individual `bow.json` for each paper and compiles global inverted index `library/global_bow_index.json`.

#### [`scripts/generate_inventory.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/scripts/generate_inventory.py)
- `main(library_dir, output_file)`: Compiles all paper metadata into a clean tabular CSV (`papers_inventory.csv`).

#### [`scripts/search_bow.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/scripts/search_bow.py)
- CLI tool to query terms against `library/global_bow_index.json` and display top matching papers with percentage relevance scores.

#### [`scripts/search_gui.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/scripts/search_gui.py)
- Desktop Tkinter GUI (`SearchGUI`) providing semantic search inputs, metadata filters, paper selection lists, and full-text preview panes.

#### [`scripts/verify_cleaning.py`](file:///Users/joachimbellet/Documents/GitHub/my-ai-research-assistant/scripts/verify_cleaning.py)
- `normalize_text(text: str)` -> `str`: Standardizes quotes, ligatures, dashes, and whitespace.
- `verify_folder(ground_truth_dir, library_dir)` -> `bool`: Asserts whether ground truth text snippets exist within preprocessed text files.

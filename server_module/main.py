import os
import signal
import sys
import logging
import json
import csv
from pathlib import Path
from typing import List, Dict, Any, Optional

# --- Simple .env loader ---
def load_env():
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip().strip('"').strip("'")

load_env()

import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Body, BackgroundTasks, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Internal imports using absolute paths from root
from server_module.mutex import ServerMutex
from server_module.auth import verify_auth_token, SERVER_PASSWORD
from search_module.searcher import SemanticSearcher
from search_module.bow_searcher import BowSearcher
from processor_module.processor import ManuscriptProcessor
from citation_module.citation_manager import CitationManager
from datetime import datetime
from graph_module.graph_builder import build_semantic_graph, compute_focus_distances
from graph_module.citation_fetcher import build_citation_graph
from graph_module.neighbor_graph import build_neighbor_graph_bow
from config import LIBRARY_DIR, EXTERNAL_LIBRARY_PATH, BOW_INDEX_PATH, CHROMA_DB_PATH
import threading

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="My AI Research Assistant API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
mutex = ServerMutex()
searcher = None
bow_searcher = None
processor = None
citation_manager = CitationManager()
_graph_cache = None           # in-memory graph cache
_graph_building = False       # lock flag for background build

PROJECTS_DIR = Path("projects")

# --- Models ---

class ProcessorConfig(BaseModel):
    process_new_pdfs: Optional[bool] = None
    add_doi: Optional[bool] = None
    add_authors: Optional[bool] = None
    add_title: Optional[bool] = None
    find_keyword: Optional[bool] = None
    compute_semantic_embedding: Optional[bool] = None

class QueryRequest(BaseModel):
    query: str
    n_results: int = 5
    method: str = "semantic" # 'semantic' or 'bow'
    year: Optional[int] = None
    author: Optional[str] = None
    journal: Optional[str] = None

class ProjectCreateRequest(BaseModel):
    name: str

class DraftSaveRequest(BaseModel):
    content: str

class CitationAddRequest(BaseModel):
    hash_id: str
    project: Optional[str] = "default"

class ChatRequest(BaseModel):
    query: str
    context_papers: List[Dict[str, Any]]
    model: Optional[str] = "phi3"

# --- Helpers ---

def get_project_path(name: str) -> Path:
    """Resolve and validate a project path, preventing path traversal."""
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_. ").strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid project name.")
    return PROJECTS_DIR / safe_name

def ensure_project_exists(name: str) -> Path:
    path = get_project_path(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found.")
    return path

def update_access_file(url: str, password: str):
    """Update SERVER_ACCESS.md with the latest connection details."""
    access_file = Path("SERVER_ACCESS.md")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Use the public URL if available, otherwise fallback to local
    display_url = url if url else "http://localhost:8000"
    
    content = f"""# 🚀 Research Assistant Access Details
**Last Started:** {now}

- **Public URL:** {display_url}
- **Access Password:** `{password}`
- **Direct Login Link:** [{display_url}/ui?token={password}]({display_url}/ui?token={password})

### 📎 Multi-File Support Enabled
The system is configured to group supplements and main papers by DOI. You can choose which file to open directly from the search result card.

---
*This file is updated automatically every time the server starts. If you are using a random ngrok tunnel, the URL will change on every restart.*
"""
    try:
        access_file.write_text(content)
        logger.info(f"Updated access details in {access_file}")
    except Exception as e:
        logger.error(f"Failed to update access file: {e}")

# --- Lifecycle Management ---

@app.on_event("startup")
def startup_event():
    """Server startup: acquire mutex, initialize modules, start tunnel."""
    global searcher, processor, bow_searcher

    # 0. Ensure projects dir and default project exist
    PROJECTS_DIR.mkdir(exist_ok=True)
    default_project = PROJECTS_DIR / "default"
    default_project.mkdir(exist_ok=True)
    if not (default_project / "draft.tex").exists():
        (default_project / "draft.tex").write_text("% Default project draft\n")
    if not (default_project / "references.bib").exists():
        (default_project / "references.bib").write_text("")

    # 1. Mutex Check
    if not mutex.acquire():
        logger.error("Mutex acquisition failed. Another instance running?")
        sys.exit(1)

    # 2. Initialize Searcher
    try:
        searcher = SemanticSearcher()
        bow_searcher = BowSearcher()
        logger.info("Searchers initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize searcher: {e}")

    # 3. Initialize Processor
    try:
        processor = ManuscriptProcessor(library_dir=LIBRARY_DIR, inbox_dir=EXTERNAL_LIBRARY_PATH)
        logger.info("Processor initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize processor: {e}")

    # 4. Start Tunnel (if enabled)
    from dotenv import load_dotenv
    load_dotenv()
    
    public_url = None

    # 5. Update access file for remote retrieval
    if public_url:
        update_access_file(public_url, SERVER_PASSWORD)
    # 6. Kick off semantic graph build in the background (non-blocking)
    if searcher:
        t = threading.Thread(target=_background_build_graph, daemon=True)
        t.start()

def _background_build_graph(force: bool = False):
    """Build the semantic graph in a background thread."""
    global _graph_cache, _graph_building
    if _graph_building:
        return
    _graph_building = True
    try:
        logger.info("[Graph] Background build started…")
        _graph_cache = build_semantic_graph(searcher.db_manager, force_rebuild=force)
        logger.info(f"[Graph] Build complete: {_graph_cache['stats']['n_nodes']} nodes, {_graph_cache['stats']['n_edges']} edges.")
    except Exception as e:
        logger.error(f"[Graph] Background build failed: {e}")
    finally:
        _graph_building = False

@app.on_event("shutdown")
def shutdown_event():
    """Server shutdown: release mutex, stop tunnel, stop processor."""
    logger.info("Server shutting down. Cleaning up...")
    if processor:
        processor.stop()
    mutex.release()

# --- Core Endpoints ---

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Research Assistant API is online."}

@app.get("/api/stats")
async def get_library_stats():
    library_dir = LIBRARY_DIR
    if not library_dir.exists():
        return {"error": "Library directory not found"}
        
    hash_dirs = [d for d in library_dir.iterdir() if d.is_dir() and len(d.name) == 64]
    
    total = len(hash_dirs)
    with_metadata = 0
    with_doi = 0
    with_text = 0
    
    for d in hash_dirs:
        if (d / "metadata.json").exists():
            with_metadata += 1
            try:
                with open(d / "metadata.json", "r") as f:
                    meta = json.load(f)
                    if meta.get("doi"):
                        with_doi += 1
            except:
                pass
        if (d / "full_text.txt").exists():
            with_text += 1
            
    return {
        "total_papers": total,
        "processed_metadata": with_metadata,
        "processed_text": with_text,
        "verified_dois": with_doi,
        "percent_complete": round((with_metadata / total * 100), 1) if total > 0 else 0
    }

@app.get("/api/status", dependencies=[Depends(verify_auth_token)])
def get_status():
    if not processor:
        raise HTTPException(status_code=500, detail="Processor not initialized.")
    return processor.get_status()

@app.post("/api/process/start", dependencies=[Depends(verify_auth_token)])
def start_processing(config: ProcessorConfig):
    if not processor:
        raise HTTPException(status_code=500, detail="Processor not initialized.")
    processor.update_config(config.dict(exclude_unset=True))
    processor.start()
    return {"status": "started", "config": processor.config}

@app.post("/api/process/stop", dependencies=[Depends(verify_auth_token)])
def stop_processing():
    if not processor:
        raise HTTPException(status_code=500, detail="Processor not initialized.")
    processor.stop()
    return {"status": "stopped"}

@app.get("/api/papers", dependencies=[Depends(verify_auth_token)])
def list_papers():
    """List ingested papers with their metadata status (filesystem based)."""
    library_path = Path("library")
    if not library_path.exists():
        return []

    papers = []
    for hash_dir in library_path.iterdir():
        if not hash_dir.is_dir():
            continue

        info = {"hash": hash_dir.name, "title": "Unknown", "status": "Ingested"}

        meta_path = hash_dir / "metadata.json"
        if meta_path.exists():
            try:
                with open(meta_path, 'r') as f:
                    meta = json.load(f)
                info["title"] = meta.get("title", "Unknown")
                info["status"] = "Processed"
            except:
                info["status"] = "Corrupt Metadata"

        papers.append(info)
    return papers

@app.get("/api/library", dependencies=[Depends(verify_auth_token)])
def get_library():
    """Get all indexed papers from papers_inventory.csv (fast) or ChromaDB for the library view."""
    papers = []
    inventory_path = Path("papers_inventory.csv")
    
    if inventory_path.exists():
        try:
            with open(inventory_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    metadata = {
                        "title": row.get("title", ""),
                        "authors": row.get("authors", ""),
                        "pdf_filename": row.get("pdf_filename", ""),
                        "doi": row.get("doi", ""),
                        "keywords": "" # Usually not in CSV, but ensures no KeyError in frontend
                    }
                    papers.append({
                        "hash_id": row.get("hash", ""),
                        "metadata": metadata
                    })
            return {"papers": papers}
        except Exception as e:
            logger.error(f"Failed to read inventory CSV: {e}")
            # Fall through to ChromaDB on error
            pass

    # Fallback to ChromaDB
    if not searcher:
        raise HTTPException(status_code=500, detail="Search engine not available.")
    try:
        # Avoid fetching the entire DB without IDs to prevent full-table scans
        # Instead, fetch IDs first using an empty include, or gather from filesystem.
        all_ids = searcher.db_manager.collection.get(include=[])["ids"]
        if all_ids:
            # Fetch metadatas for specifically these IDs
            results = searcher.db_manager.collection.get(ids=all_ids, include=["metadatas"])
            for i in range(len(results["ids"])):
                hash_id = results["ids"][i]
                metadata = results["metadatas"][i] or {}
                
                # Detect files for this hash
                pdf_filename = metadata.get("pdf_filename")
                all_files = searcher.find_all_pdfs(hash_id, pdf_filename=pdf_filename)
                
                papers.append({
                    "hash_id": hash_id,
                    "metadata": metadata,
                    "files": all_files
                })
        return {"papers": papers}
    except Exception as e:
        logger.error(f"Failed to fetch library from Chroma: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/library/text/{hash_id}", dependencies=[Depends(verify_auth_token)])
def get_library_text(hash_id: str):
    """Retrieve raw text for a specific paper."""
    # Check for various possible filenames created by different versions of the pipeline
    possible_names = ["full_text.txt", "preprocessed_text.txt", "extracted_text.txt"]
    txt_path = None
    
    for name in possible_names:
        p = Path("library") / hash_id / name
        if p.exists():
            txt_path = p
            break
            
    if not txt_path:
        raise HTTPException(status_code=404, detail="Extracted text not found.")
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            text = f.read()
        return {"text": text}
    except Exception as e:
        logger.error(f"Error reading text for {hash_id}: {e}")
        raise HTTPException(status_code=500, detail="Error reading text file.")

from collections import Counter
@app.get("/api/papers_of_the_day", dependencies=[Depends(verify_auth_token)])
def get_papers_of_the_day():
    """Return new (recently published) papers that cite our library papers, fetching live citations dynamically."""
    import random
    import requests
    import time
    
    library_dir = Path("library")
    library_dois = set()
    cited_counts = Counter()
    paper_info = {}
    valid_metas = []

    # 1. Gather all existing DOIs and metadata
    for meta_file in library_dir.glob("*/metadata.json"):
        try:
            with open(meta_file, 'r') as f:
                meta = json.load(f)
                doi = meta.get("doi")
                if doi:
                    doi_clean = doi.strip().lower()
                    library_dois.add(doi_clean)
                    valid_metas.append((meta_file, meta, doi_clean))
        except:
            pass

    # 2. Live search for new citations on a random subset of 5 papers
    sample_size = min(5, len(valid_metas))
    if sample_size > 0:
        sampled = random.sample(valid_metas, sample_size)
        for meta_file, meta, doi_clean in sampled:
            doi_no_url = doi_clean.replace("https://doi.org/", "").replace("http://doi.org/", "")
            url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi_no_url}"
            params = {"fields": "citations.externalIds,citations.title,citations.year"}
            try:
                resp = requests.get(url, params=params, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    fresh_citations = []
                    for cite in data.get("citations", []):
                        ext_ids = cite.get("externalIds", {})
                        c_doi = ext_ids.get("DOI")
                        c_title = cite.get("title")
                        c_year = cite.get("year")
                        
                        obj = {}
                        if c_title: obj["title"] = c_title
                        if c_year: obj["year"] = c_year
                        if c_doi: obj["doi"] = c_doi
                        if obj: fresh_citations.append(obj)
                        
                    # Merge with existing
                    existing_citations = meta.get("cited_by", [])
                    existing_dois = {c.get("doi") for c in existing_citations if c.get("doi")}
                    existing_titles = {c.get("title") for c in existing_citations if c.get("title")}
                    
                    new_citations = []
                    for c in fresh_citations:
                        c_doi = c.get("doi")
                        c_title = c.get("title")
                        if c_doi and c_doi not in existing_dois:
                            new_citations.append(c)
                            existing_dois.add(c_doi)
                        elif c_title and c_title not in existing_titles and not c_doi:
                            new_citations.append(c)
                            existing_titles.add(c_title)
                            
                    if new_citations:
                        meta["cited_by"] = existing_citations + new_citations
                        with open(meta_file, 'w') as f:
                            json.dump(meta, f, indent=4)
                time.sleep(0.35) # respect rate limits
            except Exception as e:
                logger.debug(f"Live POTD citation fetch failed for {doi_clean}: {e}")

    # 3. Count citations across the entire library
    for meta_file, meta, doi_clean in valid_metas:
        cited_by = meta.get("cited_by", [])
        for cite in cited_by:
            cite_doi = cite.get("doi", "").strip().lower() if cite.get("doi") else ""
            cite_title = cite.get("title", "").strip() if cite.get("title") else ""
            
            # Skip if it is already in our library
            if cite_doi and cite_doi in library_dois:
                continue
                
            key = cite_doi if cite_doi else cite_title.lower()
            if not key:
                continue
                
            cited_counts[key] += 1
            if key not in paper_info:
                paper_info[key] = {
                    "doi": cite.get("doi"),
                    "title": cite_title,
                    "year": cite.get("year")
                }

    # 4. Extract and sort by newest first, then by citation count
    candidates = []
    for key, count in cited_counts.items():
        info = paper_info[key]
        info["citation_count"] = count
        candidates.append(info)

    def safe_year(x):
        try:
            # Handle potential non-integer years gracefully
            return int(x.get("year") or 0)
        except:
            return 0

    # Sort descending by year, then descending by citation count
    candidates.sort(key=lambda x: (safe_year(x), x["citation_count"]), reverse=True)
    top_papers = candidates[:20]
        
    return {"papers_of_the_day": top_papers}

@app.get("/api/seminal_papers", dependencies=[Depends(verify_auth_token)])
def get_seminal_papers():
    """Return top papers that our library papers cite, which are not in our library."""
    library_dir = Path("library")
    library_dois = set()
    ref_counts = Counter()
    ref_info = {}

    # 1. Gather all DOIs currently in the library
    for meta_file in library_dir.glob("*/metadata.json"):
        try:
            with open(meta_file, 'r') as f:
                meta = json.load(f)
                doi = meta.get("doi")
                if doi:
                    library_dois.add(doi.strip().lower())
        except: continue

    # 2. Count outgoing references
    for meta_file in library_dir.glob("*/metadata.json"):
        try:
            with open(meta_file, 'r') as f:
                meta = json.load(f)
                refs = meta.get("references", [])
                for ref in refs:
                    if not ref: continue
                    ref_doi = ref.strip().lower() if "10." in ref else ref.strip()
                    
                    # Skip if already in library
                    if ref_doi in library_dois: continue
                    
                    ref_counts[ref_doi] += 1
                    if ref_doi not in ref_info:
                        ref_info[ref_doi] = {
                            "doi": ref_doi if "10." in ref_doi else None,
                            "title": ref if "10." not in ref_doi else "Loading title...", # Fallback
                            "raw_ref": ref
                        }
        except: continue

    # 3. Get top 20
    top_seminal = []
    for key, count in ref_counts.most_common(20):
        info = ref_info[key]
        # If it's a DOI, try to get a cleaner title from Crossref (cached/fast if possible)
        # For now, we return what we have
        info["cite_count"] = count
        top_seminal.append(info)

    return {"seminal_papers": top_seminal}

@app.post("/api/search", dependencies=[Depends(verify_auth_token)])
def search_papers(request: QueryRequest):
    if not searcher:
        raise HTTPException(status_code=500, detail="Search engine not available.")
    try:
        import re
        import csv

        # 1. Start with explicit filters
        filters = {}
        if request.year:
            filters["year"] = request.year
        if request.author:
            filters["author"] = request.author
        if request.journal:
            filters["journal"] = request.journal

        # 2. Add implicit filters from query text
        # Check for year
        if "year" not in filters:
            year_match = re.search(r'\b(19\d{2}|20\d{2})\b', request.query)
            if year_match:
                filters["year"] = int(year_match.group(1))

        # Check for known authors
        if "author" not in filters:
            known_authors = set()
            inventory_path = Path("papers_inventory.csv")
            if inventory_path.exists():
                try:
                    with open(inventory_path, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            author_str = row.get("authors", "")
                            if author_str:
                                # Simple split by comma or semicolon
                                for a in author_str.replace(";", ",").split(","):
                                    a = a.strip()
                                    if a:
                                        # only add simple last names or specific words
                                        for word in a.split():
                                            if len(word) > 2:
                                                known_authors.add(word.lower())
                except:
                    pass

            query_words = request.query.lower().split()
            found_author = None
            for word in query_words:
                if word in known_authors and word not in ["the", "and", "for", "with"]:
                    found_author = word
                    break

            if found_author:
                filters["author"] = found_author

        # 3. Construct ChromaDB `where` clause
        where_clause = None
        conditions = []

        if "year" in filters:
            conditions.append({"year": filters["year"]})

        if "author" in filters:
            # $contains works on strings in ChromaDB
            conditions.append({"authors": {"$contains": filters["author"]}})

        if "journal" in filters:
            conditions.append({"journal": {"$contains": filters["journal"]}})

        if len(conditions) == 1:
            where_clause = conditions[0]
        elif len(conditions) > 1:
            where_clause = {"$and": conditions}

        if request.method == "bow":
            if not bow_searcher:
                raise HTTPException(status_code=500, detail="BOW search engine not available.")
            
            # Bow search returns list of {hash_id, score, method}
            # Retrieve more to account for post-filtering
            results = bow_searcher.search(request.query, top_k=request.n_results * 5)
            
            # Enrich results with metadata and files using existing searcher logic
            enriched = []
            for res in results:
                if len(enriched) >= request.n_results:
                    break

                hash_id = res["hash_id"]
                
                # If we have a where_clause, we can just fetch via get with where
                get_kwargs = {"ids": [hash_id], "include": ["metadatas", "documents"]}
                if where_clause:
                    get_kwargs["where"] = where_clause

                # We'll do a single query to get the specific document from ChromaDB (to get metadata)
                meta_res = searcher.db_manager.collection.get(**get_kwargs)

                # If meta_res is empty, it means either it doesn't exist or it was filtered out by where clause
                if meta_res and meta_res["ids"]:
                    metadata = meta_res["metadatas"][0]
                    summary = meta_res["documents"][0]
                else:
                    continue # Filtered out
                
                pdf_filename = metadata.get("pdf_filename")
                all_files = searcher.find_all_pdfs(hash_id, pdf_filename=pdf_filename)
                
                enriched.append({
                    "hash_id": hash_id,
                    "score": res["score"],
                    "metadata": metadata,
                    "summary": summary,
                    "files": all_files,
                    "method": "bow"
                })
            return enriched
        else:
            return searcher.search(request.query, n_results=request.n_results, where=where_clause)
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/pdf/{hash_id}", dependencies=[Depends(verify_auth_token)])
def get_pdf(hash_id: str, filename: Optional[str] = None):
    if not searcher:
        raise HTTPException(status_code=500, detail="Search engine not available.")

    all_files = searcher.find_all_pdfs(hash_id)
    
    if not all_files:
        raise HTTPException(status_code=404, detail="No PDFs found for this entry.")
    
    selected_path = None
    if filename:
        # Find the specific file by name
        for f in all_files:
            if f["filename"] == filename:
                selected_path = f["path"]
                break
        if not selected_path:
            raise HTTPException(status_code=404, detail=f"File '{filename}' not found.")
    else:
        # Default to the first file found (usually the main paper)
        selected_path = all_files[0]["path"]

    if not os.path.exists(selected_path):
        raise HTTPException(status_code=404, detail="PDF file not found on disk.")

    return FileResponse(selected_path, media_type="application/pdf", content_disposition_type="inline")

@app.post("/api/chat/start", dependencies=[Depends(verify_auth_token)])
def start_chat_worker():
    import subprocess
    from pathlib import Path
    
    url_file = Path("library/.llm_worker_url")
    if url_file.exists():
        return {"status": "ready"}
        
    script = str(Path(os.getcwd()) / "run_llm_worker.sh")
    if Path(script).exists():
        try:
            res = subprocess.run(["sbatch", script], capture_output=True, text=True)
            return {"status": "starting", "job_info": res.stdout.strip()}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        # Local setup (e.g. Mac)
        import sys
        python_exe = sys.executable
        try:
            # Start worker in background
            subprocess.Popen([python_exe, "server_module/llm_worker.py"], 
                            cwd=os.getcwd(),
                            stdout=open("llm_worker.log", "a"),
                            stderr=subprocess.STDOUT)
            return {"status": "starting", "info": "Local worker started"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start local worker: {e}")

@app.get("/api/chat/status", dependencies=[Depends(verify_auth_token)])
def chat_worker_status():
    from pathlib import Path
    import requests
    
    url_file = Path("library/.llm_worker_url")
    if url_file.exists():
        url = url_file.read_text().strip()
        try:
            # Quick health check
            requests.get(url + "/docs", timeout=2)
            return {"status": "ready"}
        except:
            return {"status": "starting"}
            
    import getpass
    user = getpass.getuser()
    try:
        res = subprocess.run(["squeue", "-u", user, "-n", "llm_worker", "-h", "-O", "state"], capture_output=True, text=True)
        if "PENDING" in res.stdout or "RUNNING" in res.stdout:
            return {"status": "starting"}
    except:
        pass
        
    return {"status": "offline"}

@app.post("/api/chat/stop", dependencies=[Depends(verify_auth_token)])
def stop_chat_worker():
    import subprocess
    from pathlib import Path
    
    url_file = Path("library/.llm_worker_url")
    if url_file.exists():
        try:
            url_file.unlink()
        except:
            pass
            
    import getpass
    user = getpass.getuser()
    try:
        res = subprocess.run(["squeue", "-u", user, "-n", "llm_worker", "-h", "-O", "jobid"], capture_output=True, text=True)
        job_ids = [j.strip() for j in res.stdout.strip().split("\n") if j.strip()]
        for jid in job_ids:
            subprocess.run(["scancel", jid])
        return {"status": "stopped"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat", dependencies=[Depends(verify_auth_token)])
def chat_with_papers(request: ChatRequest):
    """Stream a RAG response using the LLM worker and retrieved papers context."""
    from server_module.chat import generate_rag_response
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        generate_rag_response(request.query, request.context_papers, request.model),
        media_type="text/plain"
    )

# --- Graph API Endpoints ---

class FocusRequest(BaseModel):
    paper_ids: List[str]

@app.get("/api/graph/semantic", dependencies=[Depends(verify_auth_token)])
def get_semantic_graph():
    """Return UMAP-projected semantic graph (nodes + k-NN edges + clusters + gaps)."""
    if not searcher:
        raise HTTPException(status_code=500, detail="Searcher not initialized.")
    global _graph_cache
    if _graph_cache:
        return _graph_cache
    # Cache not ready yet — try loading from disk
    from graph_module.graph_builder import _load_cache
    cached = _load_cache()
    if cached:
        _graph_cache = cached
        return cached
    if _graph_building:
        return {"status": "building", "message": "Graph is being built in the background. Please retry in ~30s.", "nodes": [], "edges": [], "clusters": [], "gaps": [], "stats": {}}
    # Trigger build synchronously as fallback
    try:
        _graph_cache = build_semantic_graph(searcher.db_manager)
        return _graph_cache
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/graph/focus", dependencies=[Depends(verify_auth_token)])
def graph_focus(req: FocusRequest):
    """Given selected paper IDs, return all papers sorted by distance to their mean embedding."""
    if not searcher:
        raise HTTPException(status_code=500, detail="Search engine not available.")
    if not req.paper_ids:
        raise HTTPException(status_code=400, detail="paper_ids list is required.")
    try:
        return {"distances": compute_focus_distances(req.paper_ids, searcher.db_manager)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/graph/citations", dependencies=[Depends(verify_auth_token)])
def get_citation_graph():
    """Return citation edges from Semantic Scholar (cached)."""
    if not searcher:
        raise HTTPException(status_code=500, detail="Search engine not available.")
    try:
        return build_citation_graph(searcher.db_manager, force_rebuild=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/graph/rebuild", dependencies=[Depends(verify_auth_token)])
def rebuild_graph(background_tasks: BackgroundTasks):
    """Force-rebuild the semantic graph cache in the background."""
    if not searcher:
        raise HTTPException(status_code=500, detail="Search engine not available.")
    if _graph_building:
        return {"status": "already_building"}
    background_tasks.add_task(_background_build_graph, True)
    return {"status": "rebuild_started"}

# Legacy endpoint kept for backwards compat
@app.get("/api/graph", dependencies=[Depends(verify_auth_token)])
def get_knowledge_graph_legacy():
    """Legacy graph endpoint — redirects to /api/graph/semantic."""
    return get_semantic_graph()

# --- Project Management Endpoints ---

@app.get("/api/projects", dependencies=[Depends(verify_auth_token)])
def list_projects():
    """Return list of all project names."""
    PROJECTS_DIR.mkdir(exist_ok=True)
    projects = sorted([p.name for p in PROJECTS_DIR.iterdir() if p.is_dir()])
    return {"projects": projects}

@app.post("/api/projects", dependencies=[Depends(verify_auth_token)])
def create_project(req: ProjectCreateRequest):
    """Create a new project folder with starter files."""
    project_path = get_project_path(req.name)
    if project_path.exists():
        raise HTTPException(status_code=409, detail=f"Project '{req.name}' already exists.")
    project_path.mkdir(parents=True)
    (project_path / "draft.tex").write_text(
        f"% Project: {req.name}\n\\documentclass{{article}}\n\\begin{{document}}\n\n\\end{{document}}\n"
    )
    (project_path / "references.bib").write_text("")
    logger.info(f"Created project: {req.name}")
    return {"status": "created", "name": req.name}

@app.delete("/api/projects/{name}", dependencies=[Depends(verify_auth_token)])
def delete_project(name: str):
    """Delete a project and all its files."""
    project_path = ensure_project_exists(name)
    import shutil
    shutil.rmtree(project_path)
    logger.info(f"Deleted project: {name}")
    return {"status": "deleted", "name": name}

@app.get("/api/projects/{name}/draft", dependencies=[Depends(verify_auth_token)])
def get_draft(name: str):
    """Get the .tex draft content for a project."""
    project_path = ensure_project_exists(name)
    draft_file = project_path / "draft.tex"
    content = draft_file.read_text() if draft_file.exists() else ""
    return {"name": name, "content": content}

@app.put("/api/projects/{name}/draft", dependencies=[Depends(verify_auth_token)])
def save_draft(name: str, req: DraftSaveRequest):
    """Save the .tex draft content for a project."""
    project_path = ensure_project_exists(name)
    (project_path / "draft.tex").write_text(req.content)
    return {"status": "saved", "name": name}

@app.get("/api/projects/{name}/bib", dependencies=[Depends(verify_auth_token)])
def get_bib(name: str):
    """Get the BibTeX content for a project."""
    project_path = ensure_project_exists(name)
    bib_file = project_path / "references.bib"
    content = bib_file.read_text() if bib_file.exists() else ""
    return {"name": name, "content": content}

@app.post("/api/citation/add", dependencies=[Depends(verify_auth_token)])
def add_citation(request: CitationAddRequest):
    """Add a paper to a specific project's BibTeX file."""
    hash_id = request.hash_id
    project_name = request.project or "default"

    if not hash_id or not searcher:
        raise HTTPException(status_code=400, detail="Invalid request")

    project_path = ensure_project_exists(project_name)
    bib_path = project_path / "references.bib"

    try:
        data = searcher.db_manager.collection.get(ids=[hash_id], include=["metadatas", "documents"])
        if not data["ids"]:
            raise HTTPException(status_code=404, detail="Paper not found")

        metadata = data["metadatas"][0]
        metadata["summary"] = data["documents"][0]
        metadata["hash"] = hash_id

        cm = CitationManager(bib_path=str(bib_path))
        bib_key = cm.add_entry(metadata)
        return {"status": "success", "bib_key": bib_key, "project": project_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add citation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/graph/neighbors/{hash_id}", dependencies=[Depends(verify_auth_token)])
def get_neighbor_graph(hash_id: str):
    """Return a local graph of the 50 nearest neighbors based on BOW."""
    if not searcher or not bow_searcher:
        raise HTTPException(status_code=500, detail="Search engines not available.")
    try:
        from graph_module.neighbor_graph import build_neighbor_graph_bow
        return build_neighbor_graph_bow(hash_id, bow_searcher, searcher.db_manager, top_n=50)
    except Exception as e:
        logger.error(f"Failed to build neighbor graph for {hash_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Frontend & Dashboard Static Files ---

frontend_path = Path("frontend_module")
if frontend_path.exists():
    app.mount("/ui", StaticFiles(directory=str(frontend_path), html=True), name="ui")
    logger.info("Mounted Research UI at /ui")

static_path = Path("server_module/static")
static_path.mkdir(parents=True, exist_ok=True)
app.mount("/dashboard", StaticFiles(directory=str(static_path), html=True), name="dashboard")

@app.get("/")
def redirect_to_ui():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/ui")

# Signal handling for interactive runs
def handle_exit(sig, frame):
    logger.info(f"Signal {sig} received. Terminating...")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("server_module.main:app", host="0.0.0.0", port=port, reload=False)

"""API for project reference lists: Zotero collections, sentence-level evidence, docx import.

Routes (all need the server password):

    GET    /api/zotero/status                  is a Zotero library found?
    GET    /api/zotero/collections             all collections (path, item count)
    GET    /api/projects/{p}/refs              the project's papers, Zotero link, sync state
    PUT    /api/projects/{p}/zotero            link a collection and sync it
    DELETE /api/projects/{p}/zotero            unlink (papers stay, as manual entries)
    POST   /api/projects/{p}/sync              sync the linked collection again
    POST   /api/projects/{p}/papers            add a library paper to the project
    DELETE /api/projects/{p}/papers/{hash}     remove a paper from the project
    POST   /api/projects/{p}/evidence          sentences of the project's papers matching a claim
    POST   /api/projects/{p}/import-docx       text of a .docx manuscript (for the editor)
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server_module.auth import verify_auth_token
from project_module import ProjectRefs, sync_from_zotero
from evidence_module import passages as ev

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(verify_auth_token)])

# Set by main.py at import time.
_ctx: Dict[str, Callable] = {}


def configure(*, project_path: Callable[[str], Path], get_searcher: Callable, library_dir: Path,
              on_library_changed: Callable[[], None], add_citation: Callable[[str, str], Optional[str]]):
    _ctx.update(project_path=project_path, get_searcher=get_searcher, library_dir=Path(library_dir),
                on_library_changed=on_library_changed, add_citation=add_citation)


# ---------------------------------------------------------------------------
# Zotero reader (one per process; created lazily)
# ---------------------------------------------------------------------------
_reader = None
_reader_error: Optional[str] = None
_reader_lock = threading.Lock()


def get_reader():
    global _reader, _reader_error
    with _reader_lock:
        if _reader is None:
            from zotero_module import ZoteroReader, ZoteroError
            try:
                _reader = ZoteroReader()
                _reader_error = None
            except ZoteroError as e:
                _reader_error = str(e)
        return _reader


def _require_reader():
    r = get_reader()
    if r is None:
        raise HTTPException(status_code=404, detail=_reader_error or "Zotero library not found.")
    return r


@router.get("/api/zotero/status")
def zotero_status():
    r = get_reader()
    return {"available": r is not None, "error": None if r else _reader_error}


@router.get("/api/zotero/collections")
def zotero_collections():
    from zotero_module import ZoteroError
    try:
        return {"collections": _require_reader().collections()}
    except ZoteroError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Sentence encoder (the library's embedding model at full size)
# ---------------------------------------------------------------------------
_encoder = None
_encode_lock = threading.Lock()
PASSAGE_DIM = 768


def get_encoder():
    global _encoder
    if _encoder is None:
        searcher = _ctx["get_searcher"]()
        if not searcher:
            raise HTTPException(status_code=503, detail="The embedding model is not loaded yet.")
        model = searcher.db_manager.embedding_fn.model
        dim = PASSAGE_DIM if "gemma" in ev._model_name(model).lower() else None
        raw = ev.sentence_transformer_encoder(model, dim=dim)

        def locked(texts, kind):
            with _encode_lock:
                return raw(texts, kind)
        locked.model_id = raw.model_id
        _encoder = locked
    return _encoder


def _index_passages(hash_id: str, pdf_path: Optional[Path] = None, force: bool = False):
    paper_dir = _ctx["library_dir"] / hash_id
    enc = get_encoder()
    if not force and ev.passage_index_is_current(paper_dir, enc.model_id):
        return
    ev.build_passage_index(paper_dir, enc, pdf_path=pdf_path)


def _index_paper(hash_id: str, meta: Dict):
    """Add the paper to the library search index if it is not there yet."""
    searcher = _ctx["get_searcher"]()
    if not searcher:
        return
    col = searcher.db_manager.collection
    if col.get(ids=[hash_id], include=[])["ids"]:
        return
    searcher.db_manager.index_document(hash_id, meta)


def _extract_text(pdf: Path) -> str:
    from extract_module.pdf_utils import extract_text_from_pdf
    return extract_text_from_pdf(str(pdf))


# ---------------------------------------------------------------------------
# Background jobs (sync, indexing) with per-project progress
# ---------------------------------------------------------------------------
_jobs: Dict[str, Dict] = {}
_jobs_lock = threading.Lock()


def _job_state(name: str) -> Dict:
    with _jobs_lock:
        return dict(_jobs.get(name) or {"running": False})


def _start_job(name: str, target: Callable[[Callable], Dict], label: str,
               rerun: bool = False) -> Dict:
    """Run ``target`` in a thread under the slot ``name``. If a job already runs in
    that slot nothing new starts; with ``rerun`` the running job is asked to run
    once more when it ends (e.g. a sync requested while a sync is running)."""
    with _jobs_lock:
        if (_jobs.get(name) or {}).get("running"):
            if rerun:
                _jobs[name]["rerun"] = True
            return dict(_jobs[name])
        _jobs[name] = {"running": True, "kind": label, "done": 0, "total": 0, "current": "",
                       "started": int(time.time()), "result": None, "error": None, "rerun": False}

    def progress(done, total, current):
        with _jobs_lock:
            _jobs[name].update(done=done, total=total, current=current)

    def run():
        while True:
            try:
                result = target(progress)
                outcome = {"result": result, "error": None}
            except Exception as e:
                logger.exception(f"[{label}] {name} failed")
                outcome = {"result": None, "error": str(e)}
            with _jobs_lock:
                job = _jobs[name]
                if job.get("rerun"):
                    job.update(rerun=False, done=0, total=0, current="", **outcome)
                    continue
                job.update(running=False, finished=int(time.time()), **outcome)
                return

    threading.Thread(target=run, daemon=True, name=f"{label}-{name}").start()
    return _job_state(name)


def _sync_job(project: str):
    project_dir = _ctx["project_path"](project)

    def target(progress):
        reader = _require_reader()
        result = sync_from_zotero(
            project_dir, _ctx["library_dir"], reader,
            index_paper=_index_paper,
            index_passages=lambda h, pdf: _index_passages(h, pdf),
            add_citation=lambda h, meta: _ctx["add_citation"](project, h),
            extract_text=_extract_text,
            progress=progress,
        )
        if result["added"]:
            try:
                _ctx["on_library_changed"]()
            except Exception as e:
                logger.warning(f"Library refresh after sync failed: {e}")
        return result
    return _start_job(f"sync:{project}", target, "sync", rerun=True)


# Papers whose sentence index could not be built, with the PDF state at that time,
# so an evidence request does not retry them until the PDF changes.
_index_failed: Dict[str, tuple] = {}


def _pdf_signature(hash_id: str) -> tuple:
    out = []
    for f in sorted((_ctx["library_dir"] / hash_id).glob("*.pdf")):
        try:
            st = f.stat()
            out.append((f.name, st.st_size, st.st_mtime_ns))
        except OSError:
            pass
    return tuple(out)


def _index_job(project: str, hash_ids: List[str]):
    def target(progress):
        failed = []
        for n, h in enumerate(hash_ids):
            progress(n, len(hash_ids), h)
            try:
                _index_passages(h)
                _index_failed.pop(h, None)
            except FileNotFoundError:
                logger.info(f"No PDF for {h}: no sentence index")
            except Exception as e:   # one unreadable PDF must not stop the others
                logger.warning(f"Sentence index failed for {h}: {e}")
                _index_failed[h] = _pdf_signature(h)
                failed.append(h)
        progress(len(hash_ids), len(hash_ids), "done")
        return {"indexed": len(hash_ids) - len(failed), "failed": failed}
    return _start_job(f"index:{project}", target, "index")


def _project_job(project: str) -> Dict:
    """One job state for the UI: a running sync, else a running index job, else the
    one that finished last."""
    sync, index = _job_state(f"sync:{project}"), _job_state(f"index:{project}")
    for j in (sync, index):
        if j.get("running"):
            return j
    started = [j for j in (sync, index) if "started" in j]
    if not started:
        return {"running": False}
    return max(started, key=lambda j: j.get("finished") or j.get("started") or 0)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _refs(name: str) -> ProjectRefs:
    path = _ctx["project_path"](name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found.")
    return ProjectRefs(path)


def project_hash_ids(name: str) -> List[str]:
    """Papers of a project (used to scope search, library and graph)."""
    return _refs(name).hash_ids()


@router.get("/api/projects/{name}/refs")
def get_refs(name: str):
    refs = _refs(name)
    data = refs.load()
    lib = _ctx["library_dir"]
    papers = []
    for p in data["papers"]:
        d = lib / p["hash_id"]
        papers.append({**p, "has_pdf": any(d.glob("*.pdf")),
                       "indexed": (d / "passages.json").exists()})
    return {"project": refs.dir.name, "zotero": data.get("zotero"), "papers": papers,
            "missing_pdf": data.get("missing_pdf", []), "job": _project_job(refs.dir.name)}


class LinkRequest(BaseModel):
    collection_key: str
    include_subcollections: bool = False


@router.put("/api/projects/{name}/zotero")
def link_zotero(name: str, req: LinkRequest):
    refs = _refs(name)
    collection = _require_reader().collection(req.collection_key)
    if not collection:
        raise HTTPException(status_code=404, detail="Zotero collection not found.")
    refs.link_zotero(collection, req.include_subcollections)
    return {"status": "linked", "zotero": refs.load().get("zotero"), "job": _sync_job(refs.dir.name)}


@router.delete("/api/projects/{name}/zotero")
def unlink_zotero(name: str, keep_papers: bool = True):
    refs = _refs(name)
    refs.unlink_zotero(keep_papers=keep_papers)
    return {"status": "unlinked"}


@router.post("/api/projects/{name}/sync")
def sync_project(name: str):
    refs = _refs(name)
    if not refs.load().get("zotero"):
        raise HTTPException(status_code=400, detail="Link a Zotero collection first.")
    return {"job": _sync_job(refs.dir.name)}


class PaperRequest(BaseModel):
    hash_id: str


def _valid_hash(hash_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", hash_id or ""):
        raise HTTPException(status_code=400, detail="Invalid paper id.")
    if not (_ctx["library_dir"] / hash_id).is_dir():
        raise HTTPException(status_code=404, detail="Paper not found in the library.")
    return hash_id


@router.post("/api/projects/{name}/papers")
def add_paper(name: str, req: PaperRequest):
    refs = _refs(name)
    h = _valid_hash(req.hash_id)
    try:
        meta = json.loads((_ctx["library_dir"] / h / "metadata.json").read_text())
    except (OSError, ValueError):
        meta = {}
    bib_key = _ctx["add_citation"](refs.dir.name, h)
    added = refs.add_paper(h, meta, bib_key)
    data = refs.load()
    data["excluded"] = [x for x in data.get("excluded", []) if x != h]
    refs.save(data)
    job = None
    if added and not (_ctx["library_dir"] / h / "passages.json").exists():
        job = _index_job(refs.dir.name, [h])
    return {"status": "added" if added else "already_in_project", "bib_key": bib_key, "job": job}


@router.delete("/api/projects/{name}/papers/{hash_id}")
def remove_paper(name: str, hash_id: str):
    refs = _refs(name)
    if not refs.remove_paper(hash_id):
        raise HTTPException(status_code=404, detail="This paper is not in the project.")
    return {"status": "removed"}


class EvidenceRequest(BaseModel):
    text: str
    per_paper: int = 3
    top_k: int = 10
    hash_ids: Optional[List[str]] = None   # restrict to some of the project's papers


def _paper_records(papers: List[Dict]) -> List[Dict]:
    """Project papers with the DOI and first-author surname from their metadata.json."""
    out = []
    for p in papers:
        try:
            meta = json.loads((_ctx["library_dir"] / p["hash_id"] / "metadata.json").read_text())
        except (OSError, ValueError):
            meta = {}
        authors = meta.get("authors") or []
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(",") if a.strip()]
        first = authors[0] if authors else ""
        if isinstance(first, dict):
            first = first.get("family") or first.get("name") or ""
        surname = p.get("first_author") or (str(first).split()[-1] if str(first).split() else "")
        out.append({**p, "doi": str(meta.get("doi") or "").lower(), "first_author": surname})
    return out


_resolver_cache: Dict[str, tuple] = {}


def _resolver(project_dir: Path, papers: List[Dict]):
    from project_module.citations import CitationResolver
    draft = project_dir / "draft.tex"
    try:
        stamp = (draft.stat().st_mtime_ns, tuple(sorted(p["hash_id"] for p in papers)))
    except OSError:
        stamp = (None, tuple(sorted(p["hash_id"] for p in papers)))
    cached = _resolver_cache.get(str(project_dir))
    if cached and cached[0] == stamp:
        return cached[1]
    text = draft.read_text(errors="ignore") if draft.exists() else ""
    resolver = CitationResolver(_paper_records(papers), text)
    _resolver_cache[str(project_dir)] = (stamp, resolver)
    return resolver


def _mark_cited(block: Dict, cited: List[str]):
    """Put the cited papers first and flag them."""
    for p in block["papers"]:
        p["cited"] = p["hash_id"] in cited
    block["papers"].sort(key=lambda p: (not p["cited"], -p["best_score"]))
    for t in block.get("top", []):
        t["cited"] = t["hash_id"] in cited


@router.post("/api/projects/{name}/evidence")
def find_evidence(name: str, req: EvidenceRequest):
    refs = _refs(name)
    data = refs.load()
    papers = data["papers"]
    if req.hash_ids:
        wanted = set(req.hash_ids)
        papers = [p for p in papers if p["hash_id"] in wanted]
    if not papers:
        raise HTTPException(status_code=400, detail="This project has no papers yet: link a Zotero "
                                                    "collection or add papers from the library.")
    if len(req.text) > 5000:
        raise HTTPException(status_code=413, detail="Select a shorter passage (at most 5000 characters).")
    enc = get_encoder()
    try:
        result = ev.find_evidence(req.text, papers, enc, _ctx["library_dir"],
                                  per_paper=max(1, min(req.per_paper, 10)), top_k=max(1, min(req.top_k, 50)))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Which project papers do the citation markers of the selection point to?
    resolver = _resolver(refs.dir, papers)
    all_cited, all_unresolved = [], []
    for part in result["parts"]:
        res = resolver.resolve(part["cites"])
        part["cited"], part["unresolved"] = res["papers"], res["unresolved"]
        _mark_cited(part, res["papers"])
    for label in ev.citation_labels(req.text):
        res = resolver.resolve(label)
        all_cited += [h for h in res["papers"] if h not in all_cited]
        all_unresolved += [u for u in res["unresolved"] if u not in all_unresolved]
    result["cited"], result["unresolved"] = all_cited, all_unresolved
    _mark_cited(result, all_cited)
    result["numbered_references"] = len(resolver.references)

    if result["not_indexed"]:
        lib = _ctx["library_dir"]
        todo = [h for h in result["not_indexed"] if any((lib / h).glob("*.pdf"))
                and not (h in _index_failed and _index_failed[h] == _pdf_signature(h))]
        result["index_failed"] = [h for h in result["not_indexed"] if h in _index_failed]
        result["job"] = _index_job(refs.dir.name, todo) if todo else _project_job(refs.dir.name)
    return result


class JudgePassage(BaseModel):
    hash_id: str = ""
    title: str = ""
    text: str
    before: str = ""
    after: str = ""


class JudgeRequest(BaseModel):
    claim: str
    passages: List[JudgePassage]


MAX_CLAIM_CHARS = 5000      # same bound as /evidence; the citation regexes run on the claim
MAX_PASSAGE_CHARS = 5000


JUDGE_SYSTEM = (
    "You check citations in a scientific manuscript. For each numbered passage from a cited paper, "
    "say whether it supports the claim, contradicts it, partly supports it, or is unrelated to it. "
    "Judge only from the passage text (with its context); do not use outside knowledge. "
    "Be strict: a passage on the same topic that says something different contradicts the claim.")


@router.post("/api/projects/{name}/evidence/judge")
def judge_evidence(name: str, req: JudgeRequest):
    """Ask the configured AI provider whether each passage supports the claim (opt-in;
    sends the claim and the passages to that provider)."""
    _refs(name)
    from ai_module import provider
    if not provider.is_enabled():
        raise HTTPException(status_code=400, detail="Set up an AI provider in ⚙ Settings to use this check.")
    if len(req.claim) > MAX_CLAIM_CHARS:
        raise HTTPException(status_code=413, detail="Select a shorter passage (at most 5000 characters).")
    passages = [p.model_copy(update={"text": p.text[:MAX_PASSAGE_CHARS],
                                     "before": p.before[:MAX_PASSAGE_CHARS],
                                     "after": p.after[:MAX_PASSAGE_CHARS]})
                for p in req.passages[:12]]
    if not passages or not ev.clean_claim(req.claim):
        raise HTTPException(status_code=400, detail="Nothing to check.")
    blocks = []
    for i, p in enumerate(passages):
        ctx = " ".join(x for x in (p.before, f"<<{p.text}>>", p.after) if x)
        blocks.append(f"[{i}] From \"{p.title[:150]}\": {ctx[:1500]}")
    prompt = (f"Claim: {ev.clean_claim(req.claim)[:1500]}\n\nPassages (the sentence to judge is between << >>):\n"
              + "\n\n".join(blocks)
              + '\n\nReturn JSON: {"verdicts": [{"i": 0, "verdict": "supports" | "contradicts" | "partly" | '
                '"unrelated", "reason": "one short sentence"}]} with one entry per passage.')
    try:
        out = provider.complete_json(prompt, system=JUDGE_SYSTEM, max_tokens=2000)
    except provider.AIError as e:
        raise HTTPException(status_code=502, detail=str(e))
    verdicts = out.get("verdicts", out) if isinstance(out, dict) else out
    clean = []
    for v in verdicts if isinstance(verdicts, list) else []:
        try:
            i = int(v.get("i"))
        except (TypeError, ValueError, AttributeError):
            continue
        verdict = str(v.get("verdict", "")).lower()
        if 0 <= i < len(passages) and verdict in {"supports", "contradicts", "partly", "unrelated"}:
            clean.append({"i": i, "verdict": verdict, "reason": str(v.get("reason", ""))[:300]})
    return {"verdicts": clean, "provider": provider.public_settings().get("label")}


class DocxRequest(BaseModel):
    filename: str = "manuscript.docx"
    data_base64: str


MAX_DOCX_BYTES = 30 * 1024 * 1024
MAX_DOCX_UNPACKED = 100 * 1024 * 1024     # guards against zip bombs
MAX_DOCX_TEXT = 5 * 1024 * 1024


@router.post("/api/projects/{name}/import-docx")
def import_docx(name: str, req: DocxRequest):
    _refs(name)
    if len(req.data_base64) > 4 * ((MAX_DOCX_BYTES + 2) // 3) + 4:
        raise HTTPException(status_code=413, detail="The file is larger than 30 MB.")
    try:
        raw = base64.b64decode(req.data_base64, validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="The file could not be read.")
    if len(raw) > MAX_DOCX_BYTES:
        raise HTTPException(status_code=413, detail="The file is larger than 30 MB.")
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            unpacked = sum(i.file_size for i in z.infolist())
    except Exception:
        raise HTTPException(status_code=400, detail="This is not a Word (.docx) file.")
    if unpacked > MAX_DOCX_UNPACKED:
        raise HTTPException(status_code=413, detail="The document is too large once unpacked.")
    try:
        import docx
        doc = docx.Document(io.BytesIO(raw))
    except Exception:
        raise HTTPException(status_code=400, detail="This is not a Word (.docx) file.")
    text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())[:MAX_DOCX_TEXT]
    return {"text": text, "paragraphs": text.count("\n\n") + 1 if text else 0}

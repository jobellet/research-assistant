"""The reference list of a project.

Each project folder may contain ``project.json``:

    {
      "zotero": {"collection_key": "ABCD1234", "collection_name": "...",
                 "include_subcollections": false, "last_sync": 1764000000},
      "papers": [{"hash_id": "...", "zotero_key": "...", "title": "...", "year": "2010",
                  "authors": "Smith and Jones", "bib_key": "smith2010example",
                  "source": "zotero" | "manual"}],
      "missing_pdf": [{"zotero_key": "...", "title": "..."}],
      "pdf_hashes": {"<zotero attachment key>": {"size": 123, "mtime": 1.0, "sha256": "..."}}
    }

The papers themselves live in the shared library (``library/<sha256>/``), so a
paper used by two projects is stored and indexed once.  Project folders are
private (git-ignored) like the library.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MANIFEST = "project.json"
_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(str(Path(path).resolve()), threading.Lock())


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _author_names(authors) -> List[str]:
    out = []
    for a in authors or []:
        if isinstance(a, dict):
            name = a.get("name") or f"{a.get('given', '')} {a.get('family', '')}".strip()
        else:
            name = str(a)
        if name.strip():
            out.append(name.strip())
    return out


def _surnames(authors) -> List[str]:
    """Family names; Zotero's own split is used when available ('van Dijk', not 'Dijk')."""
    out = []
    for a in authors or []:
        if isinstance(a, dict) and a.get("family"):
            out.append(a["family"].strip())
        else:
            name = a.get("name", "") if isinstance(a, dict) else str(a)
            if "," in name:                       # 'van Dijk, S.'
                out.append(name.split(",")[0].strip())
            elif name.split():
                out.append(name.split()[-1])
    return [n for n in out if n]


def _short_authors(authors) -> str:
    last = _surnames(authors)
    if not last:
        return ""
    if len(last) == 1:
        return last[0]
    if len(last) == 2:
        return f"{last[0]} and {last[1]}"
    return f"{last[0]} et al."


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^\w\s.,()&'-]", "_", Path(name).name).strip() or "paper.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name[:180]


class ProjectRefs:
    """Read and write the reference list (``project.json``) of one project folder."""

    def __init__(self, project_dir: Path):
        self.dir = Path(project_dir)
        self.path = self.dir / MANIFEST
        self.lock = _lock_for(self.dir)

    def load(self) -> Dict:
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict):
                raise ValueError
        except (OSError, ValueError):
            data = {}
        data.setdefault("papers", [])
        data.setdefault("missing_pdf", [])
        data.setdefault("pdf_hashes", {})
        return data

    def save(self, data: Dict):
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        tmp.replace(self.path)

    def hash_ids(self) -> List[str]:
        return [p["hash_id"] for p in self.load()["papers"] if p.get("hash_id")]

    def link_zotero(self, collection: Dict, include_subcollections: bool = False):
        with self.lock:
            data = self.load()
            old = (data.get("zotero") or {}).get("collection_key")
            data["zotero"] = {
                "collection_key": collection["key"],
                "collection_name": collection.get("path") or collection.get("name", ""),
                "include_subcollections": bool(include_subcollections),
                "last_sync": None,
            }
            if old and old != collection["key"]:
                # Papers of the previous collection are not part of the new one.
                data["papers"] = [p for p in data["papers"] if p.get("source") != "zotero"]
                data["missing_pdf"] = []
            self.save(data)

    def unlink_zotero(self, keep_papers: bool = True):
        with self.lock:
            data = self.load()
            data.pop("zotero", None)
            if keep_papers:
                for p in data["papers"]:
                    if p.get("source") == "zotero":
                        p["source"] = "manual"
            else:
                data["papers"] = [p for p in data["papers"] if p.get("source") != "zotero"]
            data["missing_pdf"] = []
            self.save(data)

    def add_paper(self, hash_id: str, meta: Dict, bib_key: Optional[str] = None) -> bool:
        """Add a library paper by hand. Returns False if it was already in the project."""
        with self.lock:
            data = self.load()
            for p in data["papers"]:
                if p.get("hash_id") == hash_id:
                    if bib_key and not p.get("bib_key"):
                        p["bib_key"] = bib_key
                        self.save(data)
                    return False
            data["papers"].append({
                "hash_id": hash_id, "title": meta.get("title", ""), "year": str(meta.get("year") or ""),
                "authors": _short_authors(meta.get("authors")),
                "first_author": (_surnames(meta.get("authors")) or [""])[0],
                "bib_key": bib_key, "source": "manual",
            })
            self.save(data)
            return True

    def remove_paper(self, hash_id: str) -> bool:
        with self.lock:
            data = self.load()
            n = len(data["papers"])
            data["papers"] = [p for p in data["papers"] if p.get("hash_id") != hash_id]
            if len(data["papers"]) == n:
                return False
            data.setdefault("excluded", [])
            if hash_id not in data["excluded"]:
                data["excluded"].append(hash_id)   # a Zotero sync will not bring it back
            self.save(data)
            return True


def _metadata_from_zotero(item: Dict, pdf_name: str) -> Dict:
    return {
        "title": item.get("title", ""),
        "authors": _author_names(item.get("authors")),
        "year": item.get("year", ""),
        "journal": item.get("journal", ""),
        "volume": item.get("volume", ""),
        "issue": item.get("issue", ""),
        "pages": item.get("pages", ""),
        "doi": item.get("doi", ""),
        "url": item.get("url", ""),
        "summary": item.get("abstract", ""),
        "keywords": item.get("tags", []),
        "pdf_filename": pdf_name,
        "zotero_key": item.get("key", ""),
        "source": "zotero",
    }


def sync_from_zotero(project_dir: Path, library_dir: Path, reader, *,
                     index_paper: Optional[Callable[[str, Dict], None]] = None,
                     index_passages: Optional[Callable[[str, Path], None]] = None,
                     add_citation: Optional[Callable[[str, Dict], Optional[str]]] = None,
                     extract_text: Optional[Callable[[Path], str]] = None,
                     progress: Optional[Callable[[int, int, str], None]] = None) -> Dict:
    """Bring a project's reference list up to date with its Zotero collection.

    For every item of the collection that has a PDF: the PDF is copied into the
    library (once; same content = same folder), ``metadata.json`` is written
    from Zotero's record (fields already present are kept), the full text is
    extracted, and the callbacks add the paper to the search index
    (``index_paper``), build its sentence index (``index_passages``) and add a
    BibTeX entry to the project (``add_citation``, which returns the key).
    Items removed from the collection leave the project (not the library).
    """
    refs = ProjectRefs(project_dir)
    library_dir = Path(library_dir)
    with refs.lock:
        data = refs.load()
    link = data.get("zotero")
    if not link:
        raise ValueError("This project is not linked to a Zotero collection.")
    items = reader.collection_items(link["collection_key"], link.get("include_subcollections", False))
    pdf_cache = dict(data.get("pdf_hashes", {}))
    excluded = set(data.get("excluded", []))
    old_by_key = {p.get("zotero_key"): p for p in data["papers"] if p.get("source") == "zotero"}

    zotero_papers, missing, added, errors = [], [], [], []
    for n, item in enumerate(items, start=1):
        label = item.get("title") or item["key"]
        if progress:
            progress(n - 1, len(items), label)
        pdf = reader.pdf_of(item)
        if not pdf:
            missing.append({"zotero_key": item["key"], "title": item.get("title", ""),
                            "year": item.get("year", ""), "authors": _short_authors(item.get("authors"))})
            continue
        try:
            att_key = next((a["key"] for a in item["attachments"] if a.get("path") == str(pdf)), str(pdf))
            st = pdf.stat()
            cached = pdf_cache.get(att_key)
            if cached and cached.get("size") == st.st_size and cached.get("mtime") == st.st_mtime:
                sha = cached["sha256"]
            else:
                sha = _sha256(pdf)
                pdf_cache[att_key] = {"size": st.st_size, "mtime": st.st_mtime, "sha256": sha}
            if sha in excluded:
                continue
            paper_dir = library_dir / sha
            paper_dir.mkdir(parents=True, exist_ok=True)
            pdfs = sorted(paper_dir.glob("*.pdf"))
            if pdfs:
                pdf_name = pdfs[0].name
            else:
                pdf_name = _safe_filename(pdf.name)
                shutil.copy2(pdf, paper_dir / pdf_name)
                (paper_dir / "source_info.txt").write_text(
                    f"source: Zotero\nzotero_item: {item['key']}\nfilename: {pdf.name}\n")

            meta_path = paper_dir / "metadata.json"
            zmeta = _metadata_from_zotero(item, pdf_name)
            try:
                meta = json.loads(meta_path.read_text())
                if not isinstance(meta, dict):
                    meta = {}
            except (OSError, ValueError):
                meta = {}
            changed = False
            for k, v in zmeta.items():
                if v and not meta.get(k):
                    meta[k] = v           # Zotero fills gaps; existing values are kept
                    changed = True
            if changed:
                meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

            text_path = paper_dir / "full_text.txt"
            if extract_text and not text_path.exists():
                try:
                    text_path.write_text(extract_text(paper_dir / pdf_name))
                except Exception as e:  # text is optional; the sentence index reads the PDF
                    logger.warning(f"Text extraction failed for {label}: {e}")

            # The paper is in the library now; the steps below are optional, so a
            # failure is reported but does not drop the paper from the project.
            def _step(name, fn, *args):
                try:
                    return fn(*args)
                except Exception as e:
                    logger.warning(f"Zotero sync: {name} failed for {label}: {e}")
                    errors.append({"zotero_key": item["key"], "title": item.get("title", ""),
                                   "step": name, "error": str(e)})
                    return None

            if index_paper:
                _step("index_paper", index_paper, sha, meta)
            if index_passages:
                _step("index_passages", index_passages, sha, paper_dir / pdf_name)

            old = old_by_key.get(item["key"]) or {}
            bib_key = old.get("bib_key")
            if add_citation and not bib_key:
                bib_key = _step("add_citation", add_citation, sha, meta) or None
            if item["key"] not in old_by_key:
                added.append(sha)
            zotero_papers.append({
                "hash_id": sha, "zotero_key": item["key"], "title": meta.get("title", ""),
                "year": str(meta.get("year") or ""),
                "authors": _short_authors(item.get("authors") or meta.get("authors")),
                "first_author": (_surnames(item.get("authors") or meta.get("authors")) or [""])[0],
                "bib_key": bib_key, "source": "zotero",
            })
        except Exception as e:
            logger.exception(f"Zotero sync failed for {label}")
            errors.append({"zotero_key": item["key"], "title": item.get("title", ""), "error": str(e)})
            prev = old_by_key.get(item["key"])
            if prev and prev.get("hash_id"):
                zotero_papers.append(prev)   # a transient failure keeps a paper already in the project

    with refs.lock:
        data = refs.load()   # re-read: papers may have been added by hand meanwhile
        cur = data.get("zotero") or {}
        if (not cur or cur.get("collection_key") != link.get("collection_key")
                or bool(cur.get("include_subcollections")) != bool(link.get("include_subcollections"))):
            # The project was unlinked or relinked while this sync ran: its results
            # belong to a link that no longer applies, so nothing is written.
            logger.info("Zotero sync discarded: the project's link changed during the sync")
            if progress:
                progress(len(items), len(items), "done")
            return {"items": len(items), "papers": 0, "added": [], "removed": [],
                    "missing_pdf": missing, "errors": errors, "aborted": True}
        excluded_now = set(data.get("excluded", []))
        zotero_papers = [p for p in zotero_papers if p.get("hash_id") not in excluded_now]
        added = [h for h in added if h not in excluded_now]
        seen = {p["hash_id"] for p in zotero_papers}
        manual = [p for p in data["papers"] if p.get("source") != "zotero" and p.get("hash_id") not in seen]
        removed = [p["hash_id"] for p in data["papers"]
                   if p.get("source") == "zotero" and p.get("hash_id") not in seen]
        data["papers"] = zotero_papers + manual
        data["missing_pdf"] = missing
        data["pdf_hashes"] = pdf_cache
        if data.get("zotero"):
            data["zotero"]["last_sync"] = int(time.time())
        refs.save(data)
    if progress:
        progress(len(items), len(items), "done")
    return {"items": len(items), "papers": len(zotero_papers), "added": added, "removed": removed,
            "missing_pdf": missing, "errors": errors}

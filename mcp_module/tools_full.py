"""Tools of the 'full' mode: they use the local app (semantic search, processing, projects) and can write.

Read-only tools are annotated ``readOnlyHint``; the ones that change something (add a paper, edit a project)
are annotated as such so assistants ask you before calling them. Nothing here deletes anything.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote
from typing import Any, Callable, Dict, List

MAX_TEXT = 60_000
PROJECT_RE = re.compile(r"[A-Za-z0-9 ._-]{1,60}")
READ = {"readOnlyHint": True, "openWorldHint": False}
READ_WEB = {"readOnlyHint": True, "openWorldHint": True}
WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
WRITE_WEB = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}


def _s(t, desc, **extra):
    return {"type": t, "description": desc, **extra}


def _schema(props: Dict, required: List[str]) -> Dict:
    return {"type": "object", "properties": props, "required": required}


ID = _s("string", "Library id, DOI or arXiv id of a paper in the library")
N = _s("integer", "Number of results (default 8, max 20)", minimum=1, maximum=20)
PROJECT = _s("string", "Project name (default 'default')")

# name -> (description, schema, annotations)
SPECS: Dict[str, Any] = {
    "check_in_library": (
        "Is this paper already in the library? Give a DOI, an arXiv id/URL, a title or an abstract. Returns the library "
        "paper when it matches exactly, otherwise the closest papers by meaning so near-duplicates are visible.",
        _schema({"doi": _s("string", "DOI"), "arxiv_id": _s("string", "arXiv id or URL"),
                 "title": _s("string", "Title"), "text": _s("string", "Abstract or any text of the paper")}, []), READ),
    "add_to_library": (
        "Add a paper to the library: downloads its open-access PDF from an arXiv id, arXiv URL or DOI and starts "
        "processing it (metadata, text, embeddings). Says if it is already in the library or if no open PDF exists. "
        "Use check_in_library first. Indexing takes a minute: poll processing_status.",
        _schema({"identifier": _s("string", "arXiv id, arXiv URL or DOI")}, ["identifier"]), WRITE_WEB),
    "processing_status": (
        "State of the background processing of newly added papers.", _schema({}, []), READ),
    "semantic_search": (
        "Search the library by meaning (not only by words). Good for 'papers that argue X' or 'evidence against Y'. "
        "Optional filters: year, author, journal.",
        _schema({"query": _s("string", "What to look for"), "n": N, "year": _s("integer", "Only this year"),
                 "author": _s("string", "Author name contains"), "journal": _s("string", "Journal contains")},
                ["query"]), READ),
    "similar_papers": (
        "Papers of the library most similar in meaning to one paper (by its title and abstract). To find papers that "
        "contradict or support it, call this, then read their abstracts (get_paper) or texts (read_paper_text) and judge.",
        _schema({"id": ID, "n": N}, ["id"]), READ),
    "read_paper_text": (
        "Extracted full text of a library paper, in chunks (offset and max_chars; at most 60000 characters per call).",
        _schema({"id": ID, "offset": _s("integer", "Start character (default 0)", minimum=0),
                 "max_chars": _s("integer", "Chunk size (default 20000)", minimum=1000, maximum=MAX_TEXT)}, ["id"]), READ),
    "library_stats": ("Number of papers in the library and how many are fully processed.", _schema({}, []), READ),
    "related_online": (
        "Papers outside the library related to a library paper (Semantic Scholar recommendations, OpenAlex related "
        "works, citing papers). Each result says if it is already in the library.",
        _schema({"id": ID, "n": N}, ["id"]), READ_WEB),
    "literature_for_text": (
        "Find literature relevant to a passage of a manuscript (searches online databases and flags papers already in the library).",
        _schema({"text": _s("string", "The passage"), "n": N}, ["text"]), READ_WEB),
    "graph_neighbors": (
        "The 50 nearest neighbours of a library paper by word usage (a local similarity graph).",
        _schema({"id": ID}, ["id"]), READ),
    "audit_claims": (
        "Check claims of a manuscript against an analysis text: marks each claim supported, contradicted or needs review.",
        _schema({"manuscript": _s("string", "Manuscript text"), "analysis": _s("string", "Analysis or results text")},
                ["manuscript", "analysis"]), READ),
    "list_projects": ("Writing projects (LaTeX draft + BibTeX) with their last modification.", _schema({}, []), READ),
    "get_draft": ("LaTeX draft of a project.", _schema({"project": PROJECT}, []), READ),
    "get_bib": ("BibTeX file of a project.", _schema({"project": PROJECT}, []), READ),
    "add_citation": (
        "Add a library paper to the BibTeX file of a project (same key scheme as the web page).",
        _schema({"id": ID, "project": PROJECT}, ["id"]), WRITE),
    "create_project": (
        "Create a new writing project.", _schema({"name": _s("string", "Project name")}, ["name"]), WRITE),
    "append_to_draft": (
        "Append text at the end of a project's LaTeX draft. It never replaces or deletes existing text.",
        _schema({"project": PROJECT, "text": _s("string", "LaTeX text to append")}, ["text"]), WRITE),
    "project_references": (
        "The papers of a project (its reference list: a linked Zotero collection and papers added by hand), "
        "with their BibTeX keys and whether their sentences are indexed for check_claim.",
        _schema({"project": PROJECT}, []), READ),
    "check_claim": (
        "Check a claim of the manuscript against the project's own papers: returns the sentences of those papers "
        "that best match it, with page numbers and the neighbouring sentences. Paste the sentence with its citation "
        "markers (',32', '[12]', '\\cite{key}' or '(Author, 2001)'): each cited part is then checked on its own and "
        "the cited paper comes first. Similar sentences can support OR contradict the claim: read them and judge.",
        _schema({"project": PROJECT, "text": _s("string", "The claim (one or a few sentences of the manuscript)"),
                 "per_paper": _s("integer", "Sentences per paper (default 3, max 6)", minimum=1, maximum=6)},
                ["text"]), READ),
    "audit_citations": (
        "Check ALL citations of a project's draft automatically. For every citing sentence and every cited part of it, "
        "returns the best-matching sentences of the cited paper (page numbers), flags citations whose reference is not "
        "in the project, citation numbers without a reference entry, references never cited, DOIs that Crossref does "
        "not know or whose record does not match the reference, parts where ANOTHER project paper matches better, and "
        "uncited sentences that closely match a project paper (possibly missing citations). The first call starts the "
        "audit (a few minutes); call again to get the report, page through it with offset/limit. Then judge each "
        "citation from the sentences: supported, inaccurate (the paper says something different), or unsupported.",
        _schema({"project": PROJECT,
                 "refresh": _s("boolean", "Start a new audit even if a report exists (default false)"),
                 "check_dois": _s("boolean", "Look the DOIs up in Crossref (default true)"),
                 "offset": _s("integer", "First citing sentence to return (default 0)", minimum=0),
                 "limit": _s("integer", "Citing sentences per call (default 10, max 30)", minimum=1, maximum=30)}, []),
        READ_WEB),
    "sync_project_zotero": (
        "Bring a project's papers up to date with its linked Zotero collection (copies new PDFs into the library, "
        "indexes them, adds BibTeX entries). Runs in the background: see project_references.",
        _schema({"project": PROJECT}, []), WRITE),
}


def _clip(obj: Any, limit: int = MAX_TEXT) -> str:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"\n[... truncated, {len(text) - limit} more characters]"


def _n(args, default=8) -> int:
    return max(1, min(int(args.get("n") or default), 20))


def _project(args) -> str:
    p = str(args.get("project") or "default").strip()
    if not PROJECT_RE.fullmatch(p) or p.startswith("."):
        raise ValueError("invalid project name")
    return p


def _pq(args) -> str:
    """Project name for a URL path."""
    return quote(_project(args), safe="")


def _evidence_summary(r: Dict) -> Dict:
    """Keep what an assistant needs: claim parts, cited papers first, sentences with pages."""
    def block(b):
        return {"claim": b.get("claim"), "cites": b.get("cites"),
                "not_in_project": [u.get("label") + (": " + u["reference"][:160] if u.get("reference") else "")
                                   for u in b.get("unresolved", [])],
                "papers": [{"title": p.get("title"), "authors": p.get("authors"), "year": p.get("year"),
                            "bib_key": p.get("bib_key"), "cited": p.get("cited", False),
                            "sentences": [{"page": s.get("page"), "similarity": s.get("similarity"),
                                           "text": s.get("text"), "context_before": s.get("before"),
                                           "context_after": s.get("after")} for s in p.get("passages", [])]}
                           for p in b.get("papers", []) if p.get("passages")]}
    out = {"whole_claim": block(r)}
    if r.get("parts"):
        out["cited_parts"] = [block(p) for p in r["parts"]]
    if r.get("not_indexed"):
        out["note"] = f"{len(r['not_indexed'])} paper(s) are still being indexed (word matches only for them)."
    return out


def _compact_citation(c: Dict) -> Dict:
    """A citing sentence of the audit report without the context sentences, texts shortened."""
    def ref(r):
        r = dict(r)
        if "best_sentences" in r:
            r["best_sentences"] = [{"page": x.get("page"), "similarity": x.get("similarity"),
                                    "text": (x.get("text") or "")[:400]} for x in r["best_sentences"]]
        if r.get("reference"):
            r["reference"] = r["reference"][:200]
        return r
    parts = []
    for p in c.get("parts", []):
        q = {"claim": p.get("claim"), "cites": p.get("cites"), "refs": [ref(r) for r in p.get("refs", [])]}
        if p.get("better_match_elsewhere"):
            b = p["better_match_elsewhere"]
            q["better_match_elsewhere"] = {k: (b.get(k) or "")[:400] if k == "text" else b.get(k)
                                           for k in ("title", "authors", "year", "page", "similarity", "text")}
        parts.append(q)
    return {"sentence_index": c.get("sentence_index"), "sentence": c.get("sentence"), "parts": parts}


def make_handlers(server) -> Dict[str, Callable[[Dict], str]]:
    """Handlers bound to an McpServer (which owns the library view and the app client)."""
    from mcp_module.server import _short

    def lib():
        if server.library is None:
            raise ValueError("library not available")
        return server.library

    def app():
        if server.app is None:
            raise ValueError("the research-assistant app is not configured")
        return server.app

    def resolve(args) -> Dict:
        m = lib().find(str(args.get("id", "")))
        if not m:
            raise ValueError("paper not found in the library")
        return m

    def hits(results: List[Dict], skip: str = "") -> List[Dict]:
        out = []
        for r in results or []:
            if r.get("hash_id") == skip:
                continue
            meta = dict(r.get("metadata") or {})
            item = _short({**meta, "summary": r.get("summary") or meta.get("summary", "")})
            item.update(id=r.get("hash_id", ""), score=round(float(r.get("score") or 0), 3))
            out.append(item)
        return out

    def check(args):
        from discovery_module import discover
        cand = {"doi": args.get("doi", ""), "arxiv_id": args.get("arxiv_id", ""), "title": args.get("title", "")}
        h = discover._match_library(cand, discover.library_index(lib().dir))
        exact = None
        if h:
            m = lib().find(h)
            exact = dict(_short(m), id=h) if m else None
        query = (args.get("text") or args.get("title") or "").strip()
        near = []
        if query and server.app is not None:
            near = hits(app().post("/api/search", {"query": query[:2000], "n_results": 4, "method": "semantic"}))
        return json.dumps({"in_library": bool(exact), "match": exact, "closest_by_meaning": near}, ensure_ascii=False)

    def add_to_library(args):
        ident = str(args.get("identifier", "")).strip()
        if not ident:
            raise ValueError("identifier is required")
        return _clip(app().post("/api/discover/fetch", {"identifier": ident, "process": True}))

    def semantic_search(args):
        body = {"query": str(args.get("query", "")).strip(), "n_results": _n(args), "method": "semantic"}
        for k in ("year", "author", "journal"):
            if args.get(k):
                body[k] = args[k]
        if not body["query"]:
            raise ValueError("query is required")
        return _clip(hits(app().post("/api/search", body)))

    def similar(args):
        m = resolve(args)
        text = f"{m.get('title', '')}. {m.get('summary', '')}".strip()[:2000]
        n = _n(args)
        res = app().post("/api/search", {"query": text, "n_results": n + 1, "method": "semantic"})
        return _clip(hits(res, skip=m["id"])[:n])

    def read_text(args):
        m = resolve(args)
        text = app().get(f"/api/library/text/{m['id']}").get("text", "")
        off = max(0, int(args.get("offset") or 0))
        size = max(1000, min(int(args.get("max_chars") or 20_000), MAX_TEXT))
        chunk = text[off:off + size]
        return json.dumps({"id": m["id"], "title": m.get("title", ""), "offset": off, "total_chars": len(text),
                           "next_offset": off + size if off + size < len(text) else None, "text": chunk},
                          ensure_ascii=False)

    def related(args):
        m = resolve(args)
        res = app().get(f"/api/discover/related/{m['id']}", {"limit": _n(args, 10)})
        return _clip([_short(c) for c in (res.get("results") if isinstance(res, dict) else res) or []])

    def for_text(args):
        res = app().post("/api/discover/text", {"text": str(args.get("text", "")), "limit": _n(args, 10)})
        return _clip([_short(c) for c in (res.get("results") if isinstance(res, dict) else res) or []])

    def neighbors(args):
        return _clip(app().get(f"/api/graph/neighbors/{resolve(args)['id']}"))

    def audit(args):
        return _clip(app().post("/api/audit/claims", {"manuscript": str(args.get("manuscript", "")),
                                                      "analysis": str(args.get("analysis", ""))}))

    def add_citation(args):
        m = resolve(args)
        return _clip(app().post("/api/citation/add", {"hash_id": m["id"], "project": _project(args)}))

    def append(args):
        proj = _project(args)
        text = str(args.get("text", ""))
        if not text.strip():
            raise ValueError("text is empty")
        cur = app().get(f"/api/projects/{quote(proj, safe='')}/draft")
        old = cur.get("content", "") if isinstance(cur, dict) else str(cur or "")
        sep = "" if not old or old.endswith("\n") else "\n"
        app().put(f"/api/projects/{quote(proj, safe='')}/draft", {"content": old + sep + text + ("" if text.endswith("\n") else "\n")})
        return json.dumps({"status": "appended", "project": proj, "added_chars": len(text)})

    def audit_citations(args):
        proj = _pq(args)
        state = app().get(f"/api/projects/{proj}/citation-audit")
        job, report = state.get("job") or {}, state.get("report")
        if job.get("running"):
            return json.dumps({"status": "running", "progress": f"{job.get('done', 0)}/{job.get('total', 0)}",
                               "hint": "call again in a minute"})
        if args.get("refresh") or not report:
            started = app().post(f"/api/projects/{proj}/citation-audit",
                                 {"check_dois": args.get("check_dois", True) is not False})
            return json.dumps({"status": "started", "job": started.get("job"),
                               "hint": "the audit takes a few minutes; call again without refresh"})
        off = max(0, int(args.get("offset") or 0))
        lim = max(1, min(int(args.get("limit") or 10), 30))
        cits = [_compact_citation(c) for c in report.get("citations", [])]
        while True:   # shrink the page until it fits (a truncated answer would be invalid JSON)
            out = {"summary": report.get("summary"), "note": report.get("note"),
                   "citations": cits[off:off + lim], "next_offset": off + lim if off + lim < len(cits) else None}
            if lim == 1 or len(json.dumps(out, ensure_ascii=False)) < MAX_TEXT // 2:
                break
            lim = max(1, lim // 2)
        if off == 0:
            out["reference_problems"] = [r for r in report.get("references", [])
                                         if not r.get("in_project") or not r.get("cited_in")
                                         or r.get("doi_differs_from_library")
                                         or (r.get("doi_check") or {}).get("status") not in (None, "ok")]
            out["possibly_missing"] = report.get("possibly_missing", [])
            out["not_indexed"] = report.get("not_indexed", [])
        return _clip(out)

    def check_claim(args):
        text = str(args.get("text", "")).strip()
        if not text:
            raise ValueError("text is empty")
        per = max(1, min(int(args.get("per_paper") or 3), 6))
        r = app().post(f"/api/projects/{_pq(args)}/evidence", {"text": text[:5000], "per_paper": per})
        return _clip(_evidence_summary(r))

    return {
        "check_in_library": check, "add_to_library": add_to_library,
        "processing_status": lambda a: _clip(app().get("/api/status")),
        "semantic_search": semantic_search, "similar_papers": similar, "read_paper_text": read_text,
        "library_stats": lambda a: _clip(app().get("/api/stats")),
        "related_online": related, "literature_for_text": for_text, "graph_neighbors": neighbors,
        "audit_claims": audit,
        "list_projects": lambda a: _clip(app().get("/api/projects")),
        "get_draft": lambda a: _clip(app().get(f"/api/projects/{_pq(a)}/draft")),
        "get_bib": lambda a: _clip(app().get(f"/api/projects/{_pq(a)}/bib")),
        "add_citation": add_citation,
        "create_project": lambda a: _clip(app().post("/api/projects", {"name": _project({"project": a.get("name")})})),
        "append_to_draft": append,
        "project_references": lambda a: _clip(app().get(f"/api/projects/{_pq(a)}/refs")),
        "check_claim": check_claim,
        "audit_citations": audit_citations,
        "sync_project_zotero": lambda a: _clip(app().post(f"/api/projects/{_pq(a)}/sync", {})),
    }

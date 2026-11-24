"""Regression tests for the project-references backend: scoped search, Zotero sync
robustness, background jobs, the Zotero snapshot, the project graph cache and
input bounds of the refs API. Everything uses fakes and invented data."""
import base64
import io
import json
import sqlite3
import threading
import time
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeCollection:
    """Mimics chromadb: query(ids=...) fails if any id is missing; get() filters."""

    def __init__(self, docs):
        self.docs = dict(docs)   # id -> (embedding, metadata, document)

    def get(self, ids=None, include=None):
        keys = [i for i in (ids if ids is not None else self.docs) if i in self.docs]
        out = {"ids": keys}
        include = include or []
        if "embeddings" in include:
            out["embeddings"] = [self.docs[k][0] for k in keys]
        if "metadatas" in include:
            out["metadatas"] = [self.docs[k][1] for k in keys]
        if "documents" in include:
            out["documents"] = [self.docs[k][2] for k in keys]
        return out

    def query(self, query_embeddings, n_results, include, ids=None, where=None):
        keys = list(ids) if ids is not None else list(self.docs)
        if any(k not in self.docs for k in keys):
            raise RuntimeError("Error executing plan: Internal error: Error finding id")
        keys = keys[:n_results]
        return {"ids": [keys], "metadatas": [[self.docs[k][1] for k in keys]],
                "distances": [[0.1] * len(keys)], "documents": [[self.docs[k][2] for k in keys]]}


class FakeEmbed:
    model_name = "fake-model"

    def __call__(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeDB:
    def __init__(self, docs):
        self.collection = FakeCollection(docs)
        self.embedding_fn = FakeEmbed()


def _doc(title):
    return ([1.0, 0.5, 0.2], {"title": title, "authors": "Smith", "year": "2001"}, "summary")


# ---------------------------------------------------------------------------
# Finding 0: scoped search with a paper not in Chroma
# ---------------------------------------------------------------------------
def test_scoped_search_skips_ids_missing_from_index(tmp_path, monkeypatch):
    from search_module.searcher import SemanticSearcher as Searcher
    s = Searcher.__new__(Searcher)
    s.db_manager = FakeDB({"p1": _doc("Tidal layers"), "p2": _doc("River deltas")})
    monkeypatch.setattr(s, "find_all_pdfs", lambda h, pdf_filename=None: [], raising=False)
    res = s.search("tides", n_results=5, ids=["p1", "missing", "p2"])
    assert sorted(r["hash_id"] for r in res) == ["p1", "p2"]
    assert s.search("tides", ids=["missing"]) == []
    assert s.search("tides", ids=[]) == []


# ---------------------------------------------------------------------------
# Findings 2 and 3: Zotero sync
# ---------------------------------------------------------------------------
class FakeReader:
    def __init__(self, root, keys, on_items=None):
        self.root, self.keys, self.on_items = root, keys, on_items

    def collection_items(self, key, sub=False):
        if self.on_items:
            self.on_items()
        items = []
        for k in self.keys:
            pdf = self.root / f"{k}.pdf"
            if not pdf.exists():
                pdf.write_bytes(b"%PDF-1.4 fake " + k.encode())
            items.append({"key": k, "title": f"Title {k}", "year": "1999",
                          "authors": [{"firstName": "Anna", "lastName": "Smith"}],
                          "attachments": [{"key": "A" + k, "path": str(pdf)}]})
        return items

    def pdf_of(self, item):
        return Path(item["attachments"][0]["path"])


def _project(tmp_path, collection_key="COLLA"):
    from project_module import ProjectRefs
    pdir, lib, zdir = tmp_path / "proj", tmp_path / "lib", tmp_path / "zot"
    pdir.mkdir(); lib.mkdir(); zdir.mkdir()
    refs = ProjectRefs(pdir)
    refs.link_zotero({"key": collection_key, "name": "Collection A"})
    return refs, pdir, lib, zdir


def test_sync_keeps_paper_when_optional_step_fails(tmp_path):
    from project_module import sync_from_zotero
    refs, pdir, lib, zdir = _project(tmp_path)

    def bad(*a):
        raise RuntimeError("cannot open PDF")
    res = sync_from_zotero(pdir, lib, FakeReader(zdir, ["K1", "K2"]),
                           index_paper=bad, index_passages=bad, add_citation=bad)
    assert res["papers"] == 2
    assert len(refs.hash_ids()) == 2
    assert {e["step"] for e in res["errors"]} == {"index_paper", "index_passages", "add_citation"}


def test_sync_keeps_existing_paper_on_fatal_item_error(tmp_path, monkeypatch):
    from project_module import sync_from_zotero, refs as refs_mod
    refs, pdir, lib, zdir = _project(tmp_path)
    reader = FakeReader(zdir, ["K1"])
    sync_from_zotero(pdir, lib, reader, add_citation=lambda h, m: "smith1999")
    before = refs.load()["papers"]
    assert len(before) == 1

    def boom(path):
        raise OSError("disk error")
    monkeypatch.setattr(refs_mod, "_sha256", boom)
    (zdir / "K1.pdf").write_bytes(b"%PDF-1.4 changed")   # cache miss: hashing is needed
    res = sync_from_zotero(pdir, lib, reader)
    assert res["errors"] and refs.load()["papers"][0]["hash_id"] == before[0]["hash_id"]
    assert refs.load()["papers"][0]["bib_key"] == "smith1999"


def test_sync_discarded_when_relinked_during_sync(tmp_path):
    from project_module import sync_from_zotero
    refs, pdir, lib, zdir = _project(tmp_path)
    reader = FakeReader(zdir, ["K1", "K2"])

    def relink_midway(h, meta):
        if refs.load()["zotero"]["collection_key"] == "COLLA":
            refs.link_zotero({"key": "COLLB", "name": "Collection B"})
    res = sync_from_zotero(pdir, lib, reader, index_paper=relink_midway)
    assert res.get("aborted")
    data = refs.load()
    assert data["zotero"]["collection_key"] == "COLLB"
    assert data["zotero"]["last_sync"] is None
    assert data["papers"] == []


def test_sync_discarded_when_unlinked_during_sync(tmp_path):
    from project_module import sync_from_zotero
    refs, pdir, lib, zdir = _project(tmp_path)
    res = sync_from_zotero(pdir, lib, FakeReader(zdir, ["K1"]),
                           index_paper=lambda h, m: refs.unlink_zotero(keep_papers=False))
    assert res.get("aborted") and refs.load()["papers"] == [] and not refs.load().get("zotero")


def test_sync_respects_removal_during_sync(tmp_path):
    from project_module import sync_from_zotero
    refs, pdir, lib, zdir = _project(tmp_path)
    reader = FakeReader(zdir, ["K1", "K2"])
    sync_from_zotero(pdir, lib, reader)
    victim = refs.hash_ids()[0]

    def remove_once(h, meta):
        if victim in refs.hash_ids():
            refs.remove_paper(victim)
    sync_from_zotero(pdir, lib, reader, index_paper=remove_once)
    assert victim not in refs.hash_ids() and len(refs.hash_ids()) == 1


# ---------------------------------------------------------------------------
# Findings 3 and 4: background jobs
# ---------------------------------------------------------------------------
def _wait_job(refs_api, name):
    for _ in range(200):
        st = refs_api._job_state(name)
        if not st.get("running"):
            return st
        time.sleep(0.02)
    raise AssertionError("job did not finish")


@pytest.fixture
def api_ctx(tmp_path, monkeypatch):
    from server_module import refs_api
    projects, lib = tmp_path / "projects", tmp_path / "lib"
    (projects / "paper").mkdir(parents=True)
    lib.mkdir()
    monkeypatch.setattr(refs_api, "_jobs", {})
    monkeypatch.setattr(refs_api, "_index_failed", {})
    monkeypatch.setattr(refs_api, "_ctx", {})
    refs_api.configure(project_path=lambda n: projects / n, get_searcher=lambda: None,
                       library_dir=lib, on_library_changed=lambda: None,
                       add_citation=lambda p, h: None)
    return refs_api, lib


def test_index_job_continues_after_unreadable_pdf(api_ctx, monkeypatch):
    refs_api, lib = api_ctx
    for h in ("h1", "h2", "h3"):
        (lib / h).mkdir()
        (lib / h / "a.pdf").write_bytes(b"x")
    done = []

    def fake_index(h, pdf_path=None, force=False):
        if h == "h1":
            raise RuntimeError("cannot open broken document")
        done.append(h)
    monkeypatch.setattr(refs_api, "_index_passages", fake_index)
    refs_api._index_job("paper", ["h1", "h2", "h3"])
    st = _wait_job(refs_api, "index:paper")
    assert st["error"] is None and st["result"]["failed"] == ["h1"]
    assert done == ["h2", "h3"]
    assert refs_api._index_failed["h1"] == refs_api._pdf_signature("h1")


def test_sync_and_index_use_separate_slots_and_sync_reruns(api_ctx):
    refs_api = api_ctx[0]
    release, runs = threading.Event(), []

    def blocking(progress):
        release.wait(5)
        return {}
    refs_api._start_job("index:paper", blocking, "index")

    def sync_target(progress):
        runs.append(1)
        if len(runs) == 1:
            release.wait(5)
        return {"n": len(runs)}
    st = refs_api._start_job("sync:paper", sync_target, "sync", rerun=True)
    assert st["running"] and st["kind"] == "sync"     # not swallowed by the index job
    assert refs_api._project_job("paper")["kind"] == "sync"
    refs_api._start_job("sync:paper", sync_target, "sync", rerun=True)   # requested again
    release.set()
    st = _wait_job(refs_api, "sync:paper")
    assert len(runs) == 2 and st["result"] == {"n": 2}
    _wait_job(refs_api, "index:paper")


# ---------------------------------------------------------------------------
# Findings 16 and 19: input bounds
# ---------------------------------------------------------------------------
def test_judge_rejects_overlong_claim(api_ctx, monkeypatch):
    refs_api = api_ctx[0]
    from ai_module import provider
    monkeypatch.setattr(provider, "is_enabled", lambda: True)
    called = []
    monkeypatch.setattr(provider, "complete_json", lambda *a, **k: called.append(a) or {"verdicts": []})
    req = refs_api.JudgeRequest(claim="(" + "Ab 1999;" * 700, passages=[{"text": "x"}])
    with pytest.raises(HTTPException) as e:
        refs_api.judge_evidence("paper", req)
    assert e.value.status_code == 413 and not called


def test_judge_truncates_long_passages(api_ctx, monkeypatch):
    refs_api = api_ctx[0]
    from ai_module import provider
    monkeypatch.setattr(provider, "is_enabled", lambda: True)
    monkeypatch.setattr(provider, "public_settings", lambda: {"label": "fake"})
    prompts = []
    monkeypatch.setattr(provider, "complete_json",
                        lambda prompt, **k: prompts.append(prompt) or {"verdicts": []})
    req = refs_api.JudgeRequest(claim="Area X shows feature alpha.",
                                passages=[{"text": "y" * 100000, "before": "b" * 100000}])
    refs_api.judge_evidence("paper", req)
    assert len(prompts[0]) < 10000


def test_import_docx_rejects_oversized_payload(api_ctx):
    refs_api = api_ctx[0]
    big = "A" * (4 * ((refs_api.MAX_DOCX_BYTES + 2) // 3) + 8)
    with pytest.raises(HTTPException) as e:
        refs_api.import_docx("paper", refs_api.DocxRequest(data_base64=big))
    assert e.value.status_code == 413


def test_import_docx_rejects_zip_bomb(api_ctx):
    refs_api = api_ctx[0]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"\0" * (refs_api.MAX_DOCX_UNPACKED + 1024))
    data = base64.b64encode(buf.getvalue()).decode()
    with pytest.raises(HTTPException) as e:
        refs_api.import_docx("paper", refs_api.DocxRequest(data_base64=data))
    assert e.value.status_code == 413


def test_import_docx_still_reads_a_small_document(api_ctx):
    docx = pytest.importorskip("docx")
    refs_api = api_ctx[0]
    d = docx.Document()
    d.add_paragraph("Area X shows feature alpha (Smith, 1999).")
    buf = io.BytesIO()
    d.save(buf)
    out = refs_api.import_docx("paper", refs_api.DocxRequest(
        data_base64=base64.b64encode(buf.getvalue()).decode()))
    assert "feature alpha" in out["text"]


# ---------------------------------------------------------------------------
# Finding 7: Zotero snapshot under concurrent use
# ---------------------------------------------------------------------------
def test_zotero_snapshot_refresh_is_thread_safe(tmp_path):
    from zotero_module import ZoteroReader
    src = tmp_path / "zotero.sqlite"
    con = sqlite3.connect(str(src))
    con.execute("CREATE TABLE t (x TEXT)")
    con.executemany("INSERT INTO t VALUES (?)", [("v" * 500,) for _ in range(20000)])
    con.commit(); con.close()
    reader = ZoteroReader(data_dir=tmp_path, cache_seconds=0)
    errors, stop = [], threading.Event()

    def use():
        for _ in range(15):
            try:
                c = reader._connect()
                c.execute("SELECT count(*) FROM t").fetchone()
                c.close()
            except Exception as e:   # pragma: no cover - the failure being guarded against
                errors.append(e)

    def touch():
        n = 0
        while not stop.is_set():
            n += 1
            import os
            os.utime(src, ns=(n * 10**9, n * 10**9))
            time.sleep(0.005)
    t = threading.Thread(target=touch); t.start()
    workers = [threading.Thread(target=use) for _ in range(4)]
    for w in workers: w.start()
    for w in workers: w.join()
    stop.set(); t.join()
    reader.close()
    assert errors == []


# ---------------------------------------------------------------------------
# Finding 8: project graph cache
# ---------------------------------------------------------------------------
def test_project_graph_cache_rebuilds_when_paper_gets_indexed(tmp_path):
    pytest.importorskip("numpy")
    from graph_module.graph_builder import build_semantic_graph
    db = FakeDB({"a": ([1.0, 0.0, 0.1], {"title": "Paper A"}, "s"),
                 "b": ([0.0, 1.0, 0.1], {"title": "Paper B"}, "s")})
    cache = tmp_path / "graph_cache.json"
    g1 = build_semantic_graph(db, ids=["a", "b", "c"], cache_path=cache)
    assert g1["stats"]["n_nodes"] == 2
    db.collection.docs["c"] = ([0.5, 0.5, 0.1], {"title": "Paper C"}, "s")
    g2 = build_semantic_graph(db, ids=["a", "b", "c"], cache_path=cache)
    assert g2["stats"]["n_nodes"] == 3


def test_library_change_drops_project_graph_caches(tmp_path, monkeypatch):
    from server_module import main
    import config
    projects = tmp_path / "projects"
    for p in ("one", "two"):
        (projects / p).mkdir(parents=True)
        (projects / p / "graph_cache.json").write_text("{}")
        (projects / p / "draft.tex").write_text("x")
    monkeypatch.setattr(main, "PROJECTS_DIR", projects)
    monkeypatch.setattr(main, "bow_searcher", None)
    monkeypatch.setattr(main, "searcher", None)
    monkeypatch.setattr(config, "CITATION_GRAPH_PATH", tmp_path / "citations.json")
    main._on_library_changed()
    assert not list(projects.glob("*/graph_cache.json"))
    assert (projects / "one" / "draft.tex").exists()

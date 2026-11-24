"""Projects linked to a Zotero collection, and sentence-level evidence search.

Everything runs on a small fake Zotero database and generated PDFs; the
embedding model is replaced by a deterministic bag-of-words encoder.
"""
import hashlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np
import pytest

fitz = pytest.importorskip("fitz")

from evidence_module import passages as ev
from project_module import ProjectRefs, sync_from_zotero
from zotero_module import ZoteroReader, ZoteroError

PAPERS = {
    "AAAA1111": ("Encoding of tidal patterns by coastal sediment layers", "1985",
                 [("Anna", "Smith"), ("Carl", "Jones")], "10.5555/test.0001",
                 ["Sediment cores in zone 7a record tidal cycles.",
                  "The thickness of these layers is modulated by the angle of the slope, forming planar growth bands.",
                  "Growth bands indicate that layers grow best during spring tides.",
                  "We sampled two estuaries during a summer field campaign."]),
    "BBBB2222": ("Representation of the river delta in the northern wetland area", "2001",
                 [("Eva", "van Dijk"), ("Piotr", "Novak")], "10.5555/test.0002",
                 ["Channels in Area X are wide and mostly located in the outer delta.",
                  "The central basin and the inner lagoon are only sparsely represented in Area X.",
                  "Channel width increases with distance from the coast.",
                  "References"]),
    "CCCC3333": ("Attention, intention, and priority in wetland restoration", "2010",
                 [("Lucia", "Lopez"), ("Mark", "Brown")], "10.5555/test.0003",
                 ["We propose that Area X acts as a habitat map of the delta.",
                  "The habitat map combines water depth and salinity.",
                  "Nesting sites are selected from the peak of the habitat map."]),
}


def make_pdf(path: Path, sentences):
    doc = fitz.open()
    for chunk in (sentences[:2], sentences[2:]):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 550, 800), " ".join(chunk), fontsize=11)
    doc.save(str(path))


SCHEMA = """
CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT);
CREATE TABLE groups (groupID INTEGER PRIMARY KEY, libraryID INT, name TEXT);
CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INT, libraryID INT, key TEXT);
CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value);
CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
CREATE TABLE itemCreators (itemID INT, creatorID INT, creatorTypeID INT, orderIndex INT);
CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT,
                          parentCollectionID INT, libraryID INT, key TEXT);
CREATE TABLE collectionItems (collectionID INT, itemID INT, orderIndex INT);
CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INT, linkMode INT,
                              contentType TEXT, path TEXT);
CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY);
CREATE TABLE deletedCollections (collectionID INTEGER PRIMARY KEY);
CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE itemTags (itemID INT, tagID INT);
"""


class FakeZotero:
    """Writes a minimal Zotero data folder (zotero.sqlite + storage/)."""

    def __init__(self, root: Path):
        self.root = root
        (root / "storage").mkdir(parents=True)
        self.db = root / "zotero.sqlite"
        con = sqlite3.connect(self.db)
        con.executescript(SCHEMA)
        con.executemany("INSERT INTO itemTypes VALUES (?, ?)",
                        [(1, "journalArticle"), (2, "attachment"), (3, "note")])
        con.executemany("INSERT INTO fields VALUES (?, ?)",
                        [(1, "title"), (2, "date"), (3, "DOI"), (4, "publicationTitle"), (5, "abstractNote")])
        con.executemany("INSERT INTO creatorTypes VALUES (?, ?)", [(1, "author"), (2, "editor")])
        con.execute("INSERT INTO libraries VALUES (1, 'user')")
        con.execute("INSERT INTO collections VALUES (1, 'Wetlands', NULL, 1, 'COLL0001')")
        con.execute("INSERT INTO collections VALUES (2, 'Sub', 1, 1, 'COLL0002')")
        con.execute("INSERT INTO collections VALUES (3, 'Old', NULL, 1, 'COLL0003')")
        con.execute("INSERT INTO deletedCollections VALUES (3)")
        con.commit()
        con.close()
        self.next_id = 100

    def add_item(self, key, collection_id=1, with_pdf=True):
        title, year, authors, doi, sentences = PAPERS[key]
        con = sqlite3.connect(self.db)
        iid = self.next_id
        self.next_id += 10
        con.execute("INSERT INTO items VALUES (?, 1, 1, ?)", (iid, key))
        for fid, value in ((1, title), (2, f"{year}-05-01"), (3, doi), (4, "J Test"), (5, "An abstract.")):
            con.execute("INSERT INTO itemDataValues (value) VALUES (?)", (value,))
            vid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            con.execute("INSERT INTO itemData VALUES (?, ?, ?)", (iid, fid, vid))
        for n, (first, last) in enumerate(authors):
            con.execute("INSERT INTO creators (firstName, lastName) VALUES (?, ?)", (first, last))
            cid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            con.execute("INSERT INTO itemCreators VALUES (?, ?, 1, ?)", (iid, cid, n))
        con.execute("INSERT INTO collectionItems VALUES (?, ?, 0)", (collection_id, iid))
        if with_pdf:
            att_key = "P" + key[1:]
            con.execute("INSERT INTO items VALUES (?, 2, 1, ?)", (iid + 1, att_key))
            con.execute("INSERT INTO itemAttachments VALUES (?, ?, 0, 'application/pdf', ?)",
                        (iid + 1, iid, f"storage:{key}.pdf"))
            (self.root / "storage" / att_key).mkdir()
            make_pdf(self.root / "storage" / att_key / f"{key}.pdf", sentences)
        # a note must never show up as a paper
        con.execute("INSERT INTO items VALUES (?, 3, 1, ?)", (iid + 2, "N" + key[1:]))
        con.execute("INSERT INTO collectionItems VALUES (?, ?, 1)", (collection_id, iid + 2))
        con.commit()
        con.close()
        return iid

    def remove_from_collection(self, iid):
        con = sqlite3.connect(self.db)
        con.execute("DELETE FROM collectionItems WHERE itemID = ?", (iid,))
        con.commit()
        con.close()


def bow_encoder():
    """Deterministic stand-in for the embedding model: hashed bag of words."""
    def encode(texts, kind):
        out = np.zeros((len(texts), 256), dtype=np.float32)
        for r, t in enumerate(texts):
            for w in re.findall(r"[a-z]{3,}", t.lower()):
                out[r, int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1
        n = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(n, 1e-9)
    encode.model_id = "bow-test"
    return encode


@pytest.fixture
def zotero(tmp_path):
    return FakeZotero(tmp_path / "Zotero")


# ---------------------------------------------------------------- reader

def test_reader_lists_collections_and_items(zotero):
    a = zotero.add_item("AAAA1111")
    zotero.add_item("BBBB2222", collection_id=2)
    zotero.add_item("CCCC3333", with_pdf=False)
    r = ZoteroReader(zotero.root, cache_seconds=0)
    cols = {c["key"]: c for c in r.collections()}
    assert set(cols) == {"COLL0001", "COLL0002"}            # trashed collection hidden
    assert cols["COLL0002"]["path"] == "Wetlands / Sub"
    items = r.collection_items("COLL0001")
    assert [i["key"] for i in items] == ["AAAA1111", "CCCC3333"]   # no notes
    first = items[0]
    assert first["year"] == "1985" and first["doi"] == "10.5555/test.0001"
    assert first["authors"][0] == {"given": "Anna", "family": "Smith"}
    assert r.pdf_of(first).name == "AAAA1111.pdf"
    assert r.pdf_of(items[1]) is None
    assert {i["key"] for i in r.collection_items("COLL0001", include_subcollections=True)} == \
        {"AAAA1111", "BBBB2222", "CCCC3333"}
    with pytest.raises(ZoteroError):
        r.collection_items("NOPE")
    # the live database is never modified, and changes are picked up
    zotero.remove_from_collection(a)
    assert [i["key"] for i in r.collection_items("COLL0001")] == ["CCCC3333"]


def test_reader_without_zotero(tmp_path):
    with pytest.raises(ZoteroError):
        ZoteroReader(tmp_path)


# ---------------------------------------------------------------- text

def test_clean_claim_removes_citation_markers():
    c = ("the northern wetland area (Area X), characterized by wide outer channels, "
         "sparse inner coverage,32 seasonal salinity bands,33 and habitat-map or "
         "nesting functions,9,34 is expected")
    out = ev.clean_claim(c)
    assert "32" not in out and "33" not in out and "34" not in out
    assert "sparse inner coverage, seasonal" in out
    assert ev.clean_claim("silt14 and Z4 [3, 5-7] \\cite{a,b} (Lopez and Brown, 2010) in B12.") \
        == "silt and Z4 in B12."
    assert "80 px" in ev.clean_claim("small steps (<2 mm, i.e., <80 px)7–9 that")


def test_split_sentences_keeps_abbreviations():
    s = ev.split_sentences("Smith et al. showed growth bands (Fig. 2) in zone 7a of estuaries. "
                           "The second sentence is here now. Short one.")
    assert s == ["Smith et al. showed growth bands (Fig. 2) in zone 7a of estuaries.",
                 "The second sentence is here now."]


def test_reference_list_is_not_indexed(tmp_path):
    pages = ["Growth bands are planar in zone 7a sediments.\nIntro text goes on here for a while. " * 5,
             "More results about the growth bands of sediments.\nReferences\nSmith AB (1985) Growth bands in 7a. Science."]
    meta = ev.build_passage_index(tmp_path, bow_encoder(), pages=pages)
    assert not any("Science" in s["t"] for s in meta["sentences"])
    assert {s["p"] for s in meta["sentences"]} == {1, 2}


# ---------------------------------------------------------------- sync + evidence

def _sync(project_dir, library, reader, enc, cites=None):
    def add_citation(h, meta):
        if cites is not None:
            cites.append(h)
        return "key_" + h[:6]
    return sync_from_zotero(project_dir, library, reader,
                            index_passages=lambda h, pdf: ev.build_passage_index(library / h, enc, pdf_path=pdf),
                            add_citation=add_citation, extract_text=lambda p: "text")


def test_sync_adds_updates_and_removes_papers(tmp_path, zotero):
    a = zotero.add_item("AAAA1111")
    zotero.add_item("BBBB2222")
    zotero.add_item("CCCC3333", with_pdf=False)
    reader = ZoteroReader(zotero.root, cache_seconds=0)
    project, library = tmp_path / "projects" / "p", tmp_path / "library"
    project.mkdir(parents=True)
    library.mkdir()
    refs = ProjectRefs(project)
    refs.link_zotero(reader.collection("COLL0001"))
    enc, cites = bow_encoder(), []

    r1 = _sync(project, library, reader, enc, cites)
    assert r1["papers"] == 2 and len(r1["added"]) == 2 and not r1["errors"]
    data = refs.load()
    assert [m["zotero_key"] for m in data["missing_pdf"]] == ["CCCC3333"]
    for p in data["papers"]:
        d = library / p["hash_id"]
        meta = json.loads((d / "metadata.json").read_text())
        assert meta["source"] == "zotero" and meta["zotero_key"] == p["zotero_key"]
        assert (d / "passages.json").exists() and (d / "full_text.txt").exists()
        assert p["bib_key"] == "key_" + p["hash_id"][:6]
    assert data["zotero"]["last_sync"]

    # second sync: nothing new, no new BibTeX entries
    r2 = _sync(project, library, reader, enc, cites)
    assert r2["added"] == [] and len(cites) == 2

    # a paper added by hand survives syncs; one removed from Zotero leaves the project
    manual = library / "manual1"
    manual.mkdir()
    refs.add_paper("manual1", {"title": "Hand-picked", "authors": ["A B"]}, "hand2020")
    zotero.remove_from_collection(a)
    r3 = _sync(project, library, reader, enc)
    assert len(r3["removed"]) == 1
    keys = {p.get("zotero_key") or p["hash_id"] for p in refs.load()["papers"]}
    assert keys == {"BBBB2222", "manual1"}
    assert (library / r3["removed"][0]).exists()          # never deleted from the library


def test_existing_metadata_is_kept(tmp_path, zotero):
    zotero.add_item("AAAA1111")
    reader = ZoteroReader(zotero.root, cache_seconds=0)
    pdf = reader.pdf_of(reader.collection_items("COLL0001")[0])
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    library = tmp_path / "library"
    (library / sha).mkdir(parents=True)
    (library / sha / "metadata.json").write_text(json.dumps({"title": "My curated title", "doi": ""}))
    project = tmp_path / "p"
    project.mkdir()
    ProjectRefs(project).link_zotero(reader.collection("COLL0001"))
    sync_from_zotero(project, library, reader)
    meta = json.loads((library / sha / "metadata.json").read_text())
    assert meta["title"] == "My curated title"             # kept
    assert meta["doi"] == "10.5555/test.0001"        # gap filled from Zotero
    assert any((library / sha).glob("*.pdf"))


def test_evidence_finds_the_matching_sentence(tmp_path, zotero):
    for k in PAPERS:
        zotero.add_item(k)
    reader = ZoteroReader(zotero.root, cache_seconds=0)
    project, library = tmp_path / "p", tmp_path / "library"
    project.mkdir()
    library.mkdir()
    ProjectRefs(project).link_zotero(reader.collection("COLL0001"))
    enc = bow_encoder()
    _sync(project, library, reader, enc)
    papers = ProjectRefs(project).load()["papers"]

    r = ev.find_evidence("Area X has a sparse representation of the inner lagoon and central basin,32", papers,
                         enc, library, per_paper=2)
    assert "32" not in r["claim"]
    best = r["top"][0]
    assert "sparsely represented" in best["text"] and best["page"] in (1, 2)
    assert r["papers"][0]["title"].startswith("Representation")
    assert best["before"] or best["after"]                 # context sentences

    r = ev.find_evidence("slope angle growth bands of coastal sediment layers", papers, enc, library)
    assert "growth bands" in r["top"][0]["text"]

    # a paper without an index falls back to word matching, and is reported
    victim = papers[0]["hash_id"]
    (library / victim / "passages.json").unlink()
    (library / victim / "full_text.txt").write_text("The habitat map is in Area X. " * 3)
    r = ev.find_evidence("habitat map in Area X", papers, enc, library)
    assert victim in r["not_indexed"]
    assert any(p.get("method") == "words" for p in r["papers"])

    with pytest.raises(ValueError):
        ev.find_evidence("32", papers, enc, library)


# ---------------------------------------------------------------- API

class FakeCollection:
    def __init__(self):
        self.docs = {}

    def get(self, ids=None, include=None, **kw):
        ids = [i for i in (ids or list(self.docs)) if i in self.docs]
        return {"ids": ids, "metadatas": [self.docs[i]["meta"] for i in ids],
                "embeddings": [self.docs[i]["emb"] for i in ids], "documents": ["" for _ in ids]}


class FakeDB:
    def __init__(self):
        self.collection = FakeCollection()

    def index_document(self, hash_id, metadata, text_content=None):
        v = bow_encoder()([metadata.get("title", "")], "document")[0]
        self.collection.docs[hash_id] = {"meta": {"title": metadata.get("title", ""), "authors": "",
                                                  "year": metadata.get("year", "")}, "emb": v.tolist()}


class FakeSearcher:
    def __init__(self):
        self.db_manager = FakeDB()


@pytest.fixture
def api(tmp_path, zotero, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from server_module import refs_api

    for k in PAPERS:
        zotero.add_item(k)
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(zotero.root))
    monkeypatch.setattr(refs_api, "_reader", None)
    monkeypatch.setattr(refs_api, "_encoder", bow_encoder())
    projects, library = tmp_path / "projects", tmp_path / "library"
    (projects / "paper").mkdir(parents=True)
    (projects / "paper" / "references.bib").write_text("")
    library.mkdir()
    searcher, changed = FakeSearcher(), []
    refs_api.configure(project_path=lambda n: projects / n, get_searcher=lambda: searcher,
                       library_dir=library, on_library_changed=lambda: changed.append(1),
                       add_citation=lambda p, h: "cite_" + h[:4])
    app = FastAPI()
    app.include_router(refs_api.router)
    monkeypatch.setattr("server_module.auth.SERVER_PASSWORD", "pw")
    client = TestClient(app, headers={"x-auth-token": "pw"})
    client.searcher, client.changed, client.library = searcher, changed, library
    return client


def _wait(client, project="paper"):
    for _ in range(200):
        job = client.get(f"/api/projects/{project}/refs").json()["job"]
        if not job.get("running"):
            return job
        time.sleep(0.05)
    raise AssertionError("sync did not finish")


def test_api_link_sync_and_evidence(api):
    assert api.get("/api/zotero/status").json()["available"] is True
    cols = api.get("/api/zotero/collections").json()["collections"]
    assert [c["key"] for c in cols] == ["COLL0001", "COLL0002"]
    assert api.put("/api/projects/paper/zotero", json={"collection_key": "NOPE"}).status_code == 404
    r = api.put("/api/projects/paper/zotero", json={"collection_key": "COLL0001"})
    assert r.status_code == 200
    job = _wait(api)
    assert job["error"] is None and job["result"]["papers"] == 3
    refs = api.get("/api/projects/paper/refs").json()
    assert refs["zotero"]["collection_name"] == "Wetlands"
    assert all(p["indexed"] and p["bib_key"].startswith("cite_") for p in refs["papers"])
    assert len(api.searcher.db_manager.collection.docs) == 3   # added to the library index
    assert api.changed                                          # graph/BOW refresh requested

    ev_ = api.post("/api/projects/paper/evidence", json={"text": "Nesting sites come from the habitat map peak"})
    assert ev_.status_code == 200
    assert "habitat map" in ev_.json()["top"][0]["text"]
    assert api.post("/api/projects/paper/evidence", json={"text": "x" * 6000}).status_code == 413
    assert api.post("/api/projects/nope/evidence", json={"text": "a b c"}).status_code == 404

    # remove one paper by hand; it does not come back on the next sync
    victim = refs["papers"][0]["hash_id"]
    assert api.delete(f"/api/projects/paper/papers/{victim}").status_code == 200
    api.post("/api/projects/paper/sync")
    _wait(api)
    assert victim not in [p["hash_id"] for p in api.get("/api/projects/paper/refs").json()["papers"]]
    # ... unless it is added again by hand
    assert api.post("/api/projects/paper/papers", json={"hash_id": victim}).json()["status"] == "added"
    assert api.post("/api/projects/paper/papers", json={"hash_id": "../etc"}).status_code == 400

    assert api.delete("/api/projects/paper/zotero").json()["status"] == "unlinked"
    assert api.post("/api/projects/paper/sync").status_code == 400


def test_api_needs_password(api):
    from fastapi.testclient import TestClient
    bare = TestClient(api.app)
    assert bare.get("/api/zotero/collections").status_code == 401


def test_import_docx(api, tmp_path):
    import base64
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("First paragraph of the manuscript.")
    d.add_paragraph("")
    d.add_paragraph("Area X has sparse inner coverage.32")
    f = tmp_path / "m.docx"
    d.save(f)
    r = api.post("/api/projects/paper/import-docx",
                 json={"filename": "m.docx", "data_base64": base64.b64encode(f.read_bytes()).decode()})
    assert r.json()["text"] == "First paragraph of the manuscript.\n\nArea X has sparse inner coverage.32"
    bad = api.post("/api/projects/paper/import-docx", json={"data_base64": base64.b64encode(b"nope").decode()})
    assert bad.status_code == 400


# ---------------------------------------------------------------- project graph

@pytest.mark.parametrize("n", [1, 2, 3, 7])
def test_project_graph_with_few_papers(tmp_path, n, monkeypatch):
    from graph_module import graph_builder as gb
    monkeypatch.setattr(gb, "_paper_summary", lambda pid, fallback="": "")
    db = FakeDB()
    rng = np.random.default_rng(0)
    for i in range(10):
        db.collection.docs[f"p{i}"] = {"meta": {"title": f"Paper {i}"}, "emb": rng.normal(size=16).tolist()}
    cache = tmp_path / "graph_cache.json"
    ids = [f"p{i}" for i in range(n)] + ["not-in-library"]
    g = gb.build_semantic_graph(db, ids=ids, cache_path=cache)
    assert {nd["id"] for nd in g["nodes"]} == {f"p{i}" for i in range(n)}
    assert cache.exists()
    again = gb.build_semantic_graph(db, ids=ids, cache_path=cache)
    assert again["stats"]["built_at"] == g["stats"]["built_at"]          # cached
    other = gb.build_semantic_graph(db, ids=ids[:-2] or ["p9"], cache_path=cache)
    assert other["stats"]["subset_key"] != g["stats"]["subset_key"]      # paper list changed


# ---------------------------------------------------------------- claims with several citations

def test_split_claims_by_citation_marker():
    c = ("By contrast, Area X, characterized by wide outer channels, sparse inner "
         "coverage,32 seasonal salinity bands,33 and habitat-map or nesting functions,9,34 "
         "is expected to reflect tidal level.")
    assert ev.split_claims(c) == [
        {"text": "sparse inner coverage", "cites": "32"},
        {"text": "seasonal salinity bands", "cites": "33"},
        {"text": "habitat-map or nesting functions", "cites": "9,34"},
    ]
    assert ev.split_claims("Growth bands [33] and habitat maps \\cite{lopez2010}.") == [
        {"text": "Growth bands", "cites": "33"}, {"text": "habitat maps", "cites": "lopez2010"}]
    assert ev.split_claims("One citation only (Lopez and Brown, 2010).") == []
    assert ev.citation_labels("x,32 and y [7] \\citep{k1,k2} (Van Dijk et al., 2001)") == \
        ["32", "7", "k1,k2", "Van Dijk et al., 2001"]


def test_citation_resolver():
    from project_module.citations import CitationResolver, expand_label
    draft = ("Text.\n\nReferences\n\n"
             "1. Someone, A. (2000). Unrelated work on something else entirely. J. Foo 1, 2.\n"
             "2. Smith, A.B., and Jones, C.D. (1985). Encoding of tidal patterns by coastal sediment "
             "layers. Science 230. https://doi.org/10.5555/TEST.0001.\n"
             "3. van Dijk, E., et al. (2001). Representation of the river delta in the northern wetland "
             "area. J. Test Geo.\n")
    papers = [
        {"hash_id": "h1", "doi": "10.5555/test.0001", "title": "Encoding of tidal patterns",
         "first_author": "Smith", "year": "1985", "bib_key": "smith1985"},
        {"hash_id": "h2", "doi": "", "title": "Representation of the river delta in the northern wetland area",
         "first_author": "van Dijk", "year": "2001", "bib_key": "vandijk2001"},
    ]
    r = CitationResolver(papers, draft)
    assert r.resolve("2")["papers"] == ["h1"]                      # by DOI (case-insensitive)
    assert r.resolve("3")["papers"] == ["h2"]                      # by title
    out = r.resolve("1–3")
    assert out["papers"] == ["h1", "h2"] and out["unresolved"][0]["label"] == "1"
    assert "Unrelated work" in out["unresolved"][0]["reference"]
    assert r.resolve("vandijk2001,smith1985")["papers"] == ["h2", "h1"]
    assert r.resolve("van Dijk et al., 2001")["papers"] == ["h2"]
    assert r.resolve("Smith and Jones, 1985")["papers"] == ["h1"]
    assert r.resolve("Smith et al., 1999")["papers"] == []
    assert expand_label("24–26,31") == ["24", "25", "26", "31"]


def test_page_furniture_and_figure_text_are_dropped(tmp_path):
    header = "Annu. Rev. Test Ecol. 2010.33:1-21. Downloaded from www.example.org"
    running = "www.annualreviews.org • Priority in Wetland Restoration"
    pages = [f"{header}\n{running}\nThe habitat map in Area X guides nesting to sheltered site {i}.\n"
             f"200 150 100 50 0 100 150 200 b c 200 150 100.\nPage text number {i} continues with real prose here."
             for i in range(4)]
    meta = ev.build_passage_index(tmp_path, bow_encoder(), pages=pages)
    texts = [s["t"] for s in meta["sentences"]]
    assert texts and not any("Downloaded" in t or "annualreviews" in t for t in texts)
    assert not any(t.startswith("200 150") for t in texts)
    assert any("habitat map in Area X" in t for t in texts)


def test_api_evidence_marks_cited_papers_and_judges(api, monkeypatch):
    api.put("/api/projects/paper/zotero", json={"collection_key": "COLL0001"})
    _wait(api)
    papers = api.get("/api/projects/paper/refs").json()["papers"]
    by_title = {p["title"].split()[0]: p for p in papers}
    project_dir = api.library.parent / "projects" / "paper"
    (project_dir / "draft.tex").write_text(
        "Draft.\n\nReferences\n"
        "1. Smith, A. (1985). Encoding of tidal patterns by coastal sediment layers. "
        "Science. https://doi.org/10.5555/test.0001\n"
        "2. van Dijk, E. (2001). Representation of the river delta in the northern wetland area. JTG.\n"
        "3. Lopez, L. (2010). Attention, intention, and priority in wetland restoration. ARE.\n"
        "4. Okafor, P. (1992). The updating of coastal maps after storms. Science.\n")
    claim = ("Area X has a sparse representation of the inner lagoon,2 planar growth bands,1 and acts as a "
             "habitat map of the delta,3,4 so it should not show seasonal floods.")
    r = api.post("/api/projects/paper/evidence", json={"text": claim}).json()
    assert r["numbered_references"] == 4
    assert [p["cites"] for p in r["parts"]] == ["2", "1", "3,4"]
    first = r["parts"][0]
    assert first["cited"] == [by_title["Representation"]["hash_id"]]
    assert first["papers"][0]["cited"] is True and first["papers"][0]["hash_id"] == first["cited"][0]
    third = r["parts"][2]
    assert third["unresolved"][0]["label"] == "4" and "Okafor" in third["unresolved"][0]["reference"]
    assert "habitat map" in third["papers"][0]["passages"][0]["text"]
    assert set(r["cited"]) == {p["hash_id"] for p in papers}

    # AI check (opt-in): without a provider it explains what to do
    from ai_module import provider
    monkeypatch.setattr(provider, "is_enabled", lambda *a, **k: False)
    body = {"claim": "the inner lagoon is sparsely represented in Area X",
            "passages": [{"title": "van Dijk", "text": "The inner lagoon is overrepresented in Area X."},
                         {"title": "Lopez", "text": "Area X is a habitat map."}]}
    assert api.post("/api/projects/paper/evidence/judge", json=body).status_code == 400
    seen = {}

    def fake_complete_json(prompt, system=None, **kw):
        seen["prompt"] = prompt
        return {"verdicts": [{"i": 0, "verdict": "contradicts", "reason": "It says overrepresented."},
                             {"i": 1, "verdict": "Unrelated", "reason": "Other topic."},
                             {"i": 7, "verdict": "supports", "reason": "out of range"},
                             {"i": "x", "verdict": "supports"}]}
    monkeypatch.setattr(provider, "is_enabled", lambda *a, **k: True)
    monkeypatch.setattr(provider, "complete_json", fake_complete_json)
    out = api.post("/api/projects/paper/evidence/judge", json=body).json()
    assert [(v["i"], v["verdict"]) for v in out["verdicts"]] == [(0, "contradicts"), (1, "unrelated")]
    assert "<<The inner lagoon is overrepresented in Area X.>>" in seen["prompt"]


# ---------------------------------------------------------------- privacy

def test_project_files_are_never_tracked():
    """Drafts and reference lists (also of the default project) must stay out of git."""
    import shutil
    import subprocess
    repo = Path(__file__).resolve().parent.parent
    if not shutil.which("git") or not (repo / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files", "--", "projects"],
                             capture_output=True, text=True).stdout.split()
    assert tracked == []
    for f in ("projects/default/draft.tex", "projects/default/references.bib",
              "projects/default/project.json", "projects/other/draft.tex"):
        r = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", "--no-index", f])
        assert r.returncode == 0, f"{f} is not ignored"


def test_api_document_text_and_audit_of_supplied_text(api):
    api.put("/api/projects/paper/zotero", json={"collection_key": "COLL0001"})
    _wait(api)
    project_dir = api.library.parent / "projects" / "paper"
    (project_dir / "draft.tex").write_text("An unrelated draft without references.")
    doc = ("Wetland claims here.\n\nReferences\n"
           "1. Smith, A. (1985). Carbon storage in peat layers of northern wetlands. J. Wet. "
           "https://doi.org/10.5555/test.0001\n"
           "2. Someone, B. (1999). A first unrelated paper. Misc.\n3. Someone, C. (1999). A second unrelated paper. Misc.\n")
    claim = "Peat stores carbon,1 and much more."
    without = api.post("/api/projects/paper/evidence", json={"text": claim}).json()
    assert without["numbered_references"] == 0
    with_doc = api.post("/api/projects/paper/evidence", json={"text": claim, "document_text": doc}).json()
    assert with_doc["numbered_references"] == 3
    assert api.post("/api/projects/paper/evidence",
                    json={"text": claim, "document_text": "x" * 3_000_001}).status_code == 413
    assert api.post("/api/projects/paper/citation-audit", json={"text": "   "}).status_code == 400

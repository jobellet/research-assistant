"""Regression tests for bugs found while testing the full application (no network)."""
import json
import os
import time
from pathlib import Path

import bibtexparser
import pytest

from citation_module.citation_manager import CitationManager
from discovery_module import discover as D
from discovery_module import sources as S
from search_module.bow_builder import build_bow_index, process_text
from search_module.bow_searcher import BowSearcher


# --- BibTeX -----------------------------------------------------------------

def _entries(path):
    with open(path) as fh:
        return bibtexparser.load(fh).entries


def test_bib_entries_are_not_duplicated_and_keys_are_unique(tmp_path):
    bib = tmp_path / "references.bib"
    cm = CitationManager(bib)
    a = {"hash": "h1", "title": "Consciousness in Artificial Intelligence", "authors": ["Patrick Butlin", "Robert Long"],
         "year": "2023", "doi": "10.48550/arXiv.2308.08708"}
    b = {"hash": "h2", "title": "Principles for Responsible AI Consciousness Research", "authors": ["Patrick Butlin"],
         "year": "2023", "journal": "Journal of AI Research"}
    c = {"hash": "h3", "title": "Consciousness and the brain", "authors": "Patrick Butlin", "year": "2023"}
    k1, k2, k3 = cm.add_entry(a), cm.add_entry(b), cm.add_entry(c)
    assert cm.add_entry(dict(a)) == k1                      # same paper again -> same key, no new entry
    entries = _entries(bib)
    assert len(entries) == 3
    assert len({k1, k2, k3}) == 3
    assert k1 == "butlin2023consciousness" and k3 == "butlin2023consciousnessa"
    e1 = next(e for e in entries if e["ID"] == k1)
    assert e1["author"] == "Patrick Butlin and Robert Long"
    assert e1["ENTRYTYPE"] == "misc" and e1["eprint"] == "2308.08708"
    e2 = next(e for e in entries if e["ID"] == k2)
    assert e2["ENTRYTYPE"] == "article" and e2["journal"] == "Journal of AI Research"
    assert "object_type" not in bib.read_text()


def test_constructing_citation_manager_does_not_create_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    CitationManager()
    assert not (tmp_path / "references.bib").exists()


# --- Projects ---------------------------------------------------------------

def test_project_names_cannot_escape_projects_dir():
    from fastapi import HTTPException
    from server_module import main
    for bad in ["..", ".", "...", ".hidden", "../x", "", "  "]:
        with pytest.raises(HTTPException):
            main.get_project_path(bad)
    assert main.get_project_path("my paper").name == "my paper"
    assert main.get_project_path("a/b").name == "ab"


def test_default_project_cannot_be_deleted(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from server_module import main
    monkeypatch.setattr(main, "PROJECTS_DIR", tmp_path)
    (tmp_path / "default").mkdir()
    with pytest.raises(HTTPException):
        main.delete_project("default")
    assert (tmp_path / "default").exists()


def test_search_filters_are_case_insensitive_substrings():
    from server_module.main import _passes_filters
    meta = {"authors": "Patrick Butlin, Robert Long", "journal": "Trends in Cognitive Sciences"}
    assert _passes_filters(meta, "long", None)
    assert _passes_filters(meta, None, "cognitive")
    assert not _passes_filters(meta, "chalmers", None)


# --- Word frequency index ---------------------------------------------------

def _make_library(tmp_path):
    lib = tmp_path / "library"
    texts = {
        "a" * 64: "global workspace broadcast attention global workspace ignition consciousness",
        "b" * 64: "integrated information phi causal structure integrated information consciousness",
        "c" * 64: "language models introspection self report introspection language models consciousness",
    }
    for h, t in texts.items():
        (lib / h).mkdir(parents=True)
        (lib / h / "full_text.txt").write_text(t)
        (lib / h / "metadata.json").write_text(json.dumps({"title": h[:3], "keywords": []}))
    return lib


def test_bow_index_and_tfidf_keywords(tmp_path):
    lib = _make_library(tmp_path)
    stats = build_bow_index(lib)
    assert stats["papers"] == 3
    assert (lib / ("a" * 64) / "bow.json").exists()
    index = json.loads((lib / "global_bow_index.json").read_text())
    assert index["workspace"][0][0] == "a" * 64
    kws = json.loads((lib / ("b" * 64) / "metadata.json").read_text())["keywords"]
    assert "integrated" in kws and "consciousness" not in kws  # word shared by all papers is not a keyword


def test_bow_searcher_reloads_rebuilt_index(tmp_path):
    lib = _make_library(tmp_path)
    searcher = BowSearcher(index_path=lib / "global_bow_index.json")   # index does not exist yet
    assert searcher.search("workspace") == []
    build_bow_index(lib)
    time.sleep(0.01)
    assert searcher.search("workspace")[0]["hash_id"] == "a" * 64


def test_process_text_drops_stopwords():
    assert "the" not in process_text("the the the workspace workspace")


# --- Discovery (offline parts) ----------------------------------------------

def test_arxiv_id_helpers():
    assert S.normalize_arxiv_id("https://arxiv.org/abs/2308.08708v2") == "2308.08708"
    assert S.normalize_arxiv_id("10.48550/arXiv.2410.11407") == "2410.11407"
    assert S.find_arxiv_id("", "2510.24797v2.pdf") == "2510.24797"
    assert S.find_arxiv_id("text arXiv:2501.07290v1 [cs.AI] 13 Jan 2025") == "2501.07290"
    assert S.find_arxiv_id("no identifier here", "paper.pdf") == ""


def test_merge_ranked_deduplicates_across_sources(tmp_path):
    a = {**S.empty_candidate("arxiv"), "title": "A Case for AI Consciousness", "arxiv_id": "2410.11407"}
    b = {**S.empty_candidate("openalex"), "title": "A case for AI consciousness",
         "doi": "10.48550/arxiv.2410.11407", "venue": "arXiv", "citation_count": 12}
    c = {**S.empty_candidate("openalex"), "title": "Something else", "doi": "10.1/x"}
    merged = D.merge_ranked([[a], [b, c]])
    assert len(merged) == 2
    top = merged[0]
    assert top["arxiv_id"] == "2410.11407" and set(top["sources"]) == {"arxiv", "openalex"}
    assert top["citation_count"] == 12


def test_results_are_matched_against_library(tmp_path):
    lib = tmp_path / "library"
    (lib / "h1").mkdir(parents=True)
    (lib / "h1" / "metadata.json").write_text(json.dumps(
        {"title": "Looking Inward", "doi": "", "pdf_filename": "2410.13787.pdf"}))
    res = D._annotate([{**S.empty_candidate("arxiv"), "title": "Looking inward!", "arxiv_id": ""},
                       {**S.empty_candidate("arxiv"), "title": "Other", "arxiv_id": "2410.13787"},
                       {**S.empty_candidate("arxiv"), "title": "New paper", "arxiv_id": "2501.00001"}], lib)
    assert [r["in_library"] for r in res] == [True, True, False]
    assert res[0]["hash_id"] == "h1"


def test_extract_query_terms_prefers_distinctive_words():
    terms = D.extract_query_terms("Self-referential processing makes language models report subjective "
                                  "experience; self-referential prompts", n=3)
    assert terms[0] == "referential"


def test_download_refuses_non_pdf(tmp_path, monkeypatch):
    class R:
        content = b"<html>paywall</html>"
    monkeypatch.setattr(S, "_get", lambda *a, **k: R())
    out = D.download_to_inbox({**S.empty_candidate("x"), "title": "T", "pdf_url": "https://e/x.pdf"}, tmp_path / "inbox")
    assert out["status"] == "failed"
    assert not list((tmp_path / "inbox").glob("*"))


def test_abstract_from_text_fallback():
    from extract_module.llm_utils import abstract_from_text
    text = ("A construct-first approach\nA B S T R A C T\nWe propose a new approach to consciousness science "
            "that deconstructs existing theories and focuses on their main constructs instead of comparing them.\n"
            "1. Introduction\nEverybody has a theory.")
    out = abstract_from_text(text)
    assert out.startswith("We propose a new approach") and "Everybody" not in out
    assert abstract_from_text("no heading here") == ""


def test_cluster_names_use_distinctive_words():
    from graph_module.graph_builder import _cluster_names
    nodes = [{"cluster": 0, "title": "Global workspace in deep learning", "keywords": "workspace, broadcast"},
             {"cluster": 0, "title": "A shared global workspace for modules", "keywords": "workspace"},
             {"cluster": 1, "title": "Language models introspection", "keywords": "introspection, metacognition"},
             {"cluster": 1, "title": "Can language models introspect? introspection tests", "keywords": "introspection"}]
    names = _cluster_names(nodes, [0, 1])
    assert names[0].startswith("workspace") or names[0].startswith("global")
    assert "introspection" in names[1]


def test_neighbor_edges_are_sparsified_and_rescaled():
    from graph_module.neighbor_graph import sparsify_edges
    import itertools
    ids = [f"n{i}" for i in range(8)]
    edges = [{"source": a, "target": b, "weight": 0.05 + 0.01 * (i % 17)}
             for i, (a, b) in enumerate(itertools.combinations(ids, 2))]
    kept = sparsify_edges(edges, k=3)
    assert len(kept) < len(edges)
    assert min(e["weight"] for e in kept) >= 0.3 and max(e["weight"] for e in kept) == 1.0
    assert all("similarity" in e for e in kept)


def test_query_terms_skip_generic_words():
    terms = D.extract_query_terms("Recent interpretability work suggests that language models maintain a small "
                                  "set of verbalizable representations that behave like a global workspace.")
    assert "maintain" not in terms and "small" not in terms
    assert "verbalizable" in terms and "workspace" in terms

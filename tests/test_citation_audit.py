"""Whole-draft citation audit (invented content, fake encoder and fake Crossref)."""
import json

import pytest

from audit_module.citation_audit import check_doi, draft_sentences, run_audit, split_body
from evidence_module import passages as ev
from project_module.citations import CitationResolver
from tests.test_zotero_projects import bow_encoder

DRAFT = """Example Title
A. Author1,2, B. Author2*

Summary
Wetlands store carbon in peat layers.1 Salt marshes trap fine silt during floods,2 and reed beds filter nitrates.3,4 Peat layers are rich in stored carbon and grow slowly over centuries.
Unrelated closing remark without any source here at all.

References
1. Smith, A. (1985). Carbon storage in peat layers of northern wetlands. J. Wet. 1, 1-9. https://doi.org/10.5555/test.0001
2. Jones, B. (2001). Silt trapping by salt marshes during floods. Coast. Res. 2, 3-4. https://doi.org/10.5555/test.0002
3. Lopez, C. (2010). Nitrate filtering by reed beds. Water 5, 6-7. https://doi.org/10.5555/test.0003
4. Okafor, D. (1992). A paper that is not in the project. Misc. 1, 1. https://doi.org/10.5555/test.0004
5. Brown, E. (1999). Never cited in the text. Misc. 2, 2.
"""


def test_split_body_and_sentences():
    body = split_body(DRAFT)
    assert "Author1,2" not in body and "References" not in body
    s = draft_sentences(body)
    assert s[0] == "Wetlands store carbon in peat layers.1"
    assert s[1] == "Salt marshes trap fine silt during floods,2 and reed beds filter nitrates.3,4"
    assert draft_sentences("See Fig. 2 for details of the method. Next one starts here.") == \
        ["See Fig. 2 for details of the method.", "Next one starts here."]


def test_check_doi():
    entry = {"doi": "10.5555/test.0001",
             "text": "Smith, A. (1985). Carbon storage in peat layers of northern wetlands. J. Wet."}
    good = lambda d: {"title": "Carbon storage in peat layers of northern wetlands", "year": 1985,
                      "first_author": "Smith", "journal": "J. Wet."}
    assert check_doi(entry, good)["status"] == "ok"
    bad = lambda d: {"title": "Deep sea vents and their fauna", "year": 2003, "first_author": "Kim", "journal": ""}
    r = check_doi(entry, bad)
    assert r["status"] == "mismatch" and len(r["problems"]) == 3
    assert check_doi(entry, lambda d: None)["status"] == "not_found"
    assert check_doi({"doi": "", "text": "x"})["status"] == "no_doi"

    def boom(d):
        raise OSError("offline")
    assert check_doi(entry, boom)["status"] == "error"


def test_run_audit(tmp_path):
    enc = bow_encoder()
    papers = []
    texts = {
        "h1": ("Carbon storage in peat layers of northern wetlands", "Smith", "1985", "10.5555/test.0001",
               ["Peat layers store large amounts of carbon in wetlands.", "Carbon accumulates slowly in peat."]),
        "h2": ("Silt trapping by salt marshes during floods", "Jones", "2001", "10.5555/test.0002",
               ["Salt marshes trap fine silt when floods cover them.", "Sediment builds up each season."]),
        "h3": ("Nitrate filtering by reed beds", "Lopez", "2010", "10.5555/WRONG",
               ["Reed beds remove nitrates from the water.", "Roots host bacteria."]),
    }
    for hid, (title, author, year, doi, sentences) in texts.items():
        d = tmp_path / hid
        d.mkdir()
        ev.build_passage_index(d, enc, pages=[" ".join(sentences)])
        papers.append({"hash_id": hid, "title": title, "first_author": author, "year": year, "doi": doi.lower(),
                       "authors": author})
    resolver = CitationResolver(papers, DRAFT)
    crossref = {"10.5555/test.0001": {"title": "Carbon storage in peat layers of northern wetlands",
                                       "year": 1985, "first_author": "Smith", "journal": ""},
                "10.5555/test.0002": {"title": "Something else entirely about deserts", "year": 2001,
                                       "first_author": "Jones", "journal": ""}}
    rep = run_audit(DRAFT, papers, enc, tmp_path, resolver, doi_lookup=crossref.get, missing_threshold=0.3)
    sm = rep["summary"]
    assert sm["citing_sentences"] == 2
    assert sm["uncited_references"] == ["5"]
    assert set(sm["doi_problems"]) >= {"2", "3", "4"}   # mismatch, differs from library, unknown
    refs = {r["n"]: r for r in rep["references"]}
    assert refs["1"]["doi_check"]["status"] == "ok" and refs["1"]["in_project"] == "h1"
    assert refs["2"]["doi_check"]["status"] == "mismatch"
    assert refs["3"]["doi_differs_from_library"] == "10.5555/wrong"
    assert refs["4"]["in_project"] is None and refs["4"]["doi_check"]["status"] == "not_found"
    first = rep["citations"][0]["parts"][0]
    assert first["refs"][0]["hash_id"] == "h1" and "carbon" in first["refs"][0]["best_sentences"][0]["text"].lower()
    parts = rep["citations"][1]["parts"]
    assert [p["cites"] for p in parts] == ["2", "3,4"]
    statuses = [r["status"] for r in parts[1]["refs"]]
    assert statuses == ["in_project", "not_in_project"]
    assert any("Peat layers are rich" in m["sentence"] for m in rep["possibly_missing"])
    json.dumps(rep)   # serialisable

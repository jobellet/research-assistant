"""Citation markers, claim splitting and sentence extraction of the evidence search.

All examples are invented text (fictional areas, authors and numbers).
"""
import json
import time

import numpy as np

from evidence_module import passages as ev


def bow_encoder(dim=64):
    def enc(texts, kind):
        out = np.zeros((len(texts), dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in t.lower().split():
                out[i, hash(w) % dim] += 1
        n = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(n, 1e-12)
    enc.model_id = "bow"
    return enc


# ---------------------------------------------------------------- numbers are not citations (1, 20)

def test_decimals_and_thousands_are_not_superscripts():
    c = "Pebbles were about 0.3 mm wide,16 and drift rates were near 1.5 Hz.17"
    assert ev.citation_labels(c) == ["16", "17"]
    out = ev.clean_claim(c)
    assert "0.3 mm" in out and "1.5 Hz" in out
    for text in ("We counted 1,250 nests", "t=0.15 s", "layer 4,5 cells", "p = 0.39 overall",
                 "a total of 20,566 samples", "at 1,000 Hz", "|z| > 1.96 here"):
        assert ev.citation_labels(text) == [], text
        assert ev.clean_claim(text) == text
    parts = ev.split_claims(c)
    assert [p["cites"] for p in parts] == ["16", "17"]
    assert "0.3 mm" in parts[0]["text"]


def test_real_superscripts_still_found():
    assert ev.citation_labels("in Area X,12 and Area Y.13") == ["12", "13"]
    assert ev.citation_labels("salinity bands,33 and nesting functions,9,34 here") == ["33", "9,34"]
    assert ev.citation_labels("two tasks.15,16 Then") == ["15,16"]
    assert ev.citation_labels("tidal drift14 and more") == ["14"]


# ---------------------------------------------------------------- acronyms (6)

def test_superscripts_after_acronyms():
    c = "Crabs nest in rostral SC17–21 and respond to tides in ZQ.22,23"
    assert ev.citation_labels(c) == ["17–21", "22,23"]
    assert ev.citation_labels("Activity in ABQ13,14 predicts tides.") == ["13,14"]
    # area names are kept
    for text in ("cells in V4 and CA1 respond", "areas MT5 and LIP2 are", "fields CA1–3 of the zone",
                 "components PC1–3 explain", "version v2.1 of", "at 4.5 and 12.25 mm"):
        assert ev.citation_labels(text) == [], text
    assert "rostral SC and" in ev.clean_claim(c)


# ---------------------------------------------------------------- author-year (16, 25)

def test_author_year_lead_ins_and_particles():
    assert ev.citation_labels("as shown (van Beers, 2007).") == ["van Beers, 2007"]
    assert ev.citation_labels("as shown (de Groot and Romo, 2005).") == ["de Groot and Romo, 2005"]
    assert ev.citation_labels("as shown (see Smith and Jones, 2002).") == ["Smith and Jones, 2002"]
    assert ev.citation_labels("as shown (e.g., Chen et al., 2015).") == ["Chen et al., 2015"]
    assert ev.citation_labels("(Smith & Jones, 2002, 2004)") == ["Smith & Jones, 2002, 2004"]
    assert ev.citation_labels("(Smith et al., 1985; van Dijk and Lopez, 2010)") == \
        ["Smith et al., 1985; van Dijk and Lopez, 2010"]
    assert ev.citation_labels("a sample (N = 1200) of nests") == []
    assert ev.clean_claim("Tides shape bands (see Smith, 2002).") == "Tides shape bands."


def test_unclosed_parenthesis_is_fast():
    authors = ["Smith et al., 1985", "Jones and Lopez, 2010", "van Dijk, 2001", "Okafor et al., 1992",
               "Chen and Brown, 2015", "Garcia, 2003", "Novak et al., 2008", "Ito and Sato, 2012",
               "Meyer, 1999", "Rossi et al., 2005", "Kim and Park, 2011", "Silva, 2018"]
    inputs = [
        "Growth bands are well known (" + "; ".join(authors) + " and more",
        "(" + "Ab 1999;" * 40 + "x",
        "(" + "A" * 4000,
        ("(" + "Ab " * 100) * 10,
        "[" + "1, " * 1500,
        "\\cite" + "[x]" * 1000 + "{",
        "x," + "1," * 2000 + "a",
        "SC" + "1,2-" * 1000,
        "drift" + "12," * 1500,
        "word " * 3000 + "(",
    ]
    for text in inputs:
        t0 = time.perf_counter()
        ev.citation_labels(text)
        ev.split_claims(text)
        ev.clean_claim(text)
        assert time.perf_counter() - t0 < 1.0, text[:40]


# ---------------------------------------------------------------- split_claims (5, 27)

def test_split_claims_ignores_commas_inside_parentheses():
    c = ("In estuaries, the tides form continuous small ripples (<1 mm, i.e., <60 grains)11–13 "
         "that correct the drift14 and refresh the bed.15")
    parts = ev.split_claims(c)
    assert [p["cites"] for p in parts] == ["11–13", "14", "15"]
    assert parts[0]["text"] == "the tides form continuous small ripples"


def test_split_claims_keeps_every_marker():
    parts = ev.split_claims("In bays, tides modulate V1,7 V4,8 and MT activity.9")
    assert [p["cites"] for p in parts] == ["7", "8", "9"]
    assert "V4" in parts[1]["text"] and "tides modulate" in parts[1]["text"]
    parts = ev.split_claims("Storms reduce growth,12 which was shown in SC,13 and FEF.14")
    assert [p["cites"] for p in parts] == ["12", "13", "14"]
    assert parts[2]["text"] != "FEF" and "FEF" in parts[2]["text"]


# ---------------------------------------------------------------- figure text (23)

def test_statistics_sentences_are_not_figure_text():
    assert not ev._is_figure_text("Rates dropped from 45.2 ± 3.1 to 21.7 ± 2.4 nests/day (p < 0.001, n = 38).")
    assert not ev._is_figure_text("Widths ranged 0.1 – 0.8 mm (median 0.3 mm, IQR 0.2 – 0.5).")
    assert ev._is_figure_text("0 50 100 150 Time (ms)")
    assert ev._is_figure_text("200 150 100 50 0 100 150 200 b c 200 150 100.")


# ---------------------------------------------------------------- reference list (22)

def test_methods_after_references_are_kept():
    body = "The growth bands in zone 7a are planar and thick here. " * 10
    pages = [body, body,
             "Discussion of the bands goes on here for some time.\nReferences\n1. Smith A. Bands. Nature 1, 2.",
             "Methods\nNests were sampled at low tide with a coring tool.\nMethods references\n"
             "40. Jones B. Coring tools. Science 3, 4.",
             body]
    kept = ev._cut_references(pages)
    assert len(kept) == 5
    joined = "\n".join(kept)
    assert "Nests were sampled at low tide" in joined
    assert "Smith A. Bands" not in joined and "Coring tools" not in joined
    assert kept[4] == ""                # after the Methods reference list nothing resumes
    kept = ev._cut_references([body, body, "Text.\nReferences\n1. Smith A. Bands.", body])
    assert kept[3] == ""


def test_reference_heading_variants():
    for h in ("References", "5. References", "References:", "Reference", "REFERENCES", "Literature Cited"):
        assert ev._REFERENCES_HEADING.match(h), h
    assert not ev._REFERENCES_HEADING.match("References to tidal maps are rare")


# ---------------------------------------------------------------- word-match fallback (24)

def test_word_fallback_skips_reference_list(tmp_path):
    body = "Sediment cores were taken from several estuaries over two seasons of fieldwork. " * 12
    text = (body + "\nWe find that storm signals for ripples reach the northern wetland in spring.\n"
            "References\n1. Smith AB, Jones CD. Storm signals for ripples in the southern delta and "
            "northern wetland. Science 1, 2 (1985).\n")
    (tmp_path / "full_text.txt").write_text(text)
    out = ev._word_matches("Storm signals for ripples reach the northern wetland.", tmp_path, 3, 1)
    assert out["passages"]
    assert all("Science" not in p["text"] for p in out["passages"])
    assert "We find that" in out["passages"][0]["text"]


def test_word_matches_rank_after_semantic(tmp_path):
    lib = tmp_path / "lib"
    enc = bow_encoder()
    (lib / "sem").mkdir(parents=True)
    ev.build_passage_index(lib / "sem", enc, pages=[
        "Unrelated text about pebbles appears in this sentence here. Another line about sand grains here."])
    (lib / "words").mkdir()
    (lib / "words" / "full_text.txt").write_text(
        "Storm signals for ripples reach the northern wetland in spring time.")
    out = ev.find_evidence("Storm signals for ripples reach the northern wetland.",
                           [{"hash_id": "sem"}, {"hash_id": "words"}], enc, lib)
    assert out["papers"][-1]["method"] == "words"
    assert out["top"][-1]["method"] == "words"


# ---------------------------------------------------------------- hyphens and page breaks (28)

def test_compound_hyphens_kept_and_page_breaks_joined(tmp_path):
    assert "self-motion" in ev.split_sentences("We studied the self-\nmotion signals of crabs in bays today.")[0]
    assert "hyphenation" in ev.split_sentences("This shows that hyphen-\nation is removed in most words.")[0]
    s = ev.split_sentences("The drift-corrected cores were dry. Later the drift-\ncorrected tide maps were used.")
    assert "drift-corrected tide" in s[1]
    pages = ["Results start here and the long sentence about tidal growth bands continues onto the",
             "next page of the paper without a break. Then a new sentence starts on page two here."]
    meta = ev.build_passage_index(tmp_path, bow_encoder(), pages=pages)
    first = meta["sentences"][0]
    assert first["p"] == 1 and first["t"].endswith("without a break.")
    assert meta["sentences"][1]["p"] == 2
    assert json.loads((tmp_path / "passages.json").read_text())["version"] == ev.INDEX_VERSION == 3

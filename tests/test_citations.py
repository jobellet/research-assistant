"""Citation resolver: author-year forms, name particles, year letters, DOI normalisation, title matching.

All names, titles and DOIs below are invented.
"""
from project_module.citations import CitationResolver, _norm_doi, parse_numbered_references


def P(hid, first, year, title="", doi="", bib_key=""):
    return {"hash_id": hid, "first_author": first, "year": year, "title": title, "doi": doi, "bib_key": bib_key}


# --- finding 21: 'Surname, YYYY' ------------------------------------------------------------

def test_single_author_comma_year_resolves():
    r = CitationResolver([P("smith", "Smith", "2011"), P("jones", "Jones", "2002")])
    assert r.resolve("Smith, 2011") == {"papers": ["smith"], "unresolved": []}
    assert r.resolve("Smith, 2011a")["papers"] == ["smith"]
    assert r.resolve("Smith, 2011; Jones, 2002")["papers"] == ["smith", "jones"]


def test_single_author_comma_year_unresolved_reports_whole_label():
    r = CitationResolver([P("smith", "Smith", "2011")])
    out = r.resolve("Miller, 2011")
    assert out["papers"] == []
    assert [u["label"] for u in out["unresolved"]] == ["Miller, 2011"]


def test_bib_key_lists_still_use_keys():
    r = CitationResolver([P("a", "Smith", "2011", bib_key="smith2011"), P("b", "Jones", "2002", bib_key="jones2002")])
    assert r.resolve("smith2011,jones2002")["papers"] == ["a", "b"]
    assert r.resolve("smith2011, jones2002")["papers"] == ["a", "b"]


# --- finding 25: particles, lead-ins, several years ------------------------------------------

def test_particles_and_lead_ins():
    papers = [P("vd", "van Dijk", "2007"), P("dv", "de Vries", "2005"), P("sm", "Smith", "2002"),
              P("ch", "Chen", "2015")]
    r = CitationResolver(papers)
    assert r.resolve("van Dijk, 2007")["papers"] == ["vd"]
    assert r.resolve("de Vries and Smith, 2005")["papers"] == ["dv"]
    assert r.resolve("see Smith and Jones, 2002")["papers"] == ["sm"]
    assert r.resolve("see also Smith, 2002")["papers"] == ["sm"]
    assert r.resolve("e.g., Chen et al., 2015")["papers"] == ["ch"]
    assert r.resolve("cf. van Dijk et al., 2007")["papers"] == ["vd"]
    assert r.resolve("Smith, 2002; see van Dijk, 2007")["papers"] == ["sm", "vd"]


def test_particle_stored_differently_in_project():
    # The project may hold 'Dijk' (name split on the last word) or 'van Dijk'.
    r = CitationResolver([P("vd", "Dijk", "2007")])
    assert r.resolve("van Dijk, 2007")["papers"] == ["vd"]
    r = CitationResolver([P("vd", "van Dijk", "2007")])
    assert r.resolve("Dijk 2007")["papers"] == ["vd"]


def test_every_year_of_a_group_is_resolved_or_reported():
    r = CitationResolver([P("a", "Smith", "2002"), P("b", "Smith", "2004")])
    assert r.resolve("Smith & Jones, 2002, 2004")["papers"] == ["a", "b"]
    out = CitationResolver([P("a", "Smith", "2002")]).resolve("Smith & Jones, 2002, 2004")
    assert out["papers"] == ["a"]
    assert [u["label"] for u in out["unresolved"]] == ["Smith & Jones, 2004"]
    assert r.resolve("Smith, 2002; 2004")["papers"] == ["a", "b"]


# --- finding 26: exact surnames first, year letters ------------------------------------------

def test_exact_surname_beats_particle_suffix():
    r = CitationResolver([P("bh", "Ben Mar", "2001"), P("h", "Mar", "2001")])
    assert r.resolve("Ben Mar et al., 2001")["papers"] == ["bh"]
    assert r.resolve("Mar et al., 2001")["papers"] == ["h"]


def test_short_surname_is_not_a_suffix_match():
    r = CitationResolver([P("ali", "Ali", "2010")])
    assert r.resolve("Li 2010")["papers"] == []
    assert r.resolve("Li, 2010")["papers"] == []


def test_year_letter_picks_one_paper():
    papers = [P("x", "Chen", "2015", title="Beta waves in area X"),
              P("y", "Chen", "2015", title="Alpha waves in area X")]
    r = CitationResolver(papers)
    assert r.resolve("Chen et al., 2015a")["papers"] == ["y"]        # title order: Alpha < Beta
    assert r.resolve("Chen et al., 2015b")["papers"] == ["x"]
    assert sorted(r.resolve("Chen et al., 2015")["papers"]) == ["x", "y"]
    assert r.resolve("Chen et al., 2015c")["papers"] == []
    keyed = [P("x", "Chen", "2015", title="Alpha", bib_key="chen2015b"),
             P("y", "Chen", "2015", title="Beta", bib_key="chen2015a")]
    assert CitationResolver(keyed).resolve("Chen, 2015a")["papers"] == ["y"]


# --- finding 29: DOI normalisation and title-match checks ------------------------------------

def test_doi_normalisation():
    assert _norm_doi("https://doi.org/10.1234/ABC.5678.") == "10.1234/abc.5678"
    assert _norm_doi("http://dx.doi.org/10.1234/abc") == "10.1234/abc"
    assert _norm_doi("doi: 10.1234/abc;") == "10.1234/abc"
    assert _norm_doi("") == "" and _norm_doi(None) == ""


DRAFT = ("Text.\n\nReferences\n\n"
         "1. Smith, A. (2009). An unrelated study of something else entirely. J. Foo 1, 2.\n"
         "2. Smith, A. (2010). Feature alpha in area X. J. Foo 3. https://doi.org/10.1234/FOO.42.\n"
         "3. Jones, B. Comment on: Spatial coding of feature alpha in area X of the monkey. J. Foo (2012).\n"
         "4. Miller, C. (2013). Spatial coding of feature alpha in area X of the monkey. J. Bar 9.\n"
         "5. Miller, C. Spatial coding of feature alpha in area X of the monkey. J. Bar.\n")


def test_project_doi_with_prefix_matches_draft_doi():
    r = CitationResolver([P("h", "Smith", "2010", title="Short", doi="https://doi.org/10.1234/foo.42")], DRAFT)
    assert r.resolve("2")["papers"] == ["h"]
    assert parse_numbered_references(DRAFT)["2"]["doi"] == "10.1234/foo.42"


def test_title_match_needs_year_or_author_and_skips_commentaries():
    r = CitationResolver([P("m", "Miller", "2013",
                            title="Spatial coding of feature alpha in area X of the monkey")], DRAFT)
    assert r.resolve("3")["papers"] == []                  # commentary by another author, other year
    assert r.resolve("4")["papers"] == ["m"]               # year present
    assert r.resolve("5")["papers"] == ["m"]               # author present
    other = CitationResolver([P("o", "Taylor", "1999",
                                title="Spatial coding of feature alpha in area X of the monkey")], DRAFT)
    assert other.resolve("4")["papers"] == []


def test_title_match_without_year_or_author_metadata_still_works():
    r = CitationResolver([P("m", "", "", title="Spatial coding of feature alpha in area X of the monkey")], DRAFT)
    assert r.resolve("4")["papers"] == ["m"]


def test_dois_with_parentheses_are_kept_whole():
    from project_module.citations import _norm_doi, parse_numbered_references
    assert _norm_doi("https://doi.org/10.1016/S0042-6989(03)00084-1.") == "10.1016/s0042-6989(03)00084-1"
    assert _norm_doi("(doi: 10.5555/abc.1)") == "10.5555/abc.1"
    refs = parse_numbered_references("References\n1. A, B. (2003). Title one here. J. 1. https://doi.org/10.1016/S0042-6989(03)00084-1\n"
                                     "2. C, D. (2004). Title two here. J. 2. (https://doi.org/10.5555/x.2)\n"
                                     "3. E, F. (2005). Title three here. J. 3. https://doi.org/10.5555/x.3\n")
    assert refs["1"]["doi"] == "10.1016/s0042-6989(03)00084-1" and refs["2"]["doi"] == "10.5555/x.2"

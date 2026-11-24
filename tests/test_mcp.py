import json

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")
from starlette.testclient import TestClient

from mcp_module.server import McpServer, create_app

SECRET = "s" * 32
FAKE = [{"title": "Paper A", "authors": ["Ada Lovelace"], "year": "2024", "doi": "10.1/a",
         "abstract": "x" * 3000, "url": "https://example.org/a"}]


def rpc(method, params=None, mid=1):
    return {"jsonrpc": "2.0", "id": mid, "method": method, **({"params": params} if params else {})}


@pytest.fixture
def lib(tmp_path):
    for h, title, doi in (("h1", "Neural correlates of consciousness in language models", "10.1/x"),
                          ("h2", "Birds of Europe", "10.1/y")):
        d = tmp_path / h
        d.mkdir()
        (d / "metadata.json").write_text(json.dumps({"title": title, "authors": ["Jane Doe"], "year": "2023",
                                                     "doi": doi, "summary": "about " + title, "keywords": ["consciousness"] if h == "h1" else []}))
        (d / "full_text.txt").write_text("SECRET FULL TEXT")
    return tmp_path


def test_discovery_mode_exposes_only_discovery(lib):
    s = McpServer("discovery", lib, searcher=lambda *a: FAKE)
    assert [t["name"] for t in s.handle(rpc("tools/list"))["result"]["tools"]] == ["discover_papers"]
    r = s.handle(rpc("tools/call", {"name": "search_library", "arguments": {"query": "x"}}))["result"]
    assert r["isError"]   # library tools do not exist, and the library is never opened


def test_discover_papers_truncates_and_shapes(lib):
    s = McpServer("discovery", None, searcher=lambda q, src, n, y: FAKE)
    out = json.loads(s.handle(rpc("tools/call", {"name": "discover_papers", "arguments": {"query": "q"}}))["result"]["content"][0]["text"])
    assert out[0]["title"] == "Paper A" and len(out[0]["abstract"]) == 1500


def test_library_tools_are_read_only_metadata(lib):
    s = McpServer("library", lib)
    names = {t["name"] for t in s.handle(rpc("tools/list"))["result"]["tools"]}
    assert names == {"discover_papers", "search_library", "get_paper", "cite", "check_in_library"}
    hits = json.loads(s.handle(rpc("tools/call", {"name": "search_library", "arguments": {"query": "consciousness language"}}))["result"]["content"][0]["text"])
    assert [h["id"] for h in hits] == ["h1"]
    got = s.handle(rpc("tools/call", {"name": "get_paper", "arguments": {"id": "10.1/x"}}))["result"]["content"][0]["text"]
    assert "Neural correlates" in got and "SECRET FULL TEXT" not in got
    bib = s.handle(rpc("tools/call", {"name": "cite", "arguments": {"id": "h1"}}))["result"]["content"][0]["text"]
    assert "@article" in bib and "Neural correlates" in bib and "library_hash" not in bib


def test_protocol_basics():
    s = McpServer("discovery")
    init = s.handle(rpc("initialize", {"protocolVersion": "2025-03-26"}))["result"]
    assert init["protocolVersion"] == "2025-03-26" and "tools" in init["capabilities"]
    assert s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert s.handle(rpc("nope"))["error"]["code"] == -32601
    assert s.handle(rpc("ping"))["result"] == {}


def test_http_secret_path_and_status_codes(lib):
    c = TestClient(create_app(SECRET, "discovery", lib, searcher=lambda *a: FAKE))
    assert c.post("/mcp/wrong" + SECRET, json=rpc("ping")).status_code == 404
    assert c.post("/", json=rpc("ping")).status_code == 404
    assert c.get(f"/mcp/{SECRET}").status_code == 405
    assert c.post(f"/mcp/{SECRET}", content=b"{bad").status_code == 400
    assert c.post(f"/mcp/{SECRET}", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    assert c.post(f"/mcp/{SECRET}", json=rpc("tools/list")).json()["result"]["tools"]


def test_short_secret_refused():
    with pytest.raises(ValueError):
        create_app("short")


def test_rate_limit():
    s = McpServer("discovery", searcher=lambda *a: FAKE)
    last = None
    for _ in range(61):
        last = s.handle(rpc("tools/call", {"name": "discover_papers", "arguments": {"query": "q"}}))
    assert last["result"]["isError"] and "Rate limit" in last["result"]["content"][0]["text"]


def test_odd_metadata_shapes_and_empty_id(tmp_path):
    d = tmp_path / "odd"
    d.mkdir()
    (d / "metadata.json").write_text(json.dumps({"title": "Odd", "authors": [{"name": "A B"}, {"given": "C", "family": "D"}],
                                                 "keywords": [{"name": "k"}], "summary": "workspace"}))
    s = McpServer("library", tmp_path)
    hit = json.loads(s.handle(rpc("tools/call", {"name": "search_library", "arguments": {"query": "workspace"}}))["result"]["content"][0]["text"])
    assert hit[0]["authors"] == ["A B", "C D"]
    for ident in ("", "  "):
        assert s.handle(rpc("tools/call", {"name": "cite", "arguments": {"id": ident}}))["result"]["isError"]


class FakeApp:
    """Records calls to the local app and returns canned answers."""

    def __init__(self):
        self.calls = []
        self.draft = "\\section{A}"

    def get(self, path, params=None):
        self.calls.append(("GET", path, params))
        if path.endswith("/draft"):
            return {"content": self.draft}
        if path.startswith("/api/library/text/"):
            return {"text": "abcdefghij" * 500}
        return {"ok": True}

    def post(self, path, body):
        self.calls.append(("POST", path, body))
        if path == "/api/search":
            return [{"hash_id": "h1", "score": 0.9, "metadata": {"title": "Neural correlates of consciousness in language models"},
                     "summary": "s1"},
                    {"hash_id": "h2", "score": 0.5, "metadata": {"title": "Birds of Europe"}, "summary": "s2"}]
        return {"status": "downloaded", "title": "T"}

    def put(self, path, body):
        self.calls.append(("PUT", path, body))
        self.draft = body["content"]
        return {"status": "saved"}


def call(s, tool, **args):
    r = s.handle(rpc("tools/call", {"name": tool, "arguments": args}))["result"]
    return r.get("isError", False), r["content"][0]["text"]


def test_full_mode_lists_tools_with_write_annotations(lib):
    s = McpServer("full", lib, app=FakeApp())
    tools = {t["name"]: t for t in s.handle(rpc("tools/list"))["result"]["tools"]}
    assert {"check_in_library", "add_to_library", "similar_papers", "semantic_search", "read_paper_text",
            "append_to_draft", "add_citation"} <= set(tools)
    assert tools["similar_papers"]["annotations"]["readOnlyHint"] is True
    assert tools["add_to_library"]["annotations"]["readOnlyHint"] is False
    assert not any("delete" in n for n in tools)


def test_full_tools_not_reachable_in_lower_modes(lib):
    for mode in ("discovery", "library"):
        s = McpServer(mode, lib, app=FakeApp())
        for name in ("add_to_library", "append_to_draft", "similar_papers"):
            err, _ = call(s, name, identifier="10.1/x", text="x", id="h1")
            assert err


def test_check_in_library_exact_and_near(lib):
    app = FakeApp()
    s = McpServer("full", lib, app=app)
    err, out = call(s, "check_in_library", doi="https://doi.org/10.1/X")
    data = json.loads(out)
    assert not err and data["in_library"] and data["match"]["id"] == "h1"
    err, out = call(s, "check_in_library", title="Something else entirely", text="an abstract")
    data = json.loads(out)
    assert not data["in_library"] and data["closest_by_meaning"][0]["id"] == "h1"


def test_similar_papers_excludes_itself_and_add_to_library_uses_app(lib):
    app = FakeApp()
    s = McpServer("full", lib, app=app)
    _, out = call(s, "similar_papers", id="h1", n=5)
    assert [p["id"] for p in json.loads(out)] == ["h2"]
    _, out = call(s, "add_to_library", identifier="arxiv:2305.17375")
    assert json.loads(out)["status"] == "downloaded"
    assert ("POST", "/api/discover/fetch", {"identifier": "arxiv:2305.17375", "process": True}) in app.calls


def test_read_text_chunks_and_append_never_replaces(lib):
    app = FakeApp()
    s = McpServer("full", lib, app=app)
    _, out = call(s, "read_paper_text", id="h1", offset=0, max_chars=1000)
    d = json.loads(out)
    assert len(d["text"]) == 1000 and d["next_offset"] == 1000 and d["total_chars"] == 5000
    call(s, "append_to_draft", project="default", text="\\section{B}")
    assert app.draft.startswith("\\section{A}") and app.draft.rstrip().endswith("\\section{B}")


def test_invalid_project_names_refused(lib):
    s = McpServer("full", lib, app=FakeApp())
    for bad in ("../x", ".hidden", "a/b", ""):
        err, _ = call(s, "append_to_draft", project=bad or "/", text="x")
        assert err
    err, _ = call(s, "create_project", name="../evil")
    assert err


def test_app_down_gives_a_clear_error(lib):
    from mcp_module.app_client import AppClient
    s = McpServer("full", lib, app=AppClient("http://127.0.0.1:9", "t", timeout=2))
    err, msg = call(s, "library_stats")
    assert err and "not reachable" in msg


def test_check_claim_and_project_references(lib):
    app = FakeApp()
    evidence = {
        "claim": "Area X has sparse inner coverage, growth bands.",
        "papers": [], "top": [], "not_indexed": ["h9"], "unresolved": [],
        "parts": [{"claim": "sparse inner coverage", "cites": "32",
                   "unresolved": [{"label": "9", "reference": "Okafor, P. (1992). The updating..."}],
                   "papers": [{"hash_id": "h1", "title": "Representation of the river delta", "authors": "van Dijk et al.",
                               "year": "2001", "bib_key": "vandijk2001", "cited": True, "best_score": 0.6,
                               "passages": [{"text": "Overrepresentation of the inner lagoon in Area X.", "page": 9,
                                             "similarity": 0.65, "before": "", "after": "We calculated..."}]}]}],
    }
    app.post = lambda path, body: (app.calls.append(("POST", path, body)), evidence)[1]
    s = McpServer("full", lib, app=app)
    tools = {t["name"]: t for t in s.handle(rpc("tools/list"))["result"]["tools"]}
    assert tools["check_claim"]["annotations"]["readOnlyHint"] is True
    assert tools["sync_project_zotero"]["annotations"]["readOnlyHint"] is False
    err, text = call(s, "check_claim", project="My paper", text="Area X has sparse inner coverage,32")
    assert not err
    method, path, body = app.calls[-1]
    assert path == "/api/projects/My%20paper/evidence" and body["per_paper"] == 3
    out = json.loads(text)
    part = out["cited_parts"][0]
    assert part["cites"] == "32" and part["papers"][0]["cited"] is True
    assert part["papers"][0]["sentences"][0]["page"] == 9
    assert part["not_in_project"][0].startswith("9: Okafor")
    assert "still being indexed" in out["note"]
    assert call(s, "check_claim", text="   ")[0] is True
    call(s, "project_references", project="My paper")
    assert app.calls[-1][1] == "/api/projects/My%20paper/refs"
    assert call(s, "project_references", project="../x")[0] is True


def test_audit_citations_tool(lib):
    app = FakeApp()
    state = {"job": {"running": False}, "report": None}
    app.get = lambda path, params=None: (app.calls.append(("GET", path, params)), state)[1]
    app.post = lambda path, body: (app.calls.append(("POST", path, body)), {"job": {"running": True}})[1]
    s = McpServer("full", lib, app=app)
    err, text = call(s, "audit_citations", project="p")
    assert not err and json.loads(text)["status"] == "started"
    assert app.calls[-1][1] == "/api/projects/p/citation-audit" and app.calls[-1][2]["check_dois"] is True
    state["job"] = {"running": True, "done": 3, "total": 9}
    assert json.loads(call(s, "audit_citations", project="p")[1])["status"] == "running"
    state["job"] = {"running": False}
    state["report"] = {"summary": {"citing_sentences": 12}, "citations": [{"sentence_index": i} for i in range(12)],
                       "references": [{"n": "1", "in_project": "h", "cited_in": [0], "doi_check": {"status": "ok"}},
                                      {"n": "2", "in_project": None, "cited_in": [1]}],
                       "possibly_missing": []}
    out = json.loads(call(s, "audit_citations", project="p", limit=5)[1])
    assert len(out["citations"]) == 5 and out["next_offset"] == 5
    assert [r["n"] for r in out["reference_problems"]] == ["2"]
    out = json.loads(call(s, "audit_citations", project="p", offset=10, limit=5)[1])
    assert len(out["citations"]) == 2 and out["next_offset"] is None and "reference_problems" not in out


def test_audit_citations_page_is_valid_json_even_when_large(lib):
    app = FakeApp()
    big = "x" * 3000
    cit = {"sentence_index": 0, "sentence": "s", "parts": [{"claim": "c", "cites": "1", "refs": [
        {"status": "in_project", "title": "T", "best_sentences": [{"text": big, "page": 1, "similarity": 0.5,
                                                                    "before": big, "after": big}] * 3}]}]}
    state = {"job": {"running": False}, "report": {"summary": {}, "citations": [dict(cit, sentence_index=i) for i in range(30)],
                                                   "references": [], "possibly_missing": []}}
    app.get = lambda path, params=None: state
    s = McpServer("full", lib, app=app)
    err, text = call(s, "audit_citations", project="p", limit=30)
    out = json.loads(text)                       # never truncated into invalid JSON
    assert out["citations"] and out["next_offset"] == len(out["citations"])
    assert "before" not in out["citations"][0]["parts"][0]["refs"][0]["best_sentences"][0]

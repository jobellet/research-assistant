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
    assert names == {"discover_papers", "search_library", "get_paper", "cite"}
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

"""AI provider configuration/requests and sync-related server behaviour (no network)."""
import json

import pytest

from ai_module import provider as P

PROVIDER_ENV = ["AI_PROVIDER", "AI_API_KEY", "AI_MODEL", "AI_BASE_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                "GEMINI_API_KEY", "GOOGLE_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"]


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for k in PROVIDER_ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(P, "_settings_path", lambda: tmp_path / "ai_settings.json")
    return tmp_path


def test_disabled_without_configuration(clean_env):
    assert not P.is_enabled()
    with pytest.raises(P.AIError):
        P.complete("hi")


def test_autodetects_a_provider_key_and_masks_it(clean_env, monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "secret-mistral-key-1234")
    pub = P.public_settings()
    assert pub["provider"] == "mistral" and pub["enabled"] and pub["source"] == "autodetect"
    assert "secret" not in json.dumps(pub) and pub["key_hint"] == "…1234"


def test_saved_settings_win_and_reuse_env_key(clean_env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key-000000")
    monkeypatch.setenv("MISTRAL_API_KEY", "mis-key-111111")
    P.save_settings("mistral", None, "mistral-large-latest")
    cfg = P.get_settings()
    assert cfg["provider"] == "mistral" and cfg["api_key"] == "mis-key-111111" and cfg["source"] == "settings"
    saved = json.loads((clean_env / "ai_settings.json").read_text())
    assert saved["api_key"] == ""            # the env key is not copied into the file


def test_request_shapes_per_provider(clean_env):
    anth = P.resolve({"provider": "anthropic", "api_key": "k"})
    req = P._build(anth, "q", "sys", 100, 0.3, streaming=True)
    assert req["url"].endswith("/messages") and req["headers"]["x-api-key"] == "k"
    assert "temperature" not in req["body"] and req["body"]["system"] == "sys" and req["body"]["stream"]
    assert req["body"]["model"] == "claude-opus-5-5"
    gem = P._build(P.resolve({"provider": "gemini", "api_key": "g"}), "q", None, 100, 0.2, streaming=True)
    assert "streamGenerateContent?alt=sse" in gem["url"] and "key=" not in gem["url"]
    oai = P._build(P.resolve({"provider": "custom", "api_key": "", "base_url": "http://localhost:11434/v1/"}),
                   "q", None, 100, 0.2, streaming=False)
    assert oai["url"] == "http://localhost:11434/v1/chat/completions" and "Authorization" not in oai["headers"]


class FakeStream:
    status_code = 200

    def __init__(self, lines):
        self.lines = lines

    def iter_lines(self, decode_unicode=True):
        return iter(self.lines)


@pytest.mark.parametrize("prov,lines,expected", [
    ("anthropic", ['data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":""}}',
                   'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hel"}}',
                   'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"lo"}}'], "Hello"),
    ("openai", ['data: {"choices":[{"delta":{"content":"Hel"}}]}', 'data: {"choices":[{"delta":{"content":"lo"}}]}',
                "data: [DONE]"], "Hello"),
    ("gemini", ['data: {"candidates":[{"content":{"parts":[{"text":"Hello"}]}}]}'], "Hello"),
])
def test_streaming_parsers(clean_env, monkeypatch, prov, lines, expected):
    monkeypatch.setattr(P.requests, "post", lambda *a, **k: FakeStream(lines))
    assert "".join(P.stream("q", settings={"provider": prov, "api_key": "k"})) == expected


def test_error_messages_never_contain_the_key(clean_env, monkeypatch):
    class Bad:
        status_code = 401
        text = "invalid key sk-verysecret-9999"
    monkeypatch.setattr(P.requests, "post", lambda *a, **k: Bad())
    with pytest.raises(P.AIError) as e:
        P.complete("q", settings={"provider": "openai", "api_key": "sk-verysecret-9999"})
    assert "verysecret" not in str(e.value)


def test_project_files_keep_synced_timestamps(tmp_path, monkeypatch):
    from server_module import main
    monkeypatch.setattr(main, "PROJECTS_DIR", tmp_path)
    main.create_project(main.ProjectCreateRequest(name="notes"))
    r = main.save_bib("notes", main.DraftSaveRequest(content="@misc{a,}\n", updated_at=1700000000123))
    assert r["updated_at"] == 1700000000123
    assert main.get_bib("notes")["content"] == "@misc{a,}\n"
    listing = main.list_projects()
    assert listing["details"]["notes"]["bib"] == 1700000000123

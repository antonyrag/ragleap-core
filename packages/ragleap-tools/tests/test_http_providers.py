"""End-to-end: every network provider through the real urllib path against a
local server. Size cap, total deadline, config validation, per-operation timeout."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from ragleap_tools import (FileOpsConfig, GeminiVisionProvider, AnthropicVisionProvider,
                           GitHubSearchConfig, SerperSearchProvider, TavilySearchProvider,
                           VisionConfig, WebSearchConfig)
from ragleap_tools.github_search import search_github_repositories
from ragleap_tools.vision import describe_image
from ragleap_tools.web_search import search_web

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32

TAVILY_OK = json.dumps({"results": [{"title": "T", "url": "http://t", "content": "c"}]}).encode()
SERPER_OK = json.dumps({"organic": [{"title": "T", "link": "http://t", "snippet": "s"}]}).encode()
GITHUB_OK = json.dumps({"items": [{"full_name": "a/b", "html_url": "http://g", "description": None,
                                   "stargazers_count": 3, "language": None}]}).encode()
GEMINI_OK = json.dumps({"candidates": [{"content": {"parts": [{"text": "a cat"}]}}]}).encode()
ANTHROPIC_OK = json.dumps({"content": [{"type": "text", "text": "a cat"}]}).encode()


def _search(provider_cls, payload):
    def run(server, **kw):
        server.payload = payload
        p = provider_cls(api_key="k", base_url=server.url, **kw)
        return lambda: search_web(WebSearchConfig(provider=p), "q"), p
    return run


def _github(server, **kw):
    server.payload = GITHUB_OK
    cfg = GitHubSearchConfig(**kw)
    return lambda: search_github_repositories(cfg, "q"), cfg


def _vision(provider_cls, payload):
    def run(server, tmp_path, **kw):
        server.payload = payload
        root = tmp_path / "root"
        root.mkdir(exist_ok=True)
        (root / "a.jpg").write_bytes(JPEG)
        base = server.url.rstrip("/") if provider_cls is GeminiVisionProvider else server.url
        p = provider_cls(api_key="k", model="m", base_url=base, **kw)
        cfg = VisionConfig(provider=p, sandbox=FileOpsConfig(root_dir=str(root)))
        return lambda: describe_image(cfg, "a.jpg"), p
    return run


SEARCH_CASES = [("tavily", _search(TavilySearchProvider, TAVILY_OK)),
                ("serper", _search(SerperSearchProvider, SERPER_OK))]
VISION_CASES = [("gemini", _vision(GeminiVisionProvider, GEMINI_OK)),
                ("anthropic", _vision(AnthropicVisionProvider, ANTHROPIC_OK))]


@pytest.fixture(autouse=True)
def github_points_at_the_server(server, monkeypatch):
    monkeypatch.setattr("ragleap_tools.github_search.BASE_URL", server.url)


def all_cases():
    out = [(n, lambda s, t, _f=f, **kw: _f(s, **kw)) for n, f in SEARCH_CASES]
    out.append(("github", lambda s, t, **kw: _github(s, **kw)))
    out += [(n, f) for n, f in VISION_CASES]
    return out


CASES = all_cases()
IDS = [c[0] for c in CASES]


@pytest.mark.parametrize("name,make", CASES, ids=IDS)
def test_works_end_to_end_over_real_urllib(name, make, server, tmp_path):
    call, _ = make(server, tmp_path)
    r = call()
    assert r.success is True, r.error
    assert server.requests and server.requests[0][0] in ("GET", "POST")


@pytest.mark.parametrize("name,make", CASES, ids=IDS)
def test_oversized_response_is_a_clean_error(name, make, server, tmp_path):
    call, _ = make(server, tmp_path, max_response_bytes=4096)
    server.mode = "big"
    r = call()
    assert r.success is False and "response exceeded 4096 bytes" in r.error


@pytest.mark.parametrize("name,make", CASES, ids=IDS)
def test_slow_drip_returns_at_the_total_deadline(name, make, server, tmp_path):
    call, _ = make(server, tmp_path, total_timeout=0.6)
    server.mode = "drip"
    t0 = time.monotonic()
    r = call()
    assert time.monotonic() - t0 < 3
    assert r.success is False and "request exceeded 0.6 seconds" in r.error


@pytest.mark.parametrize("name,make", CASES, ids=IDS)
def test_configured_limits_are_stored_and_defaults_documented(name, make, server, tmp_path):
    _, p = make(server, tmp_path, max_response_bytes=5000, total_timeout=7)
    assert (p.max_response_bytes, p.total_timeout) == (5000, 7)
    _, d = make(server, tmp_path)
    assert d.max_response_bytes == 1_048_576
    assert d.total_timeout == (90.0 if name in ("gemini", "anthropic") else 20.0)


@pytest.mark.parametrize("name,make", CASES, ids=IDS)
def test_bad_limits_are_rejected_at_construction(name, make, server, tmp_path):
    with pytest.raises(ValueError):
        make(server, tmp_path, max_response_bytes=10)
    with pytest.raises(ValueError):
        make(server, tmp_path, total_timeout=0)


def test_github_http_error_body_is_still_surfaced(server):
    server.status, server.payload = 422, b'{"message": "Validation Failed"}'
    call, _ = _github(server)
    server.payload, server.status = b'{"message": "Validation Failed"}', 422
    r = call()
    assert r.success is False and "GitHub API error 422" in r.error and "Validation Failed" in r.error


def test_github_huge_error_body_is_bounded(server):
    server.mode, server.status = "big", 500
    r = _github(server)[0]()
    assert r.success is False and "GitHub API error 500" in r.error
    assert len(r.error) < 17_000


def _fake(payload: dict):
    m = MagicMock()
    m.read.return_value = json.dumps(payload).encode()
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


def test_per_operation_timeouts_are_unchanged():
    with patch("urllib.request.urlopen", return_value=_fake({"results": []})) as m:
        search_web(WebSearchConfig(provider=TavilySearchProvider(api_key="k")), "q")
        search_web(WebSearchConfig(provider=SerperSearchProvider(api_key="k")), "q")
    assert [c.kwargs["timeout"] for c in m.call_args_list] == [15.0, 15.0]
    with patch("urllib.request.urlopen", return_value=_fake({"items": []})) as m:
        search_github_repositories(GitHubSearchConfig(), "q")
    assert m.call_args.kwargs["timeout"] == 15.0


def test_vision_per_operation_timeout_is_unchanged(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.jpg").write_bytes(JPEG)
    cfg = VisionConfig(provider=GeminiVisionProvider(api_key="k", model="m"),
                       sandbox=FileOpsConfig(root_dir=str(root)))
    with patch("urllib.request.urlopen", return_value=_fake(
            {"candidates": [{"content": {"parts": [{"text": "a cat"}]}}]})) as m:
        r = describe_image(cfg, "a.jpg")
    assert r.success is True and m.call_args.kwargs["timeout"] == 60

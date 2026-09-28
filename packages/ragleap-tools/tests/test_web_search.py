"""Tests for ragleap_tools.web_search - SearchProvider implementations,
search_web(), and make_web_search_tool(). Uses a fake SearchProvider
for the Tool/ToolResult wiring tests (mirrors test_search.py's
FakeRagLeap approach), and mocks urllib.request.urlopen directly for
the provider-specific request-building tests, so each provider's real
payload/header construction is actually exercised, not bypassed."""
import json
from unittest.mock import MagicMock, patch

from ragleap_tools.web_search import (
    SearchProvider,
    SerperSearchProvider,
    TavilySearchProvider,
    WebSearchConfig,
    make_web_search_tool,
    search_web,
)


class FakeSearchProvider(SearchProvider):
    """Stands in for a real provider. search_calls records every
    call's arguments so tests can assert on what search_web actually
    passed through."""

    def __init__(self, results=None, raise_error=None):
        self._results = results if results is not None else []
        self._raise_error = raise_error
        self.search_calls = []

    def search(self, query, num_results=5):
        self.search_calls.append({"query": query, "num_results": num_results})
        if self._raise_error is not None:
            raise self._raise_error
        return self._results


def _fake_response(payload: dict):
    """Builds a MagicMock standing in for urlopen()'s context-managed
    response object."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(payload).encode("utf-8")
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    return mock_response


def test_search_web_returns_results_from_provider():
    provider = FakeSearchProvider(results=[{"title": "A", "url": "http://a", "snippet": "..."}])
    config = WebSearchConfig(provider=provider)

    result = search_web(config, "test query")

    assert result.success is True
    assert result.result["count"] == 1
    assert result.result["results"][0]["title"] == "A"


def test_search_web_passes_through_query_and_num_results():
    provider = FakeSearchProvider(results=[])
    config = WebSearchConfig(provider=provider)

    search_web(config, "test query", num_results=10)

    assert provider.search_calls == [{"query": "test query", "num_results": 10}]


def test_search_web_catches_unexpected_errors():
    provider = FakeSearchProvider(raise_error=RuntimeError("provider exploded"))
    config = WebSearchConfig(provider=provider)

    result = search_web(config, "query")

    assert result.success is False
    assert "provider exploded" in result.error


def test_make_web_search_tool_returns_bound_tool():
    provider = FakeSearchProvider(results=[{"title": "bound", "url": "http://x", "snippet": "y"}])
    config = WebSearchConfig(provider=provider)
    tool = make_web_search_tool(config)

    assert tool.name == "search_web"
    result = tool.call(query="test")

    assert result.success is True
    assert result.result["results"][0]["title"] == "bound"


def test_make_web_search_tool_has_valid_openai_schema():
    config = WebSearchConfig(provider=FakeSearchProvider())
    tool = make_web_search_tool(config)
    schema = tool.to_openai_schema()

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "search_web"
    assert schema["function"]["parameters"]["required"] == ["query"]


def test_make_web_search_tool_has_valid_gemini_schema():
    config = WebSearchConfig(provider=FakeSearchProvider())
    tool = make_web_search_tool(config)
    schema = tool.to_gemini_schema()

    assert schema["name"] == "search_web"
    assert "parameters" in schema


@patch("ragleap_tools.web_search.urllib.request.urlopen")
def test_tavily_provider_builds_correct_request(mock_urlopen):
    mock_urlopen.return_value = _fake_response({
        "results": [{"title": "T", "url": "http://t", "content": "tavily snippet"}]
    })
    provider = TavilySearchProvider(api_key="fake-key")

    results = provider.search("test query", num_results=3)

    assert results == [{"title": "T", "url": "http://t", "snippet": "tavily snippet"}]
    sent_request = mock_urlopen.call_args[0][0]
    sent_payload = json.loads(sent_request.data.decode("utf-8"))
    assert sent_payload == {"query": "test query", "max_results": 3}
    assert "api_key" not in sent_payload  # key belongs in the header, not the body
    assert sent_request.headers.get("Authorization") == "Bearer fake-key"


@patch("ragleap_tools.web_search.urllib.request.urlopen")
def test_tavily_provider_handles_empty_results(mock_urlopen):
    mock_urlopen.return_value = _fake_response({"results": []})
    provider = TavilySearchProvider(api_key="fake-key")

    results = provider.search("query")

    assert results == []


@patch("ragleap_tools.web_search.urllib.request.urlopen")
def test_serper_provider_builds_correct_request(mock_urlopen):
    mock_urlopen.return_value = _fake_response({
        "organic": [{"title": "S", "link": "http://s", "snippet": "serper snippet"}]
    })
    provider = SerperSearchProvider(api_key="fake-key")

    results = provider.search("test query", num_results=7)

    assert results == [{"title": "S", "url": "http://s", "snippet": "serper snippet"}]
    sent_request = mock_urlopen.call_args[0][0]
    sent_payload = json.loads(sent_request.data.decode("utf-8"))
    assert sent_payload == {"q": "test query", "num": 7}
    assert sent_request.headers.get("X-api-key") == "fake-key"


@patch("ragleap_tools.web_search.urllib.request.urlopen")
def test_serper_provider_handles_empty_results(mock_urlopen):
    mock_urlopen.return_value = _fake_response({"organic": []})
    provider = SerperSearchProvider(api_key="fake-key")

    results = provider.search("query")

    assert results == []


@patch("ragleap_tools.web_search.urllib.request.urlopen")
def test_search_web_wraps_network_error_from_real_provider(mock_urlopen):
    import urllib.error
    mock_urlopen.side_effect = urllib.error.URLError("connection refused")
    provider = TavilySearchProvider(api_key="fake-key")
    config = WebSearchConfig(provider=provider)

    result = search_web(config, "query")

    assert result.success is False
    assert "connection refused" in result.error


def test_search_web_clamps_num_results_to_maximum():
    provider = FakeSearchProvider(results=[])
    search_web(WebSearchConfig(provider=provider), "q", num_results=10000)
    assert provider.search_calls[0]["num_results"] == 20


def test_search_web_clamps_num_results_to_minimum():
    provider = FakeSearchProvider(results=[])
    search_web(WebSearchConfig(provider=provider), "q", num_results=0)
    search_web(WebSearchConfig(provider=provider), "q", num_results=-5)
    assert [c["num_results"] for c in provider.search_calls] == [1, 1]


def test_search_web_coerces_numeric_string_num_results():
    provider = FakeSearchProvider(results=[])
    search_web(WebSearchConfig(provider=provider), "q", num_results="7")
    assert provider.search_calls[0]["num_results"] == 7


def test_search_web_rejects_non_integer_num_results_without_calling_provider():
    provider = FakeSearchProvider(results=[])
    result = search_web(WebSearchConfig(provider=provider), "q", num_results="lots")
    assert result.success is False
    assert "num_results" in result.error
    assert provider.search_calls == []

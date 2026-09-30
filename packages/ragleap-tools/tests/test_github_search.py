"""Tests for ragleap_tools.github_search - GitHubSearchConfig,
search_github_repositories(), and make_github_search_tool(). Mocks
urllib.request.urlopen directly so the real URL/header construction is
exercised, mirroring test_web_search.py's approach for the two
SearchProvider implementations."""
import json
import urllib.parse
from unittest.mock import MagicMock, patch

from ragleap_tools.github_search import (
    GitHubSearchConfig,
    make_github_search_tool,
    search_github_repositories,
)


def _fake_response(payload: dict):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(payload).encode("utf-8")
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = False
    return mock_response


def _query_params(request):
    return urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)


@patch("ragleap_tools.github_search.urllib.request.urlopen")
def test_returns_normalized_results(mock_urlopen):
    mock_urlopen.return_value = _fake_response({
        "total_count": 1,
        "items": [{
            "full_name": "octocat/Hello-World",
            "html_url": "https://github.com/octocat/Hello-World",
            "description": "My first repo",
            "stargazers_count": 42,
            "language": "Python",
        }],
    })
    config = GitHubSearchConfig()

    result = search_github_repositories(config, "hello world")

    assert result.success is True
    assert result.result["count"] == 1
    assert result.result["results"][0] == {
        "full_name": "octocat/Hello-World",
        "url": "https://github.com/octocat/Hello-World",
        "description": "My first repo",
        "stars": 42,
        "language": "Python",
    }


@patch("ragleap_tools.github_search.urllib.request.urlopen")
def test_handles_missing_description_and_language(mock_urlopen):
    mock_urlopen.return_value = _fake_response({
        "items": [{"full_name": "a/b", "html_url": "http://x", "stargazers_count": 0}],
    })
    result = search_github_repositories(GitHubSearchConfig(), "q")
    assert result.result["results"][0]["description"] == ""
    assert result.result["results"][0]["language"] == ""


@patch("ragleap_tools.github_search.urllib.request.urlopen")
def test_no_token_sends_no_authorization_header(mock_urlopen):
    mock_urlopen.return_value = _fake_response({"items": []})
    search_github_repositories(GitHubSearchConfig(), "query")

    sent_request = mock_urlopen.call_args[0][0]
    assert "Authorization" not in sent_request.headers


@patch("ragleap_tools.github_search.urllib.request.urlopen")
def test_token_sends_bearer_authorization_header(mock_urlopen):
    mock_urlopen.return_value = _fake_response({"items": []})
    search_github_repositories(GitHubSearchConfig(token="fake-token"), "query")

    sent_request = mock_urlopen.call_args[0][0]
    assert sent_request.headers.get("Authorization") == "Bearer fake-token"


@patch("ragleap_tools.github_search.urllib.request.urlopen")
def test_always_sends_user_agent(mock_urlopen):
    mock_urlopen.return_value = _fake_response({"items": []})
    search_github_repositories(GitHubSearchConfig(), "query")

    sent_request = mock_urlopen.call_args[0][0]
    assert sent_request.headers.get("User-agent")


@patch("ragleap_tools.github_search.urllib.request.urlopen")
def test_builds_correct_query_params(mock_urlopen):
    mock_urlopen.return_value = _fake_response({"items": []})
    search_github_repositories(GitHubSearchConfig(), "language:python llm", num_results=7, sort="stars")

    sent_request = mock_urlopen.call_args[0][0]
    params = _query_params(sent_request)
    assert params["q"] == ["language:python llm"]
    assert params["per_page"] == ["7"]
    assert params["sort"] == ["stars"]


@patch("ragleap_tools.github_search.urllib.request.urlopen")
def test_omits_sort_param_when_not_given(mock_urlopen):
    mock_urlopen.return_value = _fake_response({"items": []})
    search_github_repositories(GitHubSearchConfig(), "query")

    sent_request = mock_urlopen.call_args[0][0]
    assert "sort" not in _query_params(sent_request)


def test_clamps_num_results_to_maximum():
    with patch("ragleap_tools.github_search.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _fake_response({"items": []})
        search_github_repositories(GitHubSearchConfig(), "q", num_results=9999)
        sent_request = mock_urlopen.call_args[0][0]
        assert _query_params(sent_request)["per_page"] == ["20"]


def test_rejects_non_integer_num_results_without_making_request():
    with patch("ragleap_tools.github_search.urllib.request.urlopen") as mock_urlopen:
        result = search_github_repositories(GitHubSearchConfig(), "q", num_results="lots")
        assert result.success is False
        assert "num_results" in result.error
        mock_urlopen.assert_not_called()


@patch("ragleap_tools.github_search.urllib.request.urlopen")
def test_http_error_surfaces_status_and_body(mock_urlopen):
    import urllib.error
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="http://x", code=422, msg="Unprocessable", hdrs=None,
        fp=MagicMock(read=lambda: b'{"message": "Validation Failed"}'),
    )
    result = search_github_repositories(GitHubSearchConfig(), "bad(query")

    assert result.success is False
    assert "422" in result.error
    assert "Validation Failed" in result.error


@patch("ragleap_tools.github_search.urllib.request.urlopen")
def test_network_error_is_caught(mock_urlopen):
    import urllib.error
    mock_urlopen.side_effect = urllib.error.URLError("connection refused")
    result = search_github_repositories(GitHubSearchConfig(), "q")

    assert result.success is False
    assert "connection refused" in result.error


@patch("ragleap_tools.github_search.urllib.request.urlopen")
def test_make_tool_returns_bound_tool(mock_urlopen):
    mock_urlopen.return_value = _fake_response({
        "items": [{"full_name": "x/y", "html_url": "http://x", "stargazers_count": 1}],
    })
    tool = make_github_search_tool(GitHubSearchConfig(token="t"))

    assert tool.name == "search_github_repositories"
    result = tool.call(query="test")
    assert result.success is True
    assert result.result["results"][0]["full_name"] == "x/y"


def test_make_tool_has_valid_openai_schema():
    tool = make_github_search_tool(GitHubSearchConfig())
    schema = tool.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "search_github_repositories"
    assert schema["function"]["parameters"]["required"] == ["query"]


def test_make_tool_has_valid_gemini_schema():
    tool = make_github_search_tool(GitHubSearchConfig())
    schema = tool.to_gemini_schema()
    assert schema["name"] == "search_github_repositories"
    assert "parameters" in schema

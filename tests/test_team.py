"""Tests for core/employees/team.py (item #7). No DB/network: the LLM and ask_fn are mocked."""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.employees import team


def _svc(*replies):
    s = MagicMock()
    s.primary_config = {"provider": "x"}
    s._call_provider.side_effect = [r if isinstance(r, Exception) else (r, None) for r in replies]
    return s


def _res(answer, role, sources=("d",), used=True):
    return {"answer": answer, "sources": list(sources), "chunks_used": 2, "detected_language": "en",
            "provider_used": "gemini" if used else None, "routed_role": role, "routing_method": "llm"}


def test_parse_subtasks_valid_and_capped():
    out = team._parse_subtasks('["a","b","c","d","e"]')
    assert len(out) == team.TEAM_MAX_SUBTASKS and out[:2] == ["a", "b"]


def test_parse_subtasks_garbage_returns_empty():
    assert team._parse_subtasks("no list here") == []
    assert team._parse_subtasks('{"a": 1}') == []
    assert team._parse_subtasks('["", 5]') == []


def test_split_empty_reply_retried_with_bigger_budget():
    svc = _svc("", '["a","b"]')
    assert team.split_task("q", svc) == ["a", "b"]
    assert svc._call_provider.call_count == 2
    assert svc._call_provider.call_args_list[-1].args[3] == team.TEAM_MAX_TOKENS * 2


def test_split_failure_returns_empty():
    assert team.split_task("q", _svc(Exception("boom"))) == []


def test_run_team_happy_path():
    ask_fn = MagicMock(side_effect=[_res("price answer", "sales", ("p",)), _res("refund answer", "support", ("r",))])
    svc = _svc('["prices?","returns?"]', "merged reply")
    out = team.run_team("both?", ask_fn, svc)
    assert out["answer"] == "merged reply"
    assert ask_fn.call_count == 2
    for c in ask_fn.call_args_list:
        assert c.kwargs["role"] == "auto" and c.kwargs["trusted"] is False
    assert [c.args[0] for c in ask_fn.call_args_list] == ["prices?", "returns?"]
    assert out["sources"] == ["p", "r"] and out["chunks_used"] == 4
    assert out["routing_method"] == "team" and out["provider_used"] == "gemini"
    assert out["team"] == [
        {"subtask": "prices?", "role": "sales", "method": "llm"},
        {"subtask": "returns?", "role": "support", "method": "llm"},
    ]


def test_run_team_trusted_flag_passed_through():
    ask_fn = MagicMock(side_effect=[_res("a", "manager"), _res("b", "hr")])
    team.run_team("q", ask_fn, _svc('["x","y"]', "m"), trusted=True)
    assert all(c.kwargs["trusted"] is True for c in ask_fn.call_args_list)


def test_single_subtask_falls_back_to_one_normal_ask():
    ask_fn = MagicMock(return_value=_res("single", "support"))
    out = team.run_team("q", ask_fn, _svc('["only one"]'))
    assert ask_fn.call_count == 1 and ask_fn.call_args.args[0] == "q"
    assert out["answer"] == "single"


def test_split_failure_falls_back_to_single_answer():
    ask_fn = MagicMock(return_value=_res("single", "support"))
    out = team.run_team("q", ask_fn, _svc(Exception("boom")))
    assert ask_fn.call_count == 1 and out["answer"] == "single"


def test_failed_sub_answer_falls_back_to_single_answer():
    ask_fn = MagicMock(side_effect=[_res("x", "sales", used=False), _res("single", "support")])
    out = team.run_team("q", ask_fn, _svc('["a","b"]'))
    assert out["answer"] == "single"
    assert ask_fn.call_args_list[-1].args[0] == "q"


def test_merge_failure_joins_answers_and_keeps_notes():
    ask_fn = MagicMock(side_effect=[_res("A\n\nNote: verify independently", "legal_intake"), _res("B", "support")])
    out = team.run_team("q", ask_fn, _svc('["a","b"]', Exception("boom")))
    assert "Note: verify independently" in out["answer"] and "B" in out["answer"]

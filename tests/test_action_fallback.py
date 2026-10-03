"""
Tests for actions.call_with_fallback: the planner and the agent loop survive a busy
provider (retry once, then the LLM_FALLBACK_PROVIDERS chain). Fake service; no network.
"""
import json

import pytest

from core import agent_loop
from core.employees import actions


class Svc:
    def __init__(self, behaviour, chain=None):
        self.behaviour = {k: list(v) for k, v in behaviour.items()}
        self.chain = chain
        self.calls = []
        self.primary_config = {"provider": "p1"}

    def _fallback_chain(self):
        if self.chain is None:
            raise RuntimeError("no chain")
        return [{"provider": n} for n in self.chain]

    def _call_provider(self, config, prompt, temperature, max_tokens):
        self.calls.append((config["provider"], max_tokens))
        r = self.behaviour[config["provider"]].pop(0)
        if isinstance(r, Exception):
            raise r
        return r, {}


def busy():
    return RuntimeError("503 UNAVAILABLE high demand")


def test_retries_the_same_provider_once_then_succeeds():
    svc = Svc({"p1": [busy(), "ok"]}, chain=["p1"])
    assert actions.call_with_fallback(svc, "x", 100) == "ok"
    assert svc.calls == [("p1", 100), ("p1", 100)]


def test_falls_back_to_the_next_provider():
    svc = Svc({"p1": [busy(), busy()], "p2": ["fine"]}, chain=["p1", "p2"])
    assert actions.call_with_fallback(svc, "x", 100) == "fine"
    assert svc.calls == [("p1", 100), ("p1", 100), ("p2", 100)]


def test_empty_reply_doubles_the_budget_then_tries_the_next_provider():
    svc = Svc({"p1": ["", ""], "p2": ["x"]}, chain=["p1", "p2"])
    assert actions.call_with_fallback(svc, "q", 100) == "x"
    assert svc.calls == [("p1", 100), ("p1", 200), ("p2", 100)]


def test_all_providers_failing_raises_the_last_error():
    svc = Svc({"p1": [busy(), busy()], "p2": [busy(), RuntimeError("last one")]}, chain=["p1", "p2"])
    with pytest.raises(RuntimeError, match="last one"):
        actions.call_with_fallback(svc, "x", 100)


def test_all_empty_returns_empty_string():
    assert actions.call_with_fallback(Svc({"p1": ["", ""]}, chain=["p1"]), "x", 100) == ""


def test_service_without_a_chain_uses_the_primary():
    assert actions.call_with_fallback(Svc({"p1": ["ok"]}, chain=None), "x", 100) == "ok"


def test_unusable_chain_object_falls_back_to_the_primary():
    class Weird(Svc):
        def _fallback_chain(self):
            return object()
    assert actions.call_with_fallback(Weird({"p1": ["ok"]}), "x", 100) == "ok"


def test_plan_action_survives_a_busy_primary(monkeypatch):
    monkeypatch.setenv("ACTION_TASKS_ENABLED", "true")
    plan = json.dumps({"tool": "create_task", "target": "", "content": "Call the vendor"})
    svc = Svc({"p1": [busy(), busy()], "p2": [plan]}, chain=["p1", "p2"])
    out = actions.plan_action("please create a task to call the vendor", "ans", svc)
    assert out and out["tool"] == "create_task" and out["content"] == "Call the vendor"


def test_agent_loop_model_call_uses_the_fallback(monkeypatch):
    monkeypatch.setattr(agent_loop.budget, "check_budget", lambda role=None: None)
    svc = Svc({"p1": [busy(), busy()], "p2": ["hello"]}, chain=["p1", "p2"])
    assert agent_loop._llm(svc, "p", None) == "hello"

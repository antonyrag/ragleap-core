"""v0.2.0 behaviour: unparseable replies stop the run, bounded repair, honest rejected summaries.
Scripted fake model, no network."""
import json

import pytest
from ragleap_tools import Tool, ToolResult

import ragleap_agents.agent as agent_mod
from ragleap_agents import TRUSTED, Agent, Policy, ToolPolicy
from ragleap_agents.agent import MAX_REPAIR_ATTEMPTS

DONE = json.dumps({"tool": "done"})


def plan(tool, **arguments):
    return json.dumps({"tool": tool, "arguments": arguments})


class FakeLLM:
    def __init__(self, replies, tick=None):
        self.replies, self.prompts, self.tick = list(replies), [], tick

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if self.tick:
            self.tick()
        if not self.replies:
            raise RuntimeError("no scripted reply left")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _schema(**props):
    return {"type": "object", "properties": {k: {"type": v} for k, v in props.items()}, "required": list(props)}


def build(replies, repair=0, summarize=False, tick=None, **policy_kw):
    log = []
    tools = [
        Tool("calc", "Evaluate", _schema(expression="string"), lambda expression: ToolResult(True, "42")),
        Tool("fetch", "Read a page", _schema(url="string"), lambda url: (log.append(("fetch", url)), ToolResult(True, "page"))[1]),
        Tool("send", "Send", _schema(message="string"), lambda message: (log.append(("send", message)), ToolResult(True, "sent"))[1]),
    ]
    pol = Policy(tools={"calc": TRUSTED, "fetch": ToolPolicy(True, False), "send": ToolPolicy(False, True)},
                 repair_attempts=repair, **policy_kw)
    llm = FakeLLM(replies, tick)
    return Agent(llm, tools, pol, summarize=summarize), llm, log


# ---- unparseable replies are stops, not successes ----

@pytest.mark.parametrize("reply", [
    "Sorry, I cannot help with that.",
    '{"tool": "calc", "arguments": {"expression": ',
    plan("calc", expression="1") + " and then " + DONE,
    "",
])
def test_unparseable_reply_stops_without_running_anything(reply):
    agent, llm, log = build([reply])
    r = agent.run("q")
    assert (r.status, r.stop_reason, r.steps) == ("stopped", "unparseable_reply", []) and log == []
    assert len(llm.prompts) == 1


def test_object_without_a_tool_key_is_an_invalid_plan():
    agent, _, _ = build([json.dumps({"answer": "42"})])
    r = agent.run("q")
    assert (r.status, r.stop_reason) == ("stopped", "invalid_plan")


def test_explicit_done_is_still_done():
    for reply in (DONE, json.dumps({"tool": ""}), json.dumps({"tool": "none"})):
        agent, _, _ = build([reply])
        assert agent.run("q").status == "done"


def test_prose_after_a_real_step_stops_and_keeps_the_transcript():
    agent, _, _ = build([plan("calc", expression="1"), "The answer is 42."])
    r = agent.run("q")
    assert (r.status, r.stop_reason, len(r.steps)) == ("stopped", "unparseable_reply", 1)
    assert r.answer.startswith("1 step(s): calc.") and "Stopped: unparseable_reply" in r.answer


# ---- bounded repair ----

def test_repair_is_off_by_default():
    agent, llm, _ = build(["nope", plan("calc", expression="1"), DONE])
    assert agent.run("q").stop_reason == "unparseable_reply" and len(llm.prompts) == 1


def test_one_repair_fixes_a_bad_reply_and_the_note_does_not_echo_the_reply():
    bad = "SECRET-MODEL-TEXT not json"
    agent, llm, _ = build([bad, plan("calc", expression="1"), DONE], repair=1)
    r = agent.run("q")
    assert (r.status, r.stop_reason, len(r.steps)) == ("done", "done", 1)
    assert "rejected: it was not a single JSON object" in llm.prompts[1]
    assert "SECRET-MODEL-TEXT" not in llm.prompts[1]
    assert llm.prompts[1].startswith(llm.prompts[0])
    assert "rejected" not in llm.prompts[2]  # the note applies to one proposal only


def test_repair_for_an_unknown_tool_does_not_echo_its_name():
    agent, llm, _ = build([plan("hack_the_planet", x="1"), plan("calc", expression="1"), DONE], repair=1)
    assert agent.run("q").status == "done"
    assert "hack_the_planet" not in llm.prompts[1] and "not available" in llm.prompts[1]


def test_repair_for_bad_arguments_reports_the_schema_problem():
    agent, llm, _ = build([plan("calc"), plan("calc", expression="1"), DONE], repair=1)
    assert agent.run("q").status == "done"
    assert "missing required argument 'expression'" in llm.prompts[1]


def test_repair_is_bounded_and_capped():
    agent, llm, _ = build(["x"] * 10, repair=1)
    assert agent.run("q").stop_reason == "unparseable_reply" and len(llm.prompts) == 2
    agent, llm, _ = build(["x"] * 10, repair=99)
    assert agent.run("q").stop_reason == "unparseable_reply" and len(llm.prompts) == 1 + MAX_REPAIR_ATTEMPTS


def test_a_repaired_proposal_gets_no_shortcut_around_taint_and_approval():
    agent, log = None, None
    agent, llm, log = build([plan("fetch", url="u"), "garbage", plan("send", message="hi"), DONE], repair=1)
    r = agent.run("q")
    assert r.status == "awaiting_approval" and r.pending["forced"] is True and log == [("fetch", "u")]
    r2 = agent.resume(r.run_id, {r.pending["call_id"]: False})
    assert r2.status == "rejected" and ("send", "hi") not in log


def test_repair_respects_the_deadline():
    clock = {"t": 0.0}
    monkey = pytest.MonkeyPatch()
    monkey.setattr(agent_mod, "_now", lambda: clock["t"])
    try:
        agent, llm, _ = build(["x", plan("calc", expression="1"), DONE], repair=2,
                              tick=lambda: clock.__setitem__("t", clock["t"] + 100), deadline_seconds=10)
        r = agent.run("q")
    finally:
        monkey.undo()
    assert (r.status, r.stop_reason) == ("stopped", "deadline") and len(llm.prompts) == 1


def test_model_failure_during_repair_is_reported_without_its_text():
    agent, _, _ = build(["x", RuntimeError("api-key=SECRET")], repair=1)
    r = agent.run("q")
    assert (r.status, r.stop_reason) == ("failed", "model_error") and "SECRET" not in r.answer


# ---- rejected runs are described honestly ----

def test_rejected_run_summary_counts_only_calls_that_ran():
    agent, _, _ = build([plan("fetch", url="u"), plan("send", message="hi")])
    r = agent.run("q")
    r2 = agent.resume(r.run_id, {r.pending["call_id"]: False})
    assert r2.status == "rejected"
    assert r2.answer.startswith("1 step(s): fetch.") and "send" not in r2.answer.split("Stopped")[0]
    assert [s["status"] for s in r2.steps] == ["executed", "rejected"]  # the transcript still records the rejection

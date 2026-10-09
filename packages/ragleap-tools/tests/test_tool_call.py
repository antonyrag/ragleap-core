import inspect

import pytest

from ragleap_tools import Tool, ToolResult


def make():
    return Tool(name="t", description="d", parameters={"type": "object", "properties": {}},
                handler=lambda **kw: ToolResult(success=True, result=kw))


def test_an_argument_named_self_reaches_the_handler():
    r = make().call(self="x", other=1)
    assert r.success is True and r.result == {"self": "x", "other": 1}


def test_normal_calls_still_work():
    assert make().call(a=1).result == {"a": 1}
    assert make().call().result == {}


def test_arguments_must_still_be_keywords():
    with pytest.raises(TypeError):
        make().call("x")


def test_self_is_positional_only_in_the_signature():
    assert inspect.signature(Tool.call).parameters["self"].kind is inspect.Parameter.POSITIONAL_ONLY

from ragleap_tools.calculator import calculate, CALCULATOR_TOOL


def test_basic_arithmetic():
    assert calculate("2 + 2").result == 4
    assert calculate("10 - 3").result == 7
    assert calculate("6 * 7").result == 42
    assert calculate("10 / 4").result == 2.5
    assert calculate("2 ** 10").result == 1024


def test_functions_and_constants():
    assert calculate("sqrt(16)").result == 4.0
    assert abs(calculate("sin(0)").result - 0.0) < 1e-9
    assert calculate("abs(-5)").result == 5
    assert round(calculate("pi").result, 2) == 3.14


def test_division_by_zero():
    r = calculate("10 / 0")
    assert not r.success
    assert "ZeroDivisionError" in r.error


def test_empty_expression():
    r = calculate("")
    assert not r.success


def test_expression_too_long():
    r = calculate("1+" * 200)
    assert not r.success


def test_rejects_import_call():
    r = calculate('__import__("os").system("ls")')
    assert not r.success


def test_rejects_attribute_access():
    r = calculate("(1).__class__")
    assert not r.success


def test_rejects_arbitrary_names():
    r = calculate("x + 1")
    assert not r.success


def test_rejects_list_comprehension():
    r = calculate("[x for x in range(10)]")
    assert not r.success


def test_rejects_multi_statement():
    r = calculate("1; import os")
    assert not r.success


def test_tool_schema_shape():
    schema = CALCULATOR_TOOL.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "calculator"
    assert "expression" in schema["function"]["parameters"]["properties"]

    gemini_schema = CALCULATOR_TOOL.to_gemini_schema()
    assert gemini_schema["name"] == "calculator"


def test_tool_call_matches_direct_call():
    r1 = calculate("3 + 4")
    r2 = CALCULATOR_TOOL.call(expression="3 + 4")
    assert r1.result == r2.result == 7

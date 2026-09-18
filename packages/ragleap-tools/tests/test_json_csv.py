from ragleap_tools.json_csv import parse_json, parse_csv


def test_parse_valid_json():
    r = parse_json('{"a": 1, "b": [1, 2, 3]}')
    assert r.success
    assert r.result == {"a": 1, "b": [1, 2, 3]}


def test_parse_invalid_json():
    r = parse_json("not json")
    assert not r.success


def test_parse_csv_with_header():
    r = parse_csv("name,age\nAlice,30\nBob,25")
    assert r.success
    assert r.result[0]["name"] == "Alice"
    assert r.result[1]["age"] == "25"


def test_parse_csv_without_header():
    r = parse_csv("Alice,30\nBob,25", has_header=False)
    assert r.success
    assert r.result[0] == ["Alice", "30"]

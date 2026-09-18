from ragleap_tools.datetime_tools import get_current_datetime, add_to_date, date_difference


def test_get_current_datetime_succeeds():
    r = get_current_datetime()
    assert r.success
    assert "T" in r.result  # ISO format


def test_add_days():
    r = add_to_date("2026-01-01T00:00:00", days=30)
    assert r.success
    assert r.result.startswith("2026-01-31")


def test_subtract_via_negative():
    r = add_to_date("2026-01-31T00:00:00", days=-30)
    assert r.success
    assert r.result.startswith("2026-01-01")


def test_date_difference():
    r = date_difference("2026-01-31T00:00:00", "2026-01-01T00:00:00")
    assert r.success
    assert r.result["days"] == 30


def test_invalid_datetime_string():
    r = add_to_date("not a date", days=1)
    assert not r.success

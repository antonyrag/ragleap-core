import pytest
from fastapi.testclient import TestClient

from core import api, auth_throttle

H = {"x-api-key": "k-test"}
BAD = {"x-api-key": "wrong"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "RAGLEAP_API_KEY", "k-test")
    monkeypatch.setenv("AUTH_MAX_FAILURES", "3")
    clock = {"t": 1000.0}
    monkeypatch.setattr(auth_throttle, "_clock", lambda: clock["t"])
    c = TestClient(api.app)
    c.clock = clock
    return c


def codes(client, headers, n, path="/settings"):
    return [client.get(path, headers=headers).status_code for _ in range(n)]


def test_lockout_after_max_failures(client):
    assert codes(client, BAD, 3) == [401, 401, 429]
    r = client.get("/settings", headers=H)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert "k-test" not in r.text and "wrong" not in r.text


def test_lockout_expires(client):
    codes(client, BAD, 3)
    client.clock["t"] += 901
    assert client.get("/settings", headers=H).status_code == 200


def test_failures_outside_the_window_do_not_add_up(client):
    codes(client, BAD, 2)
    client.clock["t"] += 301
    assert codes(client, BAD, 2) == [401, 401]
    assert client.get("/settings", headers=H).status_code == 200


def test_success_resets_the_count(client):
    codes(client, BAD, 2)
    assert client.get("/settings", headers=H).status_code == 200
    assert codes(client, BAD, 2) == [401, 401]


def test_missing_key_is_not_counted(client):
    assert codes(client, {}, 10) == [401] * 10
    assert client.get("/settings", headers=H).status_code == 200


def test_throttle_can_be_turned_off(client, monkeypatch):
    monkeypatch.setenv("AUTH_THROTTLE", "off")
    assert codes(client, BAD, 20) == [401] * 20


def test_spoofed_forwarded_header_does_not_evade_the_limit(client):
    got = [client.get("/settings", headers={"x-api-key": "wrong", "x-forwarded-for": "198.51.100.%d" % i}).status_code
           for i in range(3)]
    assert got == [401, 401, 429]


def test_trusted_proxy_separates_real_clients(client, monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "testclient")
    a_bad = {"x-api-key": "wrong", "x-forwarded-for": "198.51.100.1"}
    assert codes(client, a_bad, 3) == [401, 401, 429]
    b_ok = {"x-api-key": "k-test", "x-forwarded-for": "198.51.100.2"}
    assert client.get("/settings", headers=b_ok).status_code == 200
    a_ok = {"x-api-key": "k-test", "x-forwarded-for": "198.51.100.1"}
    assert client.get("/settings", headers=a_ok).status_code == 429


def test_public_page_and_health_stay_reachable_during_lockout(client):
    codes(client, BAD, 3)
    for path in ("/health", "/office", "/office/app.js", "/office/app.css"):
        assert client.get(path).status_code == 200, path


def test_client_id_ignores_forwarded_header_unless_peer_is_trusted(monkeypatch):
    assert auth_throttle.client_id("10.0.0.5", "1.2.3.4") == "10.0.0.5"
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/24")
    assert auth_throttle.client_id("10.0.0.5", "1.2.3.4") == "1.2.3.4"
    assert auth_throttle.client_id("192.0.2.9", "1.2.3.4") == "192.0.2.9"


def test_client_id_takes_the_rightmost_untrusted_hop(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.5, 10.0.0.6")
    assert auth_throttle.client_id("10.0.0.5", "9.9.9.9, 1.2.3.4, 10.0.0.6") == "1.2.3.4"
    assert auth_throttle.client_id("10.0.0.5", "10.0.0.6") == "10.0.0.5"


def test_client_id_falls_back_on_garbage(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.5")
    assert auth_throttle.client_id("10.0.0.5", "not-an-ip") == "10.0.0.5"
    assert auth_throttle.client_id("10.0.0.5", "1.2.3.4, <script>") == "10.0.0.5"


def test_client_id_normalises_and_handles_a_missing_peer():
    assert auth_throttle.client_id("", "") == "unknown"
    assert auth_throttle.client_id("2001:DB8:0:0:0:0:0:1", "") == "2001:db8::1"


def test_settings_are_clamped_and_fall_back(monkeypatch):
    assert (auth_throttle.max_failures(), auth_throttle.window_seconds(), auth_throttle.lockout_seconds()) == (10, 300, 900)
    monkeypatch.setenv("AUTH_MAX_FAILURES", "0")
    assert auth_throttle.max_failures() == 1
    monkeypatch.setenv("AUTH_MAX_FAILURES", "abc")
    assert auth_throttle.max_failures() == 10
    monkeypatch.setenv("AUTH_LOCKOUT_SECONDS", "999999")
    assert auth_throttle.lockout_seconds() == 86400


def test_record_failure_locks_at_the_limit_and_reset_clears(monkeypatch):
    monkeypatch.setenv("AUTH_MAX_FAILURES", "2")
    assert auth_throttle.record_failure("x") == 0
    assert auth_throttle.record_failure("x") == 900
    assert auth_throttle.blocked_seconds("x") > 0 and auth_throttle.blocked_seconds("y") == 0
    auth_throttle.reset()
    assert auth_throttle.blocked_seconds("x") == 0


def test_tracking_is_bounded(monkeypatch):
    monkeypatch.setattr(auth_throttle, "MAX_TRACKED_CLIENTS", 5)
    for i in range(30):
        auth_throttle.record_failure("c%d" % i)
    assert len(auth_throttle._failures) <= 5

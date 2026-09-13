"""
Tests for core/queue.py - the optional Redis-backed task queue.

No real Redis required: these mock at the module boundary (core.queue's
internal state + the redis/rq imports) so the fallback-to-inline behavior
and the queue-configured behavior are both covered without needing a live
Redis instance. Live end-to-end verification (a real worker actually
processing a real enqueued job) is done separately via docker compose,
not here - that's an integration concern, not a unit-test one.
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import queue as queue_module


def _reset_queue_module_state():
    """core/queue.py caches its connection/queue at module level (lazy
    singleton) - reset it between tests so one test's state doesn't leak
    into the next."""
    queue_module._connection = None
    queue_module._queue = None
    queue_module._unavailable_logged = False


def test_enqueue_sync_runs_inline_when_redis_url_unset():
    _reset_queue_module_state()
    with patch.object(queue_module, "REDIS_URL", ""), \
         patch("core.integrations.service.sync_data_source", return_value={"synced": 3}) as mock_sync:
        result = queue_module.enqueue_sync("source-123")

    mock_sync.assert_called_once_with("source-123")
    assert result == {"status": "ran_inline", "result": {"synced": 3}}


def test_enqueue_sync_uses_queue_when_redis_configured_and_reachable():
    _reset_queue_module_state()
    fake_job = MagicMock(id="job-abc")
    fake_queue_instance = MagicMock()
    fake_queue_instance.enqueue.return_value = fake_job
    fake_redis_conn = MagicMock()

    with patch.object(queue_module, "REDIS_URL", "redis://fake:6379/0"), \
         patch("redis.from_url", return_value=fake_redis_conn), \
         patch("rq.Queue", return_value=fake_queue_instance), \
         patch("core.integrations.service.sync_data_source") as mock_sync:
        result = queue_module.enqueue_sync("source-456")

    fake_redis_conn.ping.assert_called_once()
    fake_queue_instance.enqueue.assert_called_once()
    mock_sync.assert_not_called()
    assert result == {"status": "enqueued", "job_id": "job-abc"}


def test_falls_back_to_inline_when_redis_configured_but_unreachable():
    _reset_queue_module_state()
    with patch.object(queue_module, "REDIS_URL", "redis://unreachable:6379/0"), \
         patch("redis.from_url", side_effect=ConnectionError("refused")), \
         patch("core.integrations.service.sync_data_source", return_value={"synced": 1}) as mock_sync:
        result = queue_module.enqueue_sync("source-789")

    mock_sync.assert_called_once_with("source-789")
    assert result == {"status": "ran_inline", "result": {"synced": 1}}


def test_get_queue_returns_none_when_redis_url_unset():
    _reset_queue_module_state()
    with patch.object(queue_module, "REDIS_URL", ""):
        assert queue_module._get_queue() is None


def test_get_queue_caches_connection_across_calls():
    _reset_queue_module_state()
    fake_queue_instance = MagicMock()

    with patch.object(queue_module, "REDIS_URL", "redis://fake:6379/0"), \
         patch("redis.from_url", return_value=MagicMock()) as mock_from_url, \
         patch("rq.Queue", return_value=fake_queue_instance):
        first = queue_module._get_queue()
        second = queue_module._get_queue()

    assert first is second
    mock_from_url.assert_called_once()

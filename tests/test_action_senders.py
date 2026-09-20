"""Tests for core/action_senders.py: no network, DNS/HTTP/SMTP mocked."""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import action_senders as a
from core import autonomy

PUBLIC = [(2, 1, 6, "", ("93.184.216.34", 443))]
ENV = {"WEBHOOK_TARGETS": "n8n=https://hooks.example.com/abc?x=1,crm=https://crm.example.com/in"}
EMAIL_ENV = {
    "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587", "SMTP_USER": "u",
    "SMTP_PASSWORD": "p", "SMTP_FROM": "bot@example.com",
    "EMAIL_ALLOWED_RECIPIENTS": "boss@acme.com,@partner.com",
}


def _addr(ip):
    return [(2, 1, 6, "", (ip, 443))]


def _smtp():
    cls = MagicMock()
    smtp = MagicMock()
    cls.return_value.__enter__.return_value = smtp
    return cls, smtp


def test_webhook_unknown_target_fails_without_request():
    with patch.dict(os.environ, ENV), patch.object(a.requests, "post") as post:
        assert a.send_webhook("evil", "hi") is False
    post.assert_not_called()


def test_webhook_known_target_posts_without_redirects():
    with patch.dict(os.environ, ENV), patch.object(a.socket, "getaddrinfo", return_value=PUBLIC), \
         patch.object(a.requests, "post", return_value=MagicMock(status_code=200)) as post:
        assert a.send_webhook("n8n", "hello") is True
    assert post.call_args.args[0] == "https://hooks.example.com/abc?x=1"
    assert post.call_args.kwargs["allow_redirects"] is False
    assert post.call_args.kwargs["json"]["text"] == "hello"


def test_webhook_non_public_addresses_blocked():
    for ip in ("10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.10", "100.64.0.1"):
        with patch.dict(os.environ, ENV), patch.object(a.socket, "getaddrinfo", return_value=_addr(ip)), \
             patch.object(a.requests, "post") as post:
            assert a.send_webhook("n8n", "hi") is False, ip
        post.assert_not_called()


def test_webhook_http_scheme_blocked():
    env = {"WEBHOOK_TARGETS": "n8n=http://hooks.example.com/abc"}
    with patch.dict(os.environ, env), patch.object(a.socket, "getaddrinfo", return_value=PUBLIC), \
         patch.object(a.requests, "post") as post:
        assert a.send_webhook("n8n", "hi") is False
    post.assert_not_called()


def test_webhook_non_2xx_is_failure():
    with patch.dict(os.environ, ENV), patch.object(a.socket, "getaddrinfo", return_value=PUBLIC), \
         patch.object(a.requests, "post", return_value=MagicMock(status_code=500)):
        assert a.send_webhook("n8n", "hi") is False


def test_webhook_request_exception_returns_false():
    with patch.dict(os.environ, ENV), patch.object(a.socket, "getaddrinfo", return_value=PUBLIC), \
         patch.object(a.requests, "post", side_effect=Exception("boom")):
        assert a.send_webhook("n8n", "hi") is False


def test_slack_requires_slack_hosted_url():
    for bad in ("", "https://evil.example.com/x", "http://hooks.slack.com/x"):
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": bad}), patch.object(a.requests, "post") as post:
            assert a.send_slack("x", "hi") is False
        post.assert_not_called()


def test_slack_posts_when_configured():
    url = "https://hooks.slack.com/services/T/B/x"
    with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": url}), \
         patch.object(a.requests, "post", return_value=MagicMock(status_code=200)) as post:
        assert a.send_slack("label", "hello") is True
    assert post.call_args.args[0] == url and post.call_args.kwargs["json"]["text"] == "hello"
    assert post.call_args.kwargs["allow_redirects"] is False


def test_email_empty_allowlist_sends_nothing():
    cls, _smtp_obj = _smtp()
    with patch.dict(os.environ, {**EMAIL_ENV, "EMAIL_ALLOWED_RECIPIENTS": ""}), patch.object(a.smtplib, "SMTP", cls):
        assert a.send_email("boss@acme.com", "hi") is False
    cls.assert_not_called()


def test_email_unlisted_recipient_blocked():
    cls, _smtp_obj = _smtp()
    with patch.dict(os.environ, EMAIL_ENV), patch.object(a.smtplib, "SMTP", cls):
        assert a.send_email("stranger@evil.com", "hi") is False
    cls.assert_not_called()


def test_email_header_injection_and_multiple_recipients_blocked():
    cls, _smtp_obj = _smtp()
    with patch.dict(os.environ, EMAIL_ENV), patch.object(a.smtplib, "SMTP", cls):
        assert a.send_email("boss@acme.com\nBcc: x@evil.com", "hi") is False
        assert a.send_email("boss@acme.com,x@evil.com", "hi") is False
    cls.assert_not_called()


def test_email_allowed_address_sends():
    cls, smtp = _smtp()
    with patch.dict(os.environ, EMAIL_ENV), patch.object(a.smtplib, "SMTP", cls):
        assert a.send_email("boss@acme.com", "Hello body") is True
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("u", "p")
    msg = smtp.send_message.call_args.args[0]
    assert msg["To"] == "boss@acme.com" and msg["From"] == "bot@example.com"


def test_email_domain_allowlist_is_exact_domain():
    cls, _smtp_obj = _smtp()
    with patch.dict(os.environ, EMAIL_ENV), patch.object(a.smtplib, "SMTP", cls):
        assert a.send_email("anyone@partner.com", "hi") is True
        assert a.send_email("x@notpartner.com", "hi") is False
        assert a.send_email("x@sub.partner.com", "hi") is False


def test_email_subject_line_convention():
    cls, smtp = _smtp()
    with patch.dict(os.environ, EMAIL_ENV), patch.object(a.smtplib, "SMTP", cls):
        a.send_email("boss@acme.com", "Subject: Order shipped\n\nYour order left.")
        a.send_email("boss@acme.com", "no subject line here")
    first, second = [c.args[0] for c in smtp.send_message.call_args_list]
    assert first["Subject"] == "Order shipped" and "Your order left." in first.get_content()
    assert second["Subject"] == "Message from RagLeap"


def test_email_smtp_failure_returns_false():
    cls, smtp = _smtp()
    smtp.send_message.side_effect = Exception("smtp down")
    with patch.dict(os.environ, EMAIL_ENV), patch.object(a.smtplib, "SMTP", cls):
        assert a.send_email("boss@acme.com", "hi") is False


def test_autonomy_dispatch_reports_sent_or_failed_for_new_channels():
    for channel, fn, target in (("webhook", "send_webhook", "n8n"), ("slack", "send_slack", "x"),
                                ("email", "send_email", "boss@acme.com")):
        with patch.object(a, fn, return_value=True):
            assert "sent" in autonomy._send_via_channel(channel, target, "hi")
        with patch.object(a, fn, return_value=False):
            out = autonomy._send_via_channel(channel, target, "hi")
            assert "failed" in out and "sent" not in out


def test_autonomy_unknown_channel_still_unsupported():
    assert "Unsupported channel" in autonomy._send_via_channel("carrier_pigeon", "x", "hi")


def test_plain_address_rules():
    ok = ["boss@acme.com", "a.b+c@sub.example.co.uk"]
    bad = ["a@b", "@x.com", "x@", "a@@b.com", "a@b..com", "a@.com", "a@b.com.", "a b@x.com",
           "a@b.com\nBcc: x@y.com", "a@b.com,c@d.com", "a@b.com;c@d.com", "<a@b.com>", "ü@b.com", ""]
    for addr in ok:
        assert a._is_plain_address(addr), addr
    for addr in bad:
        assert not a._is_plain_address(addr), addr


def test_pathological_address_is_rejected_fast_and_length_capped():
    import time
    for evil in ("!@!." + "!." * 5000, "a" * 100000 + "@x.com", "a@" + "b." * 100000):
        t0 = time.monotonic()
        assert a._is_plain_address(evil) is False
        assert time.monotonic() - t0 < 0.5

"""
Outbound action senders for the autonomy gate (phase 1 of "broad actionable").

send_webhook / send_slack / send_email are dispatched from
core.autonomy._send_via_channel(), so every mode, allowlist, sensitive-role
rule, approval step and log in execute_or_request() applies to them unchanged.

Security model: a model (or a customer message hijacking it) must never
choose the destination.
  - webhook: `target` is a NAME looked up in WEBHOOK_TARGETS (name=url,...)
    from .env, never a raw URL. HTTPS only; hosts resolving to non-public
    addresses (private, loopback, link-local, cloud metadata) are refused;
    redirects are not followed.
  - slack: posts only to SLACK_WEBHOOK_URL from .env (must be hooks.slack.com).
  - email: recipient must match EMAIL_ALLOWED_RECIPIENTS (addresses or
    @domain entries); the default is empty, so nothing sends until configured.
Senders never raise and never log secret URLs; they return True/False.
"""
import ipaddress
import logging
import os
import re
import smtplib
import socket
from email.message import EmailMessage
from typing import Dict
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 15
MAX_TEXT = 3000


def _webhook_targets() -> Dict[str, str]:
    targets = {}
    for item in os.environ.get("WEBHOOK_TARGETS", "").split(","):
        if "=" not in item:
            continue
        name, url = item.split("=", 1)
        name, url = name.strip(), url.strip()
        if name and url:
            targets[name] = url
    return targets


def _is_public_https_url(url: str) -> bool:
    """HTTPS only, and every resolved address must be globally routable."""
    try:
        p = urlparse(url)
        if p.scheme != "https" or not p.hostname:
            return False
        infos = socket.getaddrinfo(p.hostname, p.port or 443, proto=socket.IPPROTO_TCP)
        if not infos:
            return False
        for info in infos:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
            if not ip.is_global or ip.is_multicast:
                return False
        return True
    except Exception:
        return False


def send_webhook(target: str, content: str) -> bool:
    try:
        name = (target or "").strip()
        url = _webhook_targets().get(name)
        if not url:
            logger.error(f"Webhook target '{name}' is not in WEBHOOK_TARGETS - refused")
            return False
        if not _is_public_https_url(url):
            logger.error(f"Webhook target '{name}' is not a public https URL - refused")
            return False
        resp = requests.post(
            url, json={"text": (content or "")[:MAX_TEXT], "source": "ragleap"},
            timeout=HTTP_TIMEOUT, allow_redirects=False,
        )
        return 200 <= resp.status_code < 300
    except Exception as e:
        logger.error(f"Webhook send error: {e}")
        return False


SLACK_PREFIX = "https://hooks.slack.com/"


def send_slack(target: str, content: str) -> bool:
    """`target` is only a label; the destination is always SLACK_WEBHOOK_URL."""
    try:
        url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        if not url.startswith(SLACK_PREFIX):
            logger.error("SLACK_WEBHOOK_URL is not set to a hooks.slack.com URL - refused")
            return False
        resp = requests.post(
            url, json={"text": (content or "")[:MAX_TEXT]},
            timeout=HTTP_TIMEOUT, allow_redirects=False,
        )
        return 200 <= resp.status_code < 300
    except Exception as e:
        logger.error(f"Slack send error: {e}")
        return False


_EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def _recipient_allowed(addr: str) -> bool:
    """Exactly one plain address, and it must be on EMAIL_ALLOWED_RECIPIENTS
    (full addresses, or '@domain.com' entries matching that exact domain)."""
    addr = (addr or "").strip().lower()
    if not _EMAIL_RE.match(addr):
        return False
    for entry in os.environ.get("EMAIL_ALLOWED_RECIPIENTS", "").split(","):
        entry = entry.strip().lower()
        if not entry:
            continue
        if entry.startswith("@"):
            if addr.endswith(entry):
                return True
        elif addr == entry:
            return True
    return False


def send_email(target: str, content: str) -> bool:
    """Optional first line 'Subject: ...' becomes the subject; rest is the body."""
    try:
        host = os.environ.get("SMTP_HOST", "").strip()
        user = os.environ.get("SMTP_USER", "").strip()
        from_addr = os.environ.get("SMTP_FROM", "").strip() or user
        if not host or not from_addr:
            logger.error("SMTP_HOST / SMTP_FROM not configured - email refused")
            return False
        if not _recipient_allowed(target):
            logger.error("Email recipient is not in EMAIL_ALLOWED_RECIPIENTS - refused")
            return False
        subject, body = "Message from RagLeap", content or ""
        first, _, rest = body.partition("\n")
        if first.lower().startswith("subject:"):
            subject = first[8:].strip().replace("\r", " ")[:200] or subject
            body = rest.lstrip("\n")
        msg = EmailMessage()
        msg["From"] = from_addr
        msg["To"] = target.strip()
        msg["Subject"] = subject
        msg.set_content(body[:MAX_TEXT * 4])
        port = int(os.environ.get("SMTP_PORT", "587") or 587)
        password = os.environ.get("SMTP_PASSWORD", "")
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                smtp.starttls()
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        return True
    except Exception as e:
        logger.error(f"Email send error: {e}")
        return False

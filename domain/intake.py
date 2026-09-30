"""Turn a raw email or a shared message into an input row. Nothing is fetched, opened or replied to."""
from email import message_from_string, policy
from email.utils import parseaddr, parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import re
from typing import Any


class _LinkCollector(HTMLParser):
    """Collects visible text and (link text, link target) pairs from an HTML body."""

    def __init__(self):
        super().__init__()
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._label = dict(attrs).get("href") or "", []

    def handle_data(self, data):
        self.text.append(data)
        if self._href is not None:
            self._label.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((" ".join("".join(self._label).split()), self._href))
            self._href = None


def _short_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha1(value.encode('utf-8', 'replace')).hexdigest()[:8]}"


def email_to_row(raw: str) -> dict[str, Any]:
    message = message_from_string(raw, policy=policy.default)
    body_part = message.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content() if body_part is not None else ""
    links: list[tuple[str, str]] = []
    if body_part is not None and body_part.get_content_type() == "text/html":
        collector = _LinkCollector()
        collector.feed(body)
        body, links = " ".join(" ".join(collector.text).split()), collector.links
    sender_name, sender = parseaddr(str(message.get("From", "")))
    try:
        timestamp = parsedate_to_datetime(str(message.get("Date", ""))).isoformat()
    except (TypeError, ValueError):
        timestamp = ""
    authentication = str(message.get("Authentication-Results", "")).lower()
    return {
        "report_id": _short_id("E", str(message.get("Message-ID") or raw)),
        "timestamp": timestamp,
        "source": "email",
        "payload": f"{message.get('Subject', '')}\n{body}".strip(),
        "metadata": {
            "sender": sender.lower(),
            "sender_name": sender_name,
            "reply_to": parseaddr(str(message.get("Reply-To", "")))[1].lower(),
            "auth_fail": bool(re.search(r"\b(spf|dkim|dmarc)=fail", authentication)),
            "links": links,
        },
    }


def share_to_row(text: str, sender: str, channel: str, timestamp: str) -> dict[str, Any]:
    """A message the person or caregiver shared by hand, for example an SMS."""
    return {
        "report_id": _short_id("S", f"{timestamp}|{sender}|{text}"),
        "timestamp": timestamp,
        "source": channel,
        "payload": text,
        "metadata": {"sender": sender, "sender_name": ""},
    }

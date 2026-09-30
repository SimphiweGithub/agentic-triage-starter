"""Optional live inbox: read unread emails from a dedicated mailbox and hand each one to the engine.

The mailbox is one created for Scam Stop. The protected person's own mailbox
forwards to it, so the agent never holds the password to their real account.
"""
import imaplib
import os
import threading
import time
from typing import Callable


def connect_from_env() -> imaplib.IMAP4_SSL:
    connection = imaplib.IMAP4_SSL(os.environ["IMAP_HOST"])
    connection.login(os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"])
    return connection


def poll_once(connect: Callable[[], imaplib.IMAP4], handle: Callable[[str], object]) -> int:
    """Pass the raw text of every unread email to `handle`. Returns how many were read."""
    connection = connect()
    try:
        connection.select("INBOX")
        _, found = connection.search(None, "UNSEEN")
        numbers = found[0].split()
        for number in numbers:
            _, parts = connection.fetch(number, "(RFC822)")  # fetching the full email also marks it as read
            handle(parts[0][1].decode("utf-8", "replace"))
        return len(numbers)
    finally:
        connection.logout()


def start_polling(handle: Callable[[str], object]) -> threading.Thread | None:
    """Start a background thread that checks the mailbox every few seconds. Does nothing unless IMAP_HOST is set."""
    if not os.getenv("IMAP_HOST"):
        return None
    seconds = float(os.getenv("IMAP_POLL_SECONDS", "15"))

    def loop() -> None:
        while True:
            try:
                poll_once(connect_from_env, handle)
            except Exception as error:  # a mailbox problem must never stop the server
                print(f"mailbox check failed: {type(error).__name__}: {error}")
            time.sleep(seconds)

    thread = threading.Thread(target=loop, daemon=True, name="mailbox")
    thread.start()
    return thread

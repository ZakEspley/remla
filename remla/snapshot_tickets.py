"""Short-lived bearer capabilities for private still downloads."""

import secrets
import time


class SnapshotTickets:
    def __init__(self, clock=time.monotonic, ttl=30, max_bytes=25_000_000):
        self.clock = clock
        self.ttl = ttl
        self.max_bytes = max_bytes
        self._ticket = None

    def issue(self, owner, image: bytes) -> str:
        if not isinstance(image, bytes) or not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Snapshot must be a PNG")
        if not 8 < len(image) <= self.max_bytes:
            raise ValueError("Snapshot exceeds the byte limit")
        token = secrets.token_urlsafe(32)
        self._ticket = (token, owner, image, self.clock() + self.ttl)
        return token

    def consume(self, token: str, can_download) -> bytes | None:
        ticket = self._ticket
        if ticket is None:
            return None
        expected, owner, image, expires = ticket
        if self.clock() >= expires:
            self._ticket = None
            return None
        if not isinstance(token, str) or not secrets.compare_digest(token, expected):
            return None
        if not can_download(owner):
            return None
        self._ticket = None
        return image

    def revoke(self, owner) -> None:
        if self._ticket is not None and self._ticket[1] is owner:
            self._ticket = None

    def clear(self) -> None:
        self._ticket = None

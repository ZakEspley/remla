import unittest
from unittest import mock

from remla.snapshot_tickets import SnapshotTickets


class SnapshotTicketTests(unittest.TestCase):
    def setUp(self):
        self.clock = mock.Mock(return_value=100.0)
        self.owner = object()
        self.tickets = SnapshotTickets(clock=self.clock, ttl=30, max_bytes=1024)
        self.image = b"\x89PNG\r\n\x1a\n" + b"png-data"

    def test_ticket_is_one_use_and_not_a_public_file_path(self):
        token = self.tickets.issue(self.owner, self.image)
        self.assertGreaterEqual(len(token), 40)
        self.assertNotIn("/", token)
        self.assertEqual(self.tickets.consume(token, lambda owner: owner is self.owner), self.image)
        self.assertIsNone(self.tickets.consume(token, lambda owner: True))

    def test_wrong_owner_does_not_consume_and_revocation_clears_ticket(self):
        token = self.tickets.issue(self.owner, self.image)
        self.assertIsNone(self.tickets.consume(token, lambda owner: False))
        self.tickets.revoke(self.owner)
        self.assertIsNone(self.tickets.consume(token, lambda owner: True))

    def test_expired_ticket_cannot_be_downloaded(self):
        token = self.tickets.issue(self.owner, self.image)
        self.clock.return_value = 130.0
        self.assertIsNone(self.tickets.consume(token, lambda owner: True))

    def test_rejects_bad_or_oversized_images(self):
        with self.assertRaises(ValueError):
            self.tickets.issue(self.owner, b"not a PNG")
        with self.assertRaises(ValueError):
            self.tickets.issue(self.owner, self.image + b"a" * 1024)

    def test_new_ticket_replaces_previous_owner_ticket(self):
        old_token = self.tickets.issue(self.owner, self.image)
        new_token = self.tickets.issue(self.owner, self.image)
        self.assertIsNone(self.tickets.consume(old_token, lambda owner: True))
        self.assertEqual(self.tickets.consume(new_token, lambda owner: True), self.image)


if __name__ == "__main__":
    unittest.main()

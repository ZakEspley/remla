import unittest
from pathlib import Path


CLIENT = Path(__file__).resolve().parents[1] / "remla" / "setup" / "remlaJsonSocket.js"


class JsonWebSocketClientTests(unittest.TestCase):
    def test_command_message_ids_have_a_crypto_uuid_fallback(self):
        content = CLIENT.read_text(encoding="utf-8")

        self.assertIn("function createMessageId()", content)
        self.assertIn("browserCrypto?.randomUUID", content)
        self.assertIn("browserCrypto?.getRandomValues", content)
        self.assertIn("const messageId = createMessageId()", content)


if __name__ == "__main__":
    unittest.main()

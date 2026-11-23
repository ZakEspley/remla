import importlib
import json
import unittest
import uuid
from unittest import mock

from remla.snapshot_config import SnapshotConfig
from remla.snapshot_service import SnapshotBusy, SnapshotUnavailable


Experiment = importlib.import_module("remla.labcontrol.Experiment").Experiment


class Client:
    subprotocol = "remla-json-v1"

    def __init__(self):
        self.frames = []

    async def send(self, frame):
        self.frames.append(json.loads(frame))


class SnapshotAPITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.experiment = Experiment("test")
        self.experiment._runtime_state = "ready"
        self.experiment.snapshot_config = SnapshotConfig("cam", 2592, 1944)
        self.owner, self.visitor = Client(), Client()
        self.experiment.clients.extend([self.owner, self.visitor])
        self.experiment.ownership.connect(self.owner)
        self.experiment.ownership.connect(self.visitor)
        self.image = b"\x89PNG\r\n\x1a\nimage"
        self.experiment.snapshot_service = mock.Mock(capture_png=mock.AsyncMock(return_value=self.image))

    async def command(self, client, parameters=None):
        message_id = str(uuid.uuid4())
        await self.experiment.process_json_frame(json.dumps({
            "meta": {"messageId": message_id, "version": "1.0.0"},
            "type": "command", "payload": {
                "deviceName": "Experiment", "commandName": "capture_still",
                "parameters": {} if parameters is None else parameters,
            },
        }), client)
        return next(frame["payload"] for frame in client.frames
                    if frame["type"] == "result" and frame["meta"]["replyId"] == message_id)

    async def test_owner_receives_only_private_capability_and_metadata(self):
        payload = await self.command(self.owner)
        self.assertTrue(payload["ok"])
        data = payload["data"]
        self.assertEqual((data["width"], data["height"], data["mimeType"]), (2592, 1944, "image/png"))
        self.assertEqual(data["downloadPath"], "ws/snapshot")
        self.assertNotIn(data["token"], data["downloadPath"])
        self.assertNotIn("png", str(self.visitor.frames))
        self.assertEqual(self.experiment.snapshot_tickets.consume(data["token"], lambda _: True), self.image)

    async def test_failed_result_send_does_not_log_the_private_token(self):
        class ClosedConnection(Exception):
            pass

        self.owner.send = mock.AsyncMock(side_effect=ClosedConnection())
        with (mock.patch("remla.labcontrol.Experiment.ConnectionClosed", ClosedConnection),
              mock.patch("remla.labcontrol.Experiment.logging.warning") as warning,
              mock.patch("builtins.print") as output,
              mock.patch.object(self.experiment.snapshot_tickets, "issue", return_value="private-ticket-123")):
            await self.command_without_response(self.owner)
        self.assertNotIn("private-ticket-123", str(warning.call_args_list))
        self.assertNotIn("private-ticket-123", str(output.call_args_list))

    async def command_without_response(self, client):
        await self.experiment.process_json_frame(json.dumps({
            "meta": {"messageId": str(uuid.uuid4()), "version": "1.0.0"},
            "type": "command", "payload": {
                "deviceName": "Experiment", "commandName": "capture_still", "parameters": {},
            },
        }), client)

    async def test_queued_client_is_denied_without_camera_access(self):
        payload = await self.command(self.visitor)
        self.assertEqual(payload["status"], 403)
        self.experiment.snapshot_service.capture_png.assert_not_awaited()

    async def test_lab_config_omission_disables_api(self):
        self.experiment.snapshot_config = None
        payload = await self.command(self.owner)
        self.assertEqual(payload["status"], 403)
        self.experiment.snapshot_service.capture_png.assert_not_awaited()

    async def test_unexpected_parameters_are_rejected(self):
        payload = await self.command(self.owner, {"camera": "cam"})
        self.assertEqual(payload["status"], 400)
        self.experiment.snapshot_service.capture_png.assert_not_awaited()

    async def test_busy_and_helper_failure_do_not_issue_tokens(self):
        for error, status in ((SnapshotBusy(), 429), (SnapshotUnavailable(), 503)):
            with self.subTest(error=type(error).__name__):
                self.experiment.snapshot_service.capture_png.side_effect = error
                payload = await self.command(self.owner)
                self.assertEqual(payload["status"], status)
                self.assertIsNone(self.experiment.snapshot_tickets._ticket)

    async def test_owner_change_during_capture_discards_image(self):
        async def change_owner(*args):
            self.experiment.ownership.disconnect(self.owner)
            return self.image

        self.experiment.snapshot_service.capture_png.side_effect = change_owner
        payload = await self.command(self.owner)
        self.assertFalse(payload["ok"])
        self.assertIsNone(self.experiment.snapshot_tickets._ticket)


if __name__ == "__main__":
    unittest.main()

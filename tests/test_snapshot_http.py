import asyncio
import importlib
import unittest
import urllib.error
import urllib.request

import websockets


Experiment = importlib.import_module("remla.labcontrol.Experiment").Experiment


class SnapshotHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.experiment = Experiment("test")
        self.owner = object()
        self.experiment._runtime_state = "ready"
        self.experiment.clients.append(self.owner)
        self.experiment.ownership.connect(self.owner)
        self.server = await websockets.serve(
            lambda websocket, path: None,
            "127.0.0.1", 0,
            process_request=self.experiment.snapshot_http_response,
        )
        self.url = f"http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/ws/snapshot"

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def get(self, token=None, path=None):
        def request():
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(path or self.url, headers=headers), timeout=2
                ) as response:
                    return response.status, response.headers, response.read()
            except urllib.error.HTTPError as error:
                return error.code, error.headers, error.read()

        return await asyncio.to_thread(request)

    async def test_bearer_download_is_private_one_use_and_not_cached(self):
        image = b"\x89PNG\r\n\x1a\n" + b"png-data"
        token = self.experiment.snapshot_tickets.issue(self.owner, image)
        self.assertEqual((await self.get())[0], 404)
        self.assertEqual((await self.get("wrong"))[0], 404)
        status, headers, payload = await self.get(token)
        self.assertEqual(status, 200)
        self.assertEqual(payload, image)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual((await self.get(token))[0], 404)

    async def test_stale_owner_cannot_redeem_ticket(self):
        token = self.experiment.snapshot_tickets.issue(self.owner, b"\x89PNG\r\n\x1a\nimage")
        self.experiment.ownership.disconnect(self.owner)
        self.assertEqual((await self.get(token))[0], 404)

    async def test_no_other_http_path_serves_snapshot(self):
        token = self.experiment.snapshot_tickets.issue(self.owner, b"\x89PNG\r\n\x1a\nimage")
        self.assertEqual((await self.get(token, self.url + "/extra"))[0], 404)
        self.assertEqual((await self.get(token))[0], 200)


if __name__ == "__main__":
    unittest.main()

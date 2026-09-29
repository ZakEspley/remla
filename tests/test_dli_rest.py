import unittest

from remla.dli_rest import DliRestClient


class Response:
    def __init__(self, value=True):
        self.value = value

    def raise_for_status(self):
        return None

    def json(self):
        return self.value


class Session:
    def __init__(self, response=None):
        self.response = response or Response()
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


class DliRestClientTests(unittest.TestCase):
    def test_reads_zero_based_physical_state(self):
        session = Session(Response(True))
        client = DliRestClient("http://pdu", "user", "password", session=session)

        self.assertTrue(client.get_physical_state(4))
        self.assertEqual(session.calls[0][0:2], ("GET", "http://pdu/restapi/relay/outlets/4/physical_state/"))

    def test_sets_one_outlet_and_all_outlets(self):
        session = Session()
        client = DliRestClient("http://pdu", "user", "password", session=session)

        client.set_state(4, True)
        client.set_all_states(False)

        self.assertEqual(session.calls[0][0:2], ("PUT", "http://pdu/restapi/relay/outlets/4/state/"))
        self.assertEqual(session.calls[0][2]["data"], {"value": "true"})
        self.assertEqual(session.calls[1][0:2], ("PUT", "http://pdu/restapi/relay/outlets/all;/state/"))
        self.assertEqual(session.calls[1][2]["data"], {"value": "false"})

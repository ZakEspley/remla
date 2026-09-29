from urllib.parse import urljoin

import requests


class DliRestError(RuntimeError):
    pass


class DliRestClient:
    def __init__(self, base_url, username, password, timeout=10, session=None):
        self.base_url = base_url.rstrip("/") + "/restapi/"
        self.auth = requests.auth.HTTPDigestAuth(username, password)
        self.timeout = timeout
        self.session = session or requests.Session()

    def _request(self, method, path, **kwargs):
        response = self.session.request(
            method,
            urljoin(self.base_url, path),
            auth=self.auth,
            timeout=self.timeout,
            **kwargs,
        )
        try:
            response.raise_for_status()
        except requests.RequestException as error:
            raise DliRestError(f"DLI REST {method} {path} failed") from error
        return response

    def get_physical_state(self, outlet_index):
        response = self._request(
            "GET",
            f"relay/outlets/{outlet_index}/physical_state/",
            headers={"Accept": "application/json"},
        )
        value = response.json()
        if not isinstance(value, bool):
            raise DliRestError("DLI REST returned an invalid physical outlet state")
        return value

    def set_state(self, outlet_index, enabled):
        self._request(
            "PUT",
            f"relay/outlets/{outlet_index}/state/",
            headers={"X-CSRF": "x"},
            data={"value": "true" if enabled else "false"},
        )

    def set_all_states(self, enabled):
        self.set_states("all;", enabled)

    def set_states(self, outlet_indexes, enabled):
        if isinstance(outlet_indexes, str):
            selector = outlet_indexes
        else:
            selector = "=" + ",".join(str(index) for index in outlet_indexes)
        self._request(
            "PUT",
            f"relay/outlets/{selector}/state/",
            headers={"X-CSRF": "x"},
            data={"value": "true" if enabled else "false"},
        )

"""Bounded, public presentation state for a single running lab."""

import json
import math
import re


NAMESPACE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,31}\Z")
KEY = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,47}\Z")


class UIState:
    def __init__(self):
        self.revision = 0
        self.namespaces = {}

    def snapshot(self):
        return {
            "revision": self.revision,
            "namespaces": {name: values.copy() for name, values in self.namespaces.items()},
        }

    def update(self, parameters):
        if not isinstance(parameters, dict) or set(parameters) != {"namespace", "values"}:
            raise ValueError("UI state requires namespace and values")
        namespace = parameters["namespace"]
        values = parameters["values"]
        if not isinstance(namespace, str) or not NAMESPACE.fullmatch(namespace):
            raise ValueError("Invalid UI namespace")
        if not isinstance(values, dict) or len(values) > 16:
            raise ValueError("UI values must be an object with at most 16 keys")
        if namespace not in self.namespaces and values and len(self.namespaces) >= 8:
            raise ValueError("Too many UI namespaces")
        for key, value in values.items():
            if not isinstance(key, str) or not KEY.fullmatch(key):
                raise ValueError("Invalid UI state key")
            if value is not None and type(value) not in (str, bool, int, float):
                raise ValueError("UI values must be scalar")
            if isinstance(value, str) and len(value) > 80:
                raise ValueError("UI string is too long")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("UI numbers must be finite")
        if len(json.dumps(parameters, ensure_ascii=False).encode("utf-8")) > 2048:
            raise ValueError("UI update is too large")
        if values:
            self.namespaces[namespace] = values.copy()
        else:
            self.namespaces.pop(namespace, None)
        self.revision += 1

    def clear(self):
        if not self.namespaces:
            return False
        self.namespaces.clear()
        self.revision += 1
        return True

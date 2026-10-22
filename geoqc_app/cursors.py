"""Opaque, authenticated positions. Cursors never substitute for authorization."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from typing import Any

from geoqc_app.errors import AppError


class CursorSigner:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Clave de cursor incompatible")
        self.key = key

    def encode(self, binding: dict[str, Any], position: int) -> str:
        raw = json.dumps({"version": 1, "binding": binding, "position": position}, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
        payload = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        signature = hmac.new(self.key, payload.encode("ascii"), hashlib.sha256).hexdigest()
        return payload + "." + signature

    def decode(self, token: str | None, binding: dict[str, Any]) -> int:
        if token is None:
            return 0
        try:
            if len(token) > 2048 or not re.fullmatch(r"[A-Za-z0-9_-]+\.[a-f0-9]{64}", token):
                raise ValueError
            payload, signature = token.split(".")
            expected = hmac.new(self.key, payload.encode("ascii"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            raw = base64.b64decode(payload + "=" * (-len(payload) % 4), altchars=b"-_", validate=True)
            if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != payload:
                raise ValueError
            decoded = json.loads(raw)
            if (decoded["version"] != 1 or decoded["binding"] != binding
                    or type(decoded["position"]) is not int or decoded["position"] < 0):
                raise ValueError
            return int(decoded["position"])
        except (ValueError, KeyError, TypeError) as exc:
            raise AppError(422, "INVALID_DETAIL_CURSOR", "Cursor incompatible con el dosier, colección o filtros") from exc

"""Validation for the Gateway's internal request-correlation header."""

import re

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def from_headers(headers):
    value = headers.get(REQUEST_ID_HEADER, "")
    return value if _REQUEST_ID.fullmatch(value) else None

"""Versioned canonical encodings for observation and content identities."""

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal


def decimal_text(value: Decimal) -> str:
    """Exact fixed-point encoding, independent of the active Decimal context."""
    if not value.is_finite():
        raise ValueError("non-finite decimals cannot be hashed")
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def digest(namespace: str, fields: Mapping[str, str]) -> str:
    """SHA-256 of UTF-8 JSON with sorted keys, compact separators and no newline."""
    payload = {"schema": namespace, **fields}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

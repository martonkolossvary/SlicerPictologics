"""Validated lossless numeric snapshots for Slicer's rounded scene-table storage."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import struct
from collections.abc import Sequence

SNAPSHOT_ATTRIBUTE = "Pictologics.ExactValuesJSON"
WARNING_ATTRIBUTE = "Pictologics.ValuePersistenceWarning"


def table_identity(columns: Sequence[str], text_rows: Sequence[Sequence[str]]) -> str:
    """Bind values to every non-value cell, including row order and extra columns."""
    data = json.dumps([list(columns), text_rows], ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def encode_values(values: Sequence[float], identity: str) -> str:
    if any(math.isinf(value) for value in values):
        raise ValueError("Infinite feature values cannot be persisted")
    raw = struct.pack(f">{len(values)}d", *values)
    return json.dumps({
        "version": 1,
        "count": len(values),
        "identity": identity,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "float64_be": base64.b64encode(raw).decode("ascii"),
    }, separators=(",", ":"))


def decode_values(snapshot: str, identity: str, stored_values: Sequence[float]) -> tuple[float, ...]:
    """Validate all rows before returning exact doubles; never partially restore.

    The displayed values must match either the original values or Slicer 5.12's
    six-significant-digit representation. Changed tables invalidate the snapshot.
    This is an integrity check, not authentication of an untrusted scene file.
    """
    expected_count = len(stored_values)
    # Bound decoding by the loaded table size, before allocating a decoded blob.
    if len(snapshot) > expected_count * 12 + 1024:
        raise ValueError("Exact-value snapshot is larger than the table permits")
    try:
        document = json.loads(snapshot)
        if not isinstance(document, dict) or set(document) != {"version", "count", "identity", "sha256", "float64_be"}:
            raise ValueError("Invalid exact-value snapshot structure")
        if type(document["version"]) is not int or document["version"] != 1:
            raise ValueError("Unsupported exact-value snapshot version")
        if type(document["count"]) is not int or document["count"] != expected_count:
            raise ValueError("Exact-value snapshot row count differs")
        if document["identity"] != identity:
            raise ValueError("Exact-value snapshot belongs to different table rows")
        raw = base64.b64decode(document["float64_be"], validate=True)
        if len(raw) != expected_count * 8 or hashlib.sha256(raw).hexdigest() != document["sha256"]:
            raise ValueError("Exact-value snapshot checksum or length differs")
        values = struct.unpack(f">{expected_count}d", raw)
        for original, stored in zip(values, stored_values, strict=True):
            if math.isinf(original) or not (
                (math.isnan(original) and math.isnan(stored))
                or original == stored
                or float(format(original, ".6g")) == stored
            ):
                raise ValueError("Saved table values do not match the exact-value snapshot")
        return values
    except (TypeError, UnicodeError) as exc:
        raise ValueError("Invalid exact-value snapshot encoding") from exc

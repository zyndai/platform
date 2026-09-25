"""Deterministic JSON canonicalization for cross-language signing.

Vendored from zyndai_agent.a2a.canonical (v0.6.0). MUST stay byte-for-byte
identical to the TS SDK's `canonicalJson` and the Go registry's JCS impl
— that's the foundation for cross-SDK signature verification.

Spec target: RFC 8785 JSON Canonicalization Scheme (JCS).

Implementation notes:
- Object keys are sorted by Python's str sort, which uses Unicode
  code-point order. For the strings we sign (UUIDs, FQANs, ed25519:b64,
  ISO timestamps, ASCII keys) this matches TypeScript's UTF-16 code-unit
  order exactly.
- Strings are serialized via `json.dumps(s, ensure_ascii=False)` — same
  escaping the TypeScript JSON.stringify uses for the BMP subset.
- Numbers go through `json.dumps` which uses Python's repr — same shape
  as ECMAScript's ToString for finite values. -0 normalized to 0. NaN /
  Infinity rejected (not representable in JCS).
- No whitespace.
"""

import json
import math
from typing import Any


def canonical_json(value: Any) -> str:
    """Produce the canonical UTF-8 string representation of a value."""
    return _serialize(value)


def canonical_bytes(value: Any) -> bytes:
    """Convenience wrapper — returns the UTF-8 bytes most signing
    primitives want directly.
    """
    return canonical_json(value).encode("utf-8")


def _serialize(v: Any) -> str:
    if v is None:
        return "null"

    if isinstance(v, bool):
        # bool MUST be checked before int — bool is a subclass of int in Python.
        return "true" if v else "false"

    if isinstance(v, (int, float)):
        if isinstance(v, float):
            if not math.isfinite(v):
                raise ValueError(
                    f"canonical_json: non-finite number not representable: {v!r}"
                )
            # Normalize -0.0 → 0
            if v == 0.0 and math.copysign(1.0, v) < 0:
                return "0"
        return json.dumps(v, ensure_ascii=False)

    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)

    if isinstance(v, (list, tuple)):
        items = [_serialize(item) for item in v]
        return "[" + ",".join(items) + "]"

    if isinstance(v, dict):
        for k in v.keys():
            if not isinstance(k, str):
                raise TypeError(
                    f"canonical_json: object keys must be strings, got {type(k).__name__}"
                )
        sorted_items = sorted(v.items(), key=lambda kv: kv[0])
        out = [
            json.dumps(k, ensure_ascii=False) + ":" + _serialize(val)
            for k, val in sorted_items
        ]
        return "{" + ",".join(out) + "}"

    raise TypeError(f"canonical_json: unsupported value type: {type(v).__name__}")

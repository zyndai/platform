"""
Minimal Ed25519 identity primitives for the Zynd Network.

Replaces the zyndai-agent SDK's `ed25519_identity` module with a local
implementation built directly on the `cryptography` library. We use
this module wherever we previously imported `Ed25519Keypair`,
`keypair_from_private_bytes`, `sign`, etc.

The wire format matches what the registry (and every other Zynd agent)
expects:

  - Public keys as `ed25519:<base64>` strings
  - Signatures as `ed25519:<base64>` strings
  - Private seeds as raw 32 bytes (kept in memory, never persisted)
  - HD derivation: seed[i] = sha512(dev_seed || "agdns:agent:" || i_be)[:32]
    (the "agdns:agent:" salt is a cryptographic constant — do NOT change it)
  - Agent IDs use the `zns:` prefix (assigned by the registry)
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)


@dataclass
class Keypair:
    """
    An Ed25519 keypair with just the fields our code actually uses.
    Holds the raw 32-byte seed alongside the derived public key bytes
    so we don't have to re-derive on every signing call.
    """
    private_seed: bytes
    public_key_bytes: bytes

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(self.public_key_bytes).decode()

    @property
    def public_key_string(self) -> str:
        """Canonical `ed25519:<b64>` form used in registry payloads."""
        return f"ed25519:{self.public_key_b64}"

    def sign(self, message: bytes) -> str:
        """Sign `message` and return an `ed25519:<b64>` signature string."""
        priv = Ed25519PrivateKey.from_private_bytes(self.private_seed)
        sig = priv.sign(message)
        return "ed25519:" + base64.b64encode(sig).decode()


# ── Low-level helpers ─────────────────────────────────────────────────

def keypair_from_seed(seed: bytes) -> Keypair:
    """Build a Keypair from a raw 32-byte Ed25519 seed."""
    if len(seed) != 32:
        raise ValueError(f"Ed25519 seed must be 32 bytes, got {len(seed)}")
    priv = Ed25519PrivateKey.from_private_bytes(seed)
    pub_bytes = priv.public_key().public_bytes_raw()
    return Keypair(private_seed=seed, public_key_bytes=pub_bytes)


def load_developer_seed(path: str) -> bytes:
    """
    Load the 32-byte developer seed from a JSON keypair file.
    Expected format: {"private_key": "<base64 of 32 bytes>", ...}
    """
    with open(path, "r") as f:
        data = json.load(f)
    seed = base64.b64decode(data["private_key"])
    if len(seed) != 32:
        raise ValueError(
            f"Developer seed at {path} must decode to 32 bytes, got {len(seed)}"
        )
    return seed


def derive_agent_seed(developer_seed: bytes, index: int) -> bytes:
    """
    HD-derive a 32-byte agent seed from the developer seed + an index.
    Algorithm: sha512(developer_seed || "agdns:agent:" || index_be)[:32]
    Matches the SDK's derivation spec so agents keep the same ids when
    we migrate off the SDK.
    """
    index_bytes = index.to_bytes(4, byteorder="big")
    return hashlib.sha512(
        developer_seed + b"agdns:agent:" + index_bytes
    ).digest()[:32]


def derive_agent_keypair(developer_seed: bytes, index: int) -> Keypair:
    """Convenience: derive the seed at `index` and build a Keypair."""
    return keypair_from_seed(derive_agent_seed(developer_seed, index))


def sign(seed: bytes, message: bytes) -> str:
    """
    Standalone sign helper for callers that only have raw seed bytes
    (e.g. the heartbeat manager, which stores seeds as base64 and
    reconstructs them per-call rather than holding Keypair instances).
    """
    priv = Ed25519PrivateKey.from_private_bytes(seed)
    sig = priv.sign(message)
    return "ed25519:" + base64.b64encode(sig).decode()


# ── Developer identity / derivation proof ────────────────────────────

def generate_developer_id(public_key_bytes: bytes) -> str:
    """
    Compute the canonical developer ID from an Ed25519 public key.
    Format: zns:dev:<sha256(pub)[:16].hex()>

    Matches the Go registry's identity.go::GenerateDeveloperID.
    """
    digest = hashlib.sha256(public_key_bytes).digest()
    return "zns:dev:" + digest[:16].hex()


def build_derivation_proof(
    developer_seed: bytes,
    agent_public_key_bytes: bytes,
    index: int,
) -> dict:
    """
    Build a `developer_proof` dict proving that `agent_public_key_bytes`
    was HD-derived from the developer key at `index`.

    The developer signs the exact bytes:
        agent_public_key_bytes || big_endian_uint32(index)

    This matches the Go registry's identity.go::buildProofMessage and
    zyndai_agent.ed25519_identity.create_derivation_proof.

    Returns a dict the registry expects in the `developer_proof` field:
        {
          "developer_public_key": "ed25519:<b64>",
          "entity_index": int,
          "developer_signature": "ed25519:<b64>"
        }
    """
    dev_kp = keypair_from_seed(developer_seed)
    message = agent_public_key_bytes + struct.pack(">I", index)
    signature = dev_kp.sign(message)
    return {
        "developer_public_key": dev_kp.public_key_string,
        "entity_index": index,
        "developer_signature": signature,
    }

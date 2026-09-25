
"""
Zynd Identity — Ed25519 keypairs for the Zynd Network.
Slim port of agent-persona/backend/agent/zynd_identity.py.
"""
import base64
import hashlib
import json
import struct
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


@dataclass
class Keypair:
    private_seed: bytes
    public_key_bytes: bytes

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(self.public_key_bytes).decode()

    @property
    def public_key_string(self) -> str:
        return f"ed25519:{self.public_key_b64}"

    @property
    def private_key(self) -> bytes:
        return self.private_seed

    def sign(self, message: bytes) -> str:
        priv = Ed25519PrivateKey.from_private_bytes(self.private_seed)
        sig = priv.sign(message)
        return "ed25519:" + base64.b64encode(sig).decode()


Ed25519Keypair = Keypair


def keypair_from_seed(seed: bytes) -> Keypair:
    if len(seed) != 32:
        raise ValueError(f"Ed25519 seed must be 32 bytes, got {len(seed)}")
    priv = Ed25519PrivateKey.from_private_bytes(seed)
    pub_bytes = priv.public_key().public_bytes_raw()
    return Keypair(private_seed=seed, public_key_bytes=pub_bytes)


def load_developer_seed(path: str) -> bytes:
    with open(path, "r") as f:
        data = json.load(f)
    seed = base64.b64decode(data["private_key"])
    if len(seed) != 32:
        raise ValueError(f"Developer seed must decode to 32 bytes, got {len(seed)}")
    return seed


def derive_agent_seed(developer_seed: bytes, index: int) -> bytes:
    index_bytes = index.to_bytes(4, byteorder="big")
    return hashlib.sha512(developer_seed + b"agdns:agent:" + index_bytes).digest()[:32]


def derive_agent_keypair(developer_seed: bytes, index: int) -> Keypair:
    return keypair_from_seed(derive_agent_seed(developer_seed, index))

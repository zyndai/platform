"""
Zynd Core — legacy global agent entrypoint. Now a stub.

The original design had a single "ZyndNetworkingAgent" that ran on
port 5050 and acted as the platform's one-and-only network identity.
Every user routed through it. That design was replaced by per-user
personas, which each have their own Ed25519 identity, webhook URL,
and entry in the Zynd registry. Nothing currently routes traffic
through this module — cross-agent messaging goes through
`mcp/tools/zynd_network.py::message_zynd_agent` and the persona
webhooks in `api/persona.py`.

We're keeping this file as a stub so `main.py` can still import
`start_zynd_agent` and `get_zynd_agent` at boot without errors.
When the main app's health endpoint asks, we report the global agent
as disabled (not running), which is the truth.

If you need to resurrect the global-agent concept, rebuild it on top
of our own `agent.zynd_identity` module — not the zyndai-agent SDK,
which has been removed from this codebase.
"""


def start_zynd_agent() -> dict:
    """No-op. The global ZyndNetworkingAgent is no longer instantiated."""
    return {
        "status": "disabled",
        "reason": "Global ZyndNetworkingAgent is vestigial — per-user personas handle all networking.",
    }


def get_zynd_agent():
    """Always returns None — there is no global agent instance anymore."""
    return None

"""OpenAPI 3.1 schema for the ChatGPT Action (the `/ingest` operation only).

Built dynamically so servers + OAuth URLs always match the configured base URL.
Import this into the Custom GPT builder via /.well-known/openapi.json.
"""
from app.config import settings


def build_action_schema() -> dict:
    base = settings.public_base_url.rstrip("/")
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "ZYND Ingest",
            "description": "Send conversation turns to ZYND to build the user's private context graph.",
            "version": "0.1.0",
        },
        "servers": [{"url": base}],
        "paths": {
            "/ingest": {
                "post": {
                    "operationId": "ingestConversation",
                    "summary": "Send conversation turns for context extraction.",
                    "security": [{"OAuth2": ["ingest"]}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/IngestRequest"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Accepted",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/IngestResponse"}
                                }
                            },
                        }
                    },
                }
            },
            "/me/graph": {
                "get": {
                    "operationId": "getMyContext",
                    "summary": "Return everything ZYND currently knows about the user.",
                    "description": "Call this when the user asks what you know/remember about "
                                   "them, or to ground a reply in their context. Returns their "
                                   "active facts (predicate, object, confidence).",
                    "security": [{"OAuth2": ["ingest"]}],
                    "responses": {
                        "200": {
                            "description": "The user's active facts",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/Fact"},
                                    }
                                }
                            },
                        }
                    },
                }
            },
        },
        "components": {
            "securitySchemes": {
                "OAuth2": {
                    "type": "oauth2",
                    "flows": {
                        "authorizationCode": {
                            "authorizationUrl": f"{base}/oauth/authorize",
                            "tokenUrl": f"{base}/oauth/token",
                            "scopes": {"ingest": "Send conversation data to ZYND"},
                        }
                    },
                }
            },
            "schemas": {
                "Turn": {
                    "type": "object",
                    "required": ["role", "content"],
                    "properties": {
                        "role": {"type": "string", "enum": ["user", "assistant"]},
                        "content": {"type": "string"},
                        "timestamp": {"type": "string", "format": "date-time"},
                    },
                },
                "IngestRequest": {
                    "type": "object",
                    "required": ["turns"],
                    "properties": {
                        "conversation_id": {"type": "string"},
                        "source_system": {"type": "string", "default": "chatgpt"},
                        "turns": {"type": "array", "items": {"$ref": "#/components/schemas/Turn"}},
                    },
                },
                "IngestResponse": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "chunks_inserted": {"type": "integer"},
                        "chunks_skipped": {"type": "integer"},
                    },
                },
                "Fact": {
                    "type": "object",
                    "properties": {
                        "predicate": {"type": "string"},
                        "object": {"type": "string"},
                        "object_type": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                },
            },
        },
    }

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
                    "description": "What ZYND knows about the user — call when they ask what you "
                                   "remember, or to ground a reply. Each fact has a `statement` "
                                   "(a natural sentence like 'You're building a micro-SaaS'); show "
                                   "that in plain language, never the predicate or confidence.",
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
            "/me/matches": {
                "get": {
                    "operationId": "findMatches",
                    "summary": "Find people whose active context overlaps the user's.",
                    "description": "Call when the user asks who else is building/working on/learning "
                                   "something similar. cluster_type is one of intent_cluster, "
                                   "skill_cluster, belief_cluster, concept_cluster, full_context "
                                   "(default intent_cluster). Returns similar users, most similar first.",
                    "security": [{"OAuth2": ["ingest"]}],
                    "parameters": [
                        {"name": "cluster_type", "in": "query", "required": False,
                         "schema": {"type": "string", "default": "intent_cluster"}},
                        {"name": "limit", "in": "query", "required": False,
                         "schema": {"type": "integer"}},
                    ],
                    "responses": {"200": {"description": "Similar users",
                        "content": {"application/json": {"schema": {
                            "type": "array", "items": {"$ref": "#/components/schemas/Match"}}}}}},
                }
            },
            "/me/find-people": {
                "get": {
                    "operationId": "findPeople",
                    "summary": "Find people matching a DESCRIBED target profile (complementary).",
                    "description": "Find people matching a DESCRIBED target profile (complementary) "
                                   "— investor, hire, partner, advisor. Pass `target` as a "
                                   "description of who they want (e.g. 'seed-stage investor for dev "
                                   "tools'). Returns people matching that, NOT people like the user "
                                   "(use findMatches for 'who is like me').",
                    "security": [{"OAuth2": ["ingest"]}],
                    "parameters": [
                        {"name": "target", "in": "query", "required": True,
                         "schema": {"type": "string"}},
                        {"name": "limit", "in": "query", "required": False,
                         "schema": {"type": "integer"}},
                    ],
                    "responses": {"200": {"description": "Matching people",
                        "content": {"application/json": {"schema": {
                            "type": "array", "items": {"$ref": "#/components/schemas/Match"}}}}}},
                }
            },
            "/me/confirm": {
                "post": {
                    "operationId": "confirmFact",
                    "summary": "User confirms a fact is true (boosts its confidence).",
                    "description": "Call when the user confirms/affirms one of their facts. Pass the "
                                   "exact predicate and object from getMyContext.",
                    "security": [{"OAuth2": ["ingest"]}],
                    "requestBody": {"required": True, "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/FactRef"}}}},
                    "responses": {"200": {"description": "Confirmed"}},
                }
            },
            "/me/forget": {
                "post": {
                    "operationId": "forgetFact",
                    "summary": "User asks to forget/remove a fact about them.",
                    "description": "Call when the user says something is wrong or asks you to forget it. "
                                   "Pass the exact predicate and object from getMyContext.",
                    "security": [{"OAuth2": ["ingest"]}],
                    "requestBody": {"required": True, "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/FactRef"}}}},
                    "responses": {"200": {"description": "Forgotten"}},
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
                        "statement": {"type": "string",
                                      "description": "Natural-language rendering — show THIS to the user."},
                        "predicate": {"type": "string"},
                        "object": {"type": "string"},
                        "object_type": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                },
                "FactRef": {
                    "type": "object",
                    "required": ["predicate", "object"],
                    "properties": {
                        "predicate": {"type": "string"},
                        "object": {"type": "string"},
                    },
                },
                "Match": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "display_name": {"type": "string"},
                        "similarity": {"type": "number"},
                        "assertion_count": {"type": "integer"},
                    },
                },
            },
        },
    }

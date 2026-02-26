"""Input validation for all routes."""

from typing import Optional


def validate_session_create(data: dict) -> Optional[str]:
    if not data:
        return "Request body required"
    if not data.get("alice_name", "").strip():
        return "alice_name required"
    if not data.get("memory_question", "").strip():
        return "memory_question required"
    if len(data.get("memory_question", "")) > 500:
        return "memory_question must be under 500 characters"
    if not data.get("memory_answer", "").strip():
        return "memory_answer required"
    if len(data.get("memory_answer", "")) > 500:
        return "memory_answer must be under 500 characters"
    if not isinstance(data.get("alice_pubkey_jwk"), dict):
        return "alice_pubkey_jwk must be a JWK object"
    pubkey = data["alice_pubkey_jwk"]
    if pubkey.get("kty") != "EC" or pubkey.get("crv") != "P-256":
        return "alice_pubkey_jwk must be an EC P-256 key"
    return None


def validate_verify(data: dict) -> Optional[str]:
    if not data:
        return "Request body required"
    if not data.get("bob_name", "").strip():
        return "bob_name required"
    if not data.get("answer", "").strip():
        return "answer required"
    if len(data.get("answer", "")) > 500:
        return "answer must be under 500 characters"
    if not isinstance(data.get("bob_pubkey_jwk"), dict):
        return "bob_pubkey_jwk must be a JWK object"
    pubkey = data["bob_pubkey_jwk"]
    if pubkey.get("kty") != "EC" or pubkey.get("crv") != "P-256":
        return "bob_pubkey_jwk must be an EC P-256 key"
    return None
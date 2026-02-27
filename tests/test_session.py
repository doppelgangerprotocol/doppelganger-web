"""
test_session.py — Tests for POST /api/session (Alice creates a session)

What we're protecting:
  - Raw answer text is never stored — only the embedding vector
  - alice_pubkey_jwk is stored in Redis but never returned in GET response
  - Session is created with correct initial phase
  - Bad input is rejected before hitting Redis or embedding service
"""

import json
import pytest
from unittest.mock import patch


ALICE_VEC = [0.1] * 384

VALID_PAYLOAD = {
    "alice_name": "Alice",
    "memory_question": "What did we order at Chipotle?",
    "memory_answer": "Chicken burrito bowl with extra guac",
    "alice_pubkey_jwk": {
        "kty": "EC",
        "crv": "P-256",
        "x": "f83OJ3D2xF1Bg8vub9tLe1gHMzV76e8Tus9uPHvRVEU",
        "y": "x_FEzRu9m36HLN_tue659LNpXW6pCyStikYjKIWI5a0"
    }
}


def post_session(client, payload=None, fake_redis=None):
    """Helper — create a session with mocked embed + Redis."""
    payload = payload or VALID_PAYLOAD

    with patch("app.services.session_store.redis") as mock_redis, \
         patch("app.services.embedding_client.EmbeddingClient.embed", return_value=ALICE_VEC):

        if fake_redis:
            mock_redis.from_url.return_value = fake_redis

        return client.post("/api/session", json=payload)


# ── Happy path ────────────────────────────────────────────────────────────────

class TestSessionCreation:

    def test_returns_201(self, client, fake_redis):
        resp = post_session(client, fake_redis=fake_redis)
        assert resp.status_code == 201

    def test_returns_session_id(self, client, fake_redis):
        data = post_session(client, fake_redis=fake_redis).get_json()
        assert "session_id" in data
        assert len(data["session_id"]) > 20

    def test_returns_link(self, client, fake_redis):
        data = post_session(client, fake_redis=fake_redis).get_json()
        assert "link" in data
        assert "/verify/s/" in data["link"]

    def test_returns_qr_code(self, client, fake_redis):
        data = post_session(client, fake_redis=fake_redis).get_json()
        assert "qr_code" in data
        assert data["qr_code"].startswith("data:image/png;base64,")

    def test_session_stored_in_redis(self, client, fake_redis):
        data = post_session(client, fake_redis=fake_redis).get_json()
        session_id = data["session_id"]
        stored = fake_redis.hgetall(f"session:{session_id}")
        assert stored != {}
        assert stored["alice_name"] == "Alice"
        assert stored["memory_question"] == "What did we order at Chipotle?"
        assert stored["phase"] == "WAITING_FOR_BOB"

    def test_raw_answer_not_stored(self, client, fake_redis):
        """SECURITY: Raw answer text must never be stored — only the vector."""
        data = post_session(client, fake_redis=fake_redis).get_json()
        session_id = data["session_id"]
        stored = fake_redis.hgetall(f"session:{session_id}")

        # Raw answer must not appear anywhere in Redis
        all_values = json.dumps(stored)
        assert "Chicken burrito bowl" not in all_values
        assert "extra guac" not in all_values

    def test_embedding_stored_not_raw_answer(self, client, fake_redis):
        """SECURITY: answer_embedding should be a JSON vector, not text."""
        data = post_session(client, fake_redis=fake_redis).get_json()
        session_id = data["session_id"]
        stored = fake_redis.hgetall(f"session:{session_id}")

        embedding = json.loads(stored["answer_embedding"])
        assert isinstance(embedding, list)
        assert len(embedding) == 384
        assert all(isinstance(v, float) for v in embedding)

    def test_alice_pubkey_stored_in_redis(self, client, fake_redis):
        """Alice's pubkey should be in Redis (for release after Bob passes)."""
        data = post_session(client, fake_redis=fake_redis).get_json()
        session_id = data["session_id"]
        stored = fake_redis.hgetall(f"session:{session_id}")

        pubkey = json.loads(stored["alice_pubkey_jwk"])
        assert pubkey["kty"] == "EC"
        assert pubkey["crv"] == "P-256"


# ── GET session — Bob's view ───────────────────────────────────────────────────

class TestGetSession:

    def test_returns_question_and_phase(self, client, fake_redis):
        created = post_session(client, fake_redis=fake_redis).get_json()
        session_id = created["session_id"]

        with patch("app.services.session_store.redis") as mock_redis:
            mock_redis.from_url.return_value = fake_redis
            resp = client.get(f"/api/session/{session_id}")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["alice_name"] == "Alice"
        assert data["memory_question"] == "What did we order at Chipotle?"
        assert data["phase"] == "WAITING_FOR_BOB"

    def test_alice_pubkey_absent_from_get_response(self, client, fake_redis):
        """SECURITY: alice_pubkey_jwk must NEVER appear in GET /session response."""
        created = post_session(client, fake_redis=fake_redis).get_json()
        session_id = created["session_id"]

        with patch("app.services.session_store.redis") as mock_redis:
            mock_redis.from_url.return_value = fake_redis
            resp = client.get(f"/api/session/{session_id}")

        data = resp.get_json()
        assert "alice_pubkey_jwk" not in data
        # Also check raw response body — should not appear anywhere
        assert "alice_pubkey_jwk" not in resp.get_data(as_text=True)

    def test_answer_embedding_absent_from_get_response(self, client, fake_redis):
        """Embedding vector should not be exposed to Bob."""
        created = post_session(client, fake_redis=fake_redis).get_json()
        session_id = created["session_id"]

        with patch("app.services.session_store.redis") as mock_redis:
            mock_redis.from_url.return_value = fake_redis
            resp = client.get(f"/api/session/{session_id}")

        data = resp.get_json()
        assert "answer_embedding" not in data

    def test_nonexistent_session_returns_404(self, client, fake_redis):
        with patch("app.services.session_store.redis") as mock_redis:
            mock_redis.from_url.return_value = fake_redis
            resp = client.get("/api/session/doesnotexist")
        assert resp.status_code == 404


# ── Input validation ──────────────────────────────────────────────────────────

class TestSessionValidation:

    def test_missing_alice_name(self, client, fake_redis):
        payload = {**VALID_PAYLOAD, "alice_name": ""}
        resp = post_session(client, payload=payload, fake_redis=fake_redis)
        assert resp.status_code == 400
        assert "alice_name" in resp.get_json()["error"]

    def test_missing_memory_question(self, client, fake_redis):
        payload = {**VALID_PAYLOAD, "memory_question": ""}
        resp = post_session(client, payload=payload, fake_redis=fake_redis)
        assert resp.status_code == 400

    def test_missing_memory_answer(self, client, fake_redis):
        payload = {**VALID_PAYLOAD, "memory_answer": ""}
        resp = post_session(client, payload=payload, fake_redis=fake_redis)
        assert resp.status_code == 400

    def test_question_too_long(self, client, fake_redis):
        payload = {**VALID_PAYLOAD, "memory_question": "x" * 501}
        resp = post_session(client, payload=payload, fake_redis=fake_redis)
        assert resp.status_code == 400

    def test_answer_too_long(self, client, fake_redis):
        payload = {**VALID_PAYLOAD, "memory_answer": "x" * 501}
        resp = post_session(client, payload=payload, fake_redis=fake_redis)
        assert resp.status_code == 400

    def test_invalid_pubkey_not_ec(self, client, fake_redis):
        payload = {**VALID_PAYLOAD, "alice_pubkey_jwk": {"kty": "RSA", "crv": "P-256"}}
        resp = post_session(client, payload=payload, fake_redis=fake_redis)
        assert resp.status_code == 400

    def test_invalid_pubkey_wrong_curve(self, client, fake_redis):
        payload = {**VALID_PAYLOAD, "alice_pubkey_jwk": {"kty": "EC", "crv": "P-384"}}
        resp = post_session(client, payload=payload, fake_redis=fake_redis)
        assert resp.status_code == 400

    def test_pubkey_not_a_dict(self, client, fake_redis):
        payload = {**VALID_PAYLOAD, "alice_pubkey_jwk": "not-a-jwk"}
        resp = post_session(client, payload=payload, fake_redis=fake_redis)
        assert resp.status_code == 400

    def test_empty_body(self, client, fake_redis):
        with patch("app.services.session_store.redis") as mock_redis:
            mock_redis.from_url.return_value = fake_redis
            resp = client.post("/api/session", data="", content_type="application/json")
        assert resp.status_code == 400

    def test_embedding_service_unavailable_returns_503(self, client, fake_redis):
        with patch("app.services.session_store.redis") as mock_redis, \
             patch("app.services.embedding_client.EmbeddingClient.embed", return_value=None):
            mock_redis.from_url.return_value = fake_redis
            resp = client.post("/api/session", json=VALID_PAYLOAD)
        assert resp.status_code == 503
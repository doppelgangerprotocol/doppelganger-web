"""
test_verify.py — Tests for POST /api/session/<id>/verify (Bob verifies)

What we're protecting:
  - alice_pubkey_jwk is ONLY returned on PASS — never on FAIL
  - Sessions can only be verified once (one-time use guarantee)
  - Score reflects actual semantic similarity
  - Phase transitions correctly
"""

import json
import pytest
from unittest.mock import patch


VALID_PUBKEY = {
    "kty": "EC",
    "crv": "P-256",
    "x": "f83OJ3D2xF1Bg8vub9tLe1gHMzV76e8Tus9uPHvRVEU",
    "y": "x_FEzRu9m36HLN_tue659LNpXW6pCyStikYjKIWI5a0"
}

BOB_PUBKEY = {
    "kty": "EC",
    "crv": "P-256",
    "x": "abc123def456abc123def456abc123def456abc123de",
    "y": "def456abc123def456abc123def456abc123def456ab"
}

# Vectors for PASS: high cosine similarity (~0.97)
ALICE_VEC = [0.1] * 384
BOB_PASS_VEC = [0.1] * 383 + [0.101]  # nearly identical — PASS

# Vectors for FAIL: low cosine similarity
BOB_FAIL_VEC = [0.0] * 383 + [1.0]    # orthogonal — FAIL


def create_session(client, fake_redis):
    """Helper — create a fresh session ready for Bob to verify."""
    payload = {
        "alice_name": "Alice",
        "memory_question": "What did we order at Chipotle?",
        "memory_answer": "Chicken burrito bowl with extra guac",
        "alice_pubkey_jwk": VALID_PUBKEY
    }
    with patch("app.services.session_store.redis") as mock_redis, \
         patch("app.services.embedding_client.EmbeddingClient.embed", return_value=ALICE_VEC):
        mock_redis.from_url.return_value = fake_redis
        resp = client.post("/api/session", json=payload)
    return resp.get_json()["session_id"]


def verify(client, fake_redis, session_id, answer_vec=BOB_PASS_VEC, answer_text="chicken burrito bowl extra guac"):
    """Helper — Bob submits an answer."""
    with patch("app.services.session_store.redis") as mock_redis, \
         patch("app.services.embedding_client.EmbeddingClient.embed", return_value=answer_vec):
        mock_redis.from_url.return_value = fake_redis
        return client.post(
            f"/api/session/{session_id}/verify",
            json={
                "bob_name": "Bob",
                "answer": answer_text,
                "bob_pubkey_jwk": BOB_PUBKEY
            }
        )


# ── PASS ──────────────────────────────────────────────────────────────────────

class TestVerifyPass:

    def test_pass_returns_200(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        resp = verify(client, fake_redis, session_id)
        assert resp.status_code == 200

    def test_pass_result_is_pass(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        data = verify(client, fake_redis, session_id).get_json()
        assert data["result"] == "PASS"

    def test_pass_returns_alice_pubkey(self, client, fake_redis):
        """SECURITY: alice_pubkey_jwk must be present on PASS."""
        session_id = create_session(client, fake_redis)
        data = verify(client, fake_redis, session_id).get_json()
        assert "alice_pubkey_jwk" in data
        assert data["alice_pubkey_jwk"]["kty"] == "EC"
        assert data["alice_pubkey_jwk"]["crv"] == "P-256"

    def test_pass_returns_score(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        data = verify(client, fake_redis, session_id).get_json()
        assert "score" in data
        assert data["score"] >= 75

    def test_pass_updates_phase_to_verified(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        verify(client, fake_redis, session_id)
        stored = fake_redis.hgetall(f"session:{session_id}")
        assert stored["phase"] == "VERIFIED"

    def test_pass_stores_bob_name(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        verify(client, fake_redis, session_id)
        stored = fake_redis.hgetall(f"session:{session_id}")
        assert stored["bob_name"] == "Bob"

    def test_pass_stores_similarity_score(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        verify(client, fake_redis, session_id)
        stored = fake_redis.hgetall(f"session:{session_id}")
        assert stored["similarity_score"] != ""
        assert float(stored["similarity_score"]) >= 0.75


# ── FAIL ──────────────────────────────────────────────────────────────────────

class TestVerifyFail:

    def test_fail_returns_200(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        resp = verify(client, fake_redis, session_id,
                      answer_vec=BOB_FAIL_VEC,
                      answer_text="I have no idea what we ordered")
        assert resp.status_code == 200

    def test_fail_result_is_fail(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        data = verify(client, fake_redis, session_id,
                      answer_vec=BOB_FAIL_VEC,
                      answer_text="I have no idea what we ordered").get_json()
        assert data["result"] == "FAIL"

    def test_fail_does_not_return_alice_pubkey(self, client, fake_redis):
        """SECURITY: alice_pubkey_jwk must be ABSENT on FAIL — this is the core guarantee."""
        session_id = create_session(client, fake_redis)
        resp = verify(client, fake_redis, session_id,
                      answer_vec=BOB_FAIL_VEC,
                      answer_text="I have no idea what we ordered")
        data = resp.get_json()

        assert "alice_pubkey_jwk" not in data
        # Also check raw response body
        assert "alice_pubkey_jwk" not in resp.get_data(as_text=True)

    def test_fail_score_is_low(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        data = verify(client, fake_redis, session_id,
                      answer_vec=BOB_FAIL_VEC,
                      answer_text="I have no idea").get_json()
        assert data["score"] < 75

    def test_fail_updates_phase_to_failed(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        verify(client, fake_redis, session_id,
               answer_vec=BOB_FAIL_VEC,
               answer_text="wrong answer")
        stored = fake_redis.hgetall(f"session:{session_id}")
        assert stored["phase"] == "FAILED"

    def test_fail_does_not_store_bob_pubkey(self, client, fake_redis):
        """Bob's pubkey should not be stored if he fails."""
        session_id = create_session(client, fake_redis)
        verify(client, fake_redis, session_id,
               answer_vec=BOB_FAIL_VEC,
               answer_text="wrong answer")
        stored = fake_redis.hgetall(f"session:{session_id}")
        assert stored["bob_pubkey_jwk"] == ""


# ── One-time use guarantee ────────────────────────────────────────────────────

class TestOneTimeUse:

    def test_cannot_verify_twice_after_pass(self, client, fake_redis):
        """SECURITY: Session locked after PASS — attacker cannot re-verify."""
        session_id = create_session(client, fake_redis)
        verify(client, fake_redis, session_id)  # first — PASS
        resp = verify(client, fake_redis, session_id)  # second attempt
        assert resp.status_code == 409

    def test_cannot_verify_twice_after_fail(self, client, fake_redis):
        """SECURITY: Session locked after FAIL — attacker cannot keep guessing."""
        session_id = create_session(client, fake_redis)
        verify(client, fake_redis, session_id,
               answer_vec=BOB_FAIL_VEC,
               answer_text="wrong")   # first — FAIL
        resp = verify(client, fake_redis, session_id,
                      answer_vec=BOB_PASS_VEC,
                      answer_text="correct this time")  # second attempt
        assert resp.status_code == 409

    def test_nonexistent_session_returns_404(self, client, fake_redis):
        with patch("app.services.session_store.redis") as mock_redis, \
             patch("app.services.embedding_client.EmbeddingClient.embed", return_value=BOB_PASS_VEC):
            mock_redis.from_url.return_value = fake_redis
            resp = client.post(
                "/api/session/doesnotexist/verify",
                json={"bob_name": "Bob", "answer": "test", "bob_pubkey_jwk": BOB_PUBKEY}
            )
        assert resp.status_code == 404


# ── Input validation ──────────────────────────────────────────────────────────

class TestVerifyValidation:

    def test_missing_bob_name(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        with patch("app.services.session_store.redis") as mock_redis, \
             patch("app.services.embedding_client.EmbeddingClient.embed", return_value=BOB_PASS_VEC):
            mock_redis.from_url.return_value = fake_redis
            resp = client.post(
                f"/api/session/{session_id}/verify",
                json={"bob_name": "", "answer": "test", "bob_pubkey_jwk": BOB_PUBKEY}
            )
        assert resp.status_code == 400

    def test_missing_answer(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        with patch("app.services.session_store.redis") as mock_redis, \
             patch("app.services.embedding_client.EmbeddingClient.embed", return_value=BOB_PASS_VEC):
            mock_redis.from_url.return_value = fake_redis
            resp = client.post(
                f"/api/session/{session_id}/verify",
                json={"bob_name": "Bob", "answer": "", "bob_pubkey_jwk": BOB_PUBKEY}
            )
        assert resp.status_code == 400

    def test_answer_too_long(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        with patch("app.services.session_store.redis") as mock_redis, \
             patch("app.services.embedding_client.EmbeddingClient.embed", return_value=BOB_PASS_VEC):
            mock_redis.from_url.return_value = fake_redis
            resp = client.post(
                f"/api/session/{session_id}/verify",
                json={"bob_name": "Bob", "answer": "x" * 501, "bob_pubkey_jwk": BOB_PUBKEY}
            )
        assert resp.status_code == 400

    def test_invalid_pubkey(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        with patch("app.services.session_store.redis") as mock_redis, \
             patch("app.services.embedding_client.EmbeddingClient.embed", return_value=BOB_PASS_VEC):
            mock_redis.from_url.return_value = fake_redis
            resp = client.post(
                f"/api/session/{session_id}/verify",
                json={"bob_name": "Bob", "answer": "test",
                      "bob_pubkey_jwk": {"kty": "RSA"}}
            )
        assert resp.status_code == 400

    def test_embedding_service_unavailable_returns_503(self, client, fake_redis):
        session_id = create_session(client, fake_redis)
        with patch("app.services.session_store.redis") as mock_redis, \
             patch("app.services.embedding_client.EmbeddingClient.embed", return_value=None):
            mock_redis.from_url.return_value = fake_redis
            resp = client.post(
                f"/api/session/{session_id}/verify",
                json={"bob_name": "Bob", "answer": "test", "bob_pubkey_jwk": BOB_PUBKEY}
            )
        assert resp.status_code == 503
"""
test_verify.py — Tests for POST /api/session/<id>/verify (Bob verifies)

Security guarantees tested:
  - alice_pubkey_jwk ONLY returned on PASS — never on FAIL
  - Sessions can only be verified once (one-time use guarantee)
  - Phase transitions correctly
"""

import json
import pytest
from unittest.mock import patch
from tests.conftest import ALICE_VEC, BOB_PASS_VEC, BOB_FAIL_VEC


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

BOB_PUBKEY = {
    "kty": "EC",
    "crv": "P-256",
    "x": "abc123def456abc123def456abc123def456abc123de",
    "y": "def456abc123def456abc123def456abc123def456ab"
}


def create_session(client):
    with patch("app.services.embedding_client.EmbeddingClient.embed",
               return_value=ALICE_VEC):
        resp = client.post("/api/session", json=VALID_PAYLOAD)
    return resp.get_json()["session_id"]


def do_verify(client, session_id, answer_vec=BOB_PASS_VEC, answer="chicken burrito bowl"):
    with patch("app.services.embedding_client.EmbeddingClient.embed",
               return_value=answer_vec):
        return client.post(
            f"/api/session/{session_id}/verify",
            json={"bob_name": "Bob", "answer": answer, "bob_pubkey_jwk": BOB_PUBKEY}
        )


# ── PASS ──────────────────────────────────────────────────────────────────────

class TestVerifyPass:

    def test_pass_returns_200(self, client):
        sid = create_session(client)
        assert do_verify(client, sid).status_code == 200

    def test_pass_result_is_pass(self, client):
        sid = create_session(client)
        assert do_verify(client, sid).get_json()["result"] == "PASS"

    def test_pass_returns_alice_pubkey(self, client):
        """SECURITY: alice_pubkey_jwk must be present on PASS."""
        sid = create_session(client)
        data = do_verify(client, sid).get_json()
        assert "alice_pubkey_jwk" in data
        assert data["alice_pubkey_jwk"]["kty"] == "EC"
        assert data["alice_pubkey_jwk"]["crv"] == "P-256"

    def test_pass_returns_score(self, client):
        sid = create_session(client)
        data = do_verify(client, sid).get_json()
        assert "score" in data
        assert data["score"] >= 75

    def test_pass_updates_phase_to_verified(self, client, fake_redis):
        sid = create_session(client)
        do_verify(client, sid)
        assert fake_redis.hgetall(f"session:{sid}")["phase"] == "VERIFIED"

    def test_pass_stores_bob_name(self, client, fake_redis):
        sid = create_session(client)
        do_verify(client, sid)
        assert fake_redis.hgetall(f"session:{sid}")["bob_name"] == "Bob"

    def test_pass_stores_similarity_score(self, client, fake_redis):
        sid = create_session(client)
        do_verify(client, sid)
        stored = fake_redis.hgetall(f"session:{sid}")
        assert stored["similarity_score"] != ""
        assert float(stored["similarity_score"]) >= 0.75


# ── FAIL ──────────────────────────────────────────────────────────────────────

class TestVerifyFail:

    def test_fail_returns_200(self, client):
        sid = create_session(client)
        resp = do_verify(client, sid, BOB_FAIL_VEC, "I have no idea")
        assert resp.status_code == 200

    def test_fail_result_is_fail(self, client):
        sid = create_session(client)
        data = do_verify(client, sid, BOB_FAIL_VEC, "I have no idea").get_json()
        assert data["result"] == "FAIL"

    def test_fail_does_not_return_alice_pubkey(self, client):
        """SECURITY: alice_pubkey_jwk must be ABSENT on FAIL."""
        sid = create_session(client)
        resp = do_verify(client, sid, BOB_FAIL_VEC, "I have no idea")
        data = resp.get_json()
        assert "alice_pubkey_jwk" not in data
        assert "alice_pubkey_jwk" not in resp.get_data(as_text=True)

    def test_fail_score_is_low(self, client):
        sid = create_session(client)
        data = do_verify(client, sid, BOB_FAIL_VEC, "I have no idea").get_json()
        assert data["score"] < 75

    def test_fail_updates_phase_to_failed(self, client, fake_redis):
        sid = create_session(client)
        do_verify(client, sid, BOB_FAIL_VEC, "wrong answer")
        assert fake_redis.hgetall(f"session:{sid}")["phase"] == "FAILED"

    def test_fail_does_not_store_bob_pubkey(self, client, fake_redis):
        sid = create_session(client)
        do_verify(client, sid, BOB_FAIL_VEC, "wrong answer")
        assert fake_redis.hgetall(f"session:{sid}")["bob_pubkey_jwk"] == ""


# ── One-time use guarantee ────────────────────────────────────────────────────

class TestOneTimeUse:

    def test_cannot_verify_twice_after_pass(self, client):
        """SECURITY: Attacker cannot re-verify after PASS."""
        sid = create_session(client)
        do_verify(client, sid)
        assert do_verify(client, sid).status_code == 409

    def test_cannot_verify_twice_after_fail(self, client):
        """SECURITY: Attacker cannot keep guessing after FAIL."""
        sid = create_session(client)
        do_verify(client, sid, BOB_FAIL_VEC, "wrong")
        assert do_verify(client, sid, BOB_PASS_VEC, "correct").status_code == 409

    def test_nonexistent_session_returns_404(self, client):
        with patch("app.services.embedding_client.EmbeddingClient.embed",
                   return_value=BOB_PASS_VEC):
            resp = client.post(
                "/api/session/doesnotexist/verify",
                json={"bob_name": "Bob", "answer": "test", "bob_pubkey_jwk": BOB_PUBKEY}
            )
        assert resp.status_code == 404


# ── Input validation ──────────────────────────────────────────────────────────

class TestVerifyValidation:

    def test_missing_bob_name(self, client):
        sid = create_session(client)
        with patch("app.services.embedding_client.EmbeddingClient.embed",
                   return_value=BOB_PASS_VEC):
            resp = client.post(f"/api/session/{sid}/verify",
                               json={"bob_name": "", "answer": "test",
                                     "bob_pubkey_jwk": BOB_PUBKEY})
        assert resp.status_code == 400

    def test_missing_answer(self, client):
        sid = create_session(client)
        with patch("app.services.embedding_client.EmbeddingClient.embed",
                   return_value=BOB_PASS_VEC):
            resp = client.post(f"/api/session/{sid}/verify",
                               json={"bob_name": "Bob", "answer": "",
                                     "bob_pubkey_jwk": BOB_PUBKEY})
        assert resp.status_code == 400

    def test_answer_too_long(self, client):
        sid = create_session(client)
        with patch("app.services.embedding_client.EmbeddingClient.embed",
                   return_value=BOB_PASS_VEC):
            resp = client.post(f"/api/session/{sid}/verify",
                               json={"bob_name": "Bob", "answer": "x" * 501,
                                     "bob_pubkey_jwk": BOB_PUBKEY})
        assert resp.status_code == 400

    def test_invalid_pubkey(self, client):
        sid = create_session(client)
        with patch("app.services.embedding_client.EmbeddingClient.embed",
                   return_value=BOB_PASS_VEC):
            resp = client.post(f"/api/session/{sid}/verify",
                               json={"bob_name": "Bob", "answer": "test",
                                     "bob_pubkey_jwk": {"kty": "RSA"}})
        assert resp.status_code == 400

    def test_embedding_unavailable_returns_503(self, client):
        sid = create_session(client)
        with patch("app.services.embedding_client.EmbeddingClient.embed",
                   return_value=None):
            resp = client.post(f"/api/session/{sid}/verify",
                               json={"bob_name": "Bob", "answer": "test",
                                     "bob_pubkey_jwk": BOB_PUBKEY})
        assert resp.status_code == 503
"""
Verify route — Bob's side of the Doppelganger Protocol.

This is the protocol moment:
  - Bob submits his answer to Alice's memory question + his ECDH public key
  - Server scores Bob's answer against Alice's stored embedding
  - If score >= threshold: keys are exchanged, channel opens, both parties notified
  - If score < threshold: no key exchange, channel stays closed, session ends

Alice's public key is only revealed to Bob AFTER he passes.
This is the trust bootstrap — the shared memory IS the certificate.
"""

import json
from flask import Blueprint, jsonify, request, current_app
from app import limiter
from app.services.session_store import SessionStore
from app.services.embedding_client import EmbeddingClient
from app.utils.validators import validate_verify

verify_bp = Blueprint("verify", __name__)


@verify_bp.route("/session/<session_id>/verify", methods=["POST"])
@limiter.limit("5 per minute")
def verify(session_id):
    """
    Bob submits his answer and public key.

    Request body:
    {
        "bob_name": "Bob",
        "answer": "chicken burrito bowl extra guac",
        "bob_pubkey_jwk": { ...JWK... }
    }

    On PASS response:
    {
        "result": "PASS",
        "score": 0.94,
        "alice_pubkey_jwk": { ...JWK... }   <-- only revealed on pass
    }

    On FAIL response:
    {
        "result": "FAIL",
        "score": 0.21
        // alice_pubkey_jwk intentionally absent
    }
    """
    data = request.get_json(silent=True)
    error = validate_verify(data)
    if error:
        return jsonify({"error": error}), 400

    store = SessionStore()
    session = store.get(session_id)
    if not session:
        return jsonify({"error": "Session not found or expired"}), 404

    if session["phase"] != "WAITING_FOR_BOB":
        return jsonify({"error": "Session already completed"}), 409

    # Score Bob's answer against Alice's stored embedding
    bob_embedding = EmbeddingClient.embed(data["answer"])
    if bob_embedding is None:
        return jsonify({"error": "Embedding service unavailable"}), 503

    score = EmbeddingClient.cosine_similarity(
        json.loads(session["answer_embedding"]),
        bob_embedding
    )

    threshold = current_app.config["SIMILARITY_THRESHOLD"]
    passed = score >= threshold

    if passed:
        # Trust established — exchange keys, open channel
        store.update(session_id, {
            "phase": "VERIFIED",
            "bob_name": data["bob_name"],
            "bob_pubkey_jwk": json.dumps(data["bob_pubkey_jwk"]),
            "similarity_score": str(round(score, 4))
        })
        # Notify Alice via SSE that Bob passed and provide Bob's pubkey
        store.publish(session_id, {
            "event": "VERIFIED",
            "bob_name": data["bob_name"],
            "bob_pubkey_jwk": data["bob_pubkey_jwk"],
            "score": round(score * 100)
        })
        return jsonify({
            "result": "PASS",
            "score": round(score * 100),
            "alice_pubkey_jwk": json.loads(session["alice_pubkey_jwk"])
            # Alice's pubkey only released here — after Bob proves himself
        }), 200

    else:
        # Trust not established — channel stays closed
        store.update(session_id, {
            "phase": "FAILED",
            "similarity_score": str(round(score, 4))
        })
        store.publish(session_id, {
            "event": "FAILED",
            "score": round(score * 100)
        })
        return jsonify({
            "result": "FAIL",
            "score": round(score * 100)
            # alice_pubkey_jwk intentionally absent
        }), 200
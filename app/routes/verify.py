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
@limiter.limit(lambda: current_app.config["VERIFY_RATE_LIMIT"])
def verify(session_id):
    data = request.get_json(silent=True)
    error = validate_verify(data)
    if error:
        return jsonify({"error": error}), 400

    store = SessionStore()
    session = store.get(session_id)
    if not session:
        return jsonify({"error": "Session not found or expired"}), 404

    # Cheap early rejection; the atomic check happens in finalize() below.
    if session["phase"] != "WAITING_FOR_BOB":
        return jsonify({"error": "Session already completed"}), 409

    bob_embedding = EmbeddingClient.embed(data["answer"])
    if bob_embedding is None:
        # Session is untouched, so Bob can simply retry.
        return jsonify({"error": "Embedding service busy — please try again"}), 503

    score = EmbeddingClient.cosine_similarity(
        json.loads(session["answer_embedding"]),
        bob_embedding
    )
    passed = score >= current_app.config["SIMILARITY_THRESHOLD"]
    pct = round(score * 100)

    if passed:
        updates = {
            "phase": "VERIFIED",
            "bob_name": data["bob_name"],
            "bob_pubkey_jwk": json.dumps(data["bob_pubkey_jwk"]),
            "similarity_score": str(round(score, 4)),
        }
        event = {
            "event": "VERIFIED",
            "bob_name": data["bob_name"],
            "bob_pubkey_jwk": data["bob_pubkey_jwk"],
            "score": pct,
        }
    else:
        updates = {"phase": "FAILED", "similarity_score": str(round(score, 4))}
        event = {"event": "FAILED", "score": pct}

    outcome = store.finalize(session_id, updates, event)
    if outcome == -1:
        return jsonify({"error": "Session expired while scoring"}), 404
    if outcome == 0:
        return jsonify({"error": "Session already completed"}), 409

    if passed:
        return jsonify({
            "result": "PASS",
            "score": pct,
            "alice_pubkey_jwk": json.loads(session["alice_pubkey_jwk"])
            # Alice's pubkey only released here — after Bob proves himself
        }), 200

    return jsonify({"result": "FAIL", "score": pct}), 200
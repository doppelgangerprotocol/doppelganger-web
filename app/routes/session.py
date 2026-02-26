"""
Session route — Alice's side of the Doppelganger Protocol.

Alice creates a session by providing:
  - Her name
  - A memory question (shown to Bob in plaintext)
  - Her answer to that question (used to generate an embedding for scoring)
  - Her ECDH public key (bundled into the one-time link)

The server:
  - Calls the embedding microservice to vectorize Alice's answer
  - Stores the embedding (NOT the raw answer) in Redis with a TTL
  - Returns a one-time link + QR code that contains the session ID

Alice's public key is stored server-side and returned to Alice only AFTER
Bob passes the memory challenge. It is never exposed to an unverified Bob.
"""

from flask import Blueprint, jsonify, request, current_app
from app import limiter
from app.services.session_store import SessionStore
from app.services.embedding_client import EmbeddingClient
from app.services.qr import generate_qr
from app.utils.session_id import generate_session_id
from app.utils.validators import validate_session_create

session_bp = Blueprint("session", __name__)


@session_bp.route("/session", methods=["POST"])
@limiter.limit("10 per hour")
def create_session():
    """
    Alice creates a new verification session.

    Request body:
    {
        "alice_name": "Alice",
        "memory_question": "What did we order at Chipotle?",
        "memory_answer": "Chicken burrito bowl with extra guac",
        "alice_pubkey_jwk": { ...JWK... }
    }

    Response:
    {
        "session_id": "abc123",
        "link": "https://doppelgangerprotocol.app/verify/s/abc123",
        "qr_code": "data:image/png;base64,..."
    }
    """
    data = request.get_json(silent=True)
    error = validate_session_create(data)
    if error:
        return jsonify({"error": error}), 400

    # Generate embedding from Alice's answer — raw answer never stored
    embedding = EmbeddingClient.embed(data["memory_answer"])
    if embedding is None:
        return jsonify({"error": "Embedding service unavailable"}), 503

    session_id = generate_session_id()
    ttl = current_app.config["SESSION_TTL_SECONDS"]
    base_url = current_app.config.get("BASE_URL", "https://doppelgangerprotocol.app")

    store = SessionStore()
    store.create(
        session_id=session_id,
        alice_name=data["alice_name"],
        memory_question=data["memory_question"],
        answer_embedding=embedding,
        alice_pubkey_jwk=data["alice_pubkey_jwk"],
        ttl=ttl
    )

    link = f"{base_url}/verify/s/{session_id}"
    qr_code = generate_qr(link)

    return jsonify({
        "session_id": session_id,
        "link": link,
        "qr_code": qr_code
    }), 201


@session_bp.route("/session/<session_id>", methods=["GET"])
def get_session(session_id):
    """
    Bob opens the one-time link — returns only what Bob is allowed to see.

    Returns the memory question (plaintext) and the session phase.
    Alice's public key is NOT returned here — only after Bob passes verification.
    """
    store = SessionStore()
    session = store.get(session_id)
    if not session:
        return jsonify({"error": "Session not found or expired"}), 404

    return jsonify({
        "alice_name": session["alice_name"],
        "memory_question": session["memory_question"],
        "phase": session["phase"]
    }), 200


@session_bp.route("/session/<session_id>", methods=["DELETE"])
def delete_session(session_id):
    """Manual teardown — sessions also auto-expire via Redis TTL."""
    store = SessionStore()
    store.delete(session_id)
    return jsonify({"deleted": True}), 200
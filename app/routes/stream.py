"""
SSE stream — real-time updates for both Alice and Bob.

Alice connects to this stream after creating her session.
She stays connected waiting for Bob to verify.

Events pushed:
  - VERIFIED: Bob passed — includes Bob's pubkey so Alice can complete key exchange
  - FAILED:   Bob failed — channel stays closed
"""

import json
from flask import Blueprint, Response, stream_with_context, current_app
from app.services.session_store import SessionStore

stream_bp = Blueprint("stream", __name__)


@stream_bp.route("/session/<session_id>/stream", methods=["GET"])
def event_stream(session_id):
    """
    Server-Sent Events stream for a session.
    Alice connects here after creating her session.
    Receives VERIFIED or FAILED when Bob submits his answer.
    """
    store = SessionStore()
    session = store.get(session_id)
    if not session:
        return Response("Session not found", status=404)

    def generate():
        # Send current state immediately on connect
        yield f"data: {json.dumps({'event': 'CONNECTED', 'phase': session['phase']})}\n\n"

        # Subscribe to Redis pub/sub for this session
        pubsub = store.subscribe(session_id)
        try:
            for message in pubsub.listen():
                if message["type"] == "message":
                    yield f"data: {message['data']}\n\n"
                    # Stop streaming once terminal state reached
                    event = json.loads(message["data"]).get("event")
                    if event in ("VERIFIED", "FAILED"):
                        break
        finally:
            pubsub.unsubscribe()

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Disable nginx buffering
            "Connection": "keep-alive"
        }
    )
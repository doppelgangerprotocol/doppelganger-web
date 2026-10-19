"""
SSE stream — real-time updates for Alice while she waits for Bob.

Events pushed:
  - CONNECTED: on open
  - VERIFIED:  Bob passed — includes Bob's pubkey so Alice can complete key exchange
  - FAILED:    Bob failed — channel stays closed
  - EXPIRED:   session TTL ran out before anyone answered

Hardening:
  - No Redis connection per stream (EventHub fans out one per worker)
  - Heartbeat every 15s: keeps proxies from cutting idle streams and lets the
    server notice closed tabs (the write fails -> generator exits -> cleanup)
  - Safety-net state check on every heartbeat, so a missed pub/sub message
    (e.g. during a Redis reconnect) costs at most 15s, never a hung demo
  - Ends itself when the session expires
"""

import json
import queue
import time

from flask import Blueprint, Response, stream_with_context

from app import limiter
from app.services.event_hub import hub
from app.services.session_store import SessionStore

stream_bp = Blueprint("stream", __name__)

HEARTBEAT_SECONDS = 15
MAX_STREAM_SECONDS = 15 * 60          # hard cap, belt and braces
TERMINAL_EVENTS = ("VERIFIED", "FAILED", "EXPIRED")


def _sse(payload) -> str:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return f"data: {data}\n\n"


@stream_bp.route("/session/<session_id>/stream", methods=["GET"])
@limiter.exempt   # browser auto-reconnects must never be rate limited into a broken demo
def event_stream(session_id):
    store = SessionStore()
    phase = store.get_phase(session_id)
    if phase is None:
        return Response("Session not found", status=404)

    def generate():
        q = hub.subscribe(session_id)
        try:
            yield "retry: 5000\n\n"   # browser waits 5s before auto-reconnecting
            yield _sse({"event": "CONNECTED", "phase": phase})

            # Bob may have finished before this stream opened (or this is a reconnect).
            # Checking AFTER subscribing means no event can slip through the gap.
            final = store.terminal_event(session_id)
            if final:
                yield _sse(final)
                return

            deadline = time.monotonic() + MAX_STREAM_SECONDS
            while time.monotonic() < deadline:
                try:
                    data = q.get(timeout=HEARTBEAT_SECONDS)
                except queue.Empty:
                    final = store.terminal_event(session_id)
                    if final:
                        yield _sse(final)
                        return
                    yield ": keepalive\n\n"
                    continue

                yield _sse(data)
                if json.loads(data).get("event") in TERMINAL_EVENTS:
                    return

            yield _sse({"event": "EXPIRED"})
        finally:
            hub.unsubscribe(session_id, q)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )
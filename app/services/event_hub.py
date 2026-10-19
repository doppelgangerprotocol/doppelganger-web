"""
EventHub: ONE Redis pub/sub connection per worker process, fanned out to every
SSE stream in that process through in-memory queues.

Before: each waiting Alice held her own pub/sub connection, forever if Bob
never showed up. Now 200 waiting Alices cost 1 connection per worker.

Uses stdlib threading/queue on purpose: under gunicorn's gevent worker these are
monkey-patched into greenlets; under `flask run` locally they're real threads.
"""
import logging
import os
import queue
import threading
import time

import redis

log = logging.getLogger(__name__)

_PATTERN = "session:*:events"
_PREFIX, _SUFFIX = "session:", ":events"


class EventHub:
    def __init__(self):
        self._queues: dict[str, set] = {}
        self._pid = None
        self._lock = threading.Lock()

    def subscribe(self, session_id: str) -> queue.Queue:
        self._ensure_listener()
        q = queue.Queue(maxsize=10)
        self._queues.setdefault(session_id, set()).add(q)
        return q

    def unsubscribe(self, session_id: str, q: queue.Queue) -> None:
        qs = self._queues.get(session_id)
        if qs is not None:
            qs.discard(q)
            if not qs:
                self._queues.pop(session_id, None)

    def _ensure_listener(self) -> None:
        if self._pid == os.getpid():
            return
        with self._lock:
            if self._pid == os.getpid():
                return
            self._queues = {}
            threading.Thread(target=self._listen_forever, daemon=True).start()
            self._pid = os.getpid()

    def _listen_forever(self) -> None:
        while True:
            client = pubsub = None
            try:
                # Dedicated connection (not from the shared pool): it's held permanently,
                # and it must NOT have a socket_timeout or idle periods would raise.
                client = redis.Redis.from_url(
                    os.environ.get("REDIS_URL", "redis://localhost:6379"),
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                    health_check_interval=30,
                )
                pubsub = client.pubsub(ignore_subscribe_messages=True)
                pubsub.psubscribe(_PATTERN)
                log.info("EventHub listening (pid %s)", os.getpid())

                while True:
                    msg = pubsub.get_message(timeout=5.0)
                    if not msg or msg["type"] != "pmessage":
                        continue
                    session_id = msg["channel"][len(_PREFIX):-len(_SUFFIX)]
                    for q in list(self._queues.get(session_id, ())):
                        try:
                            q.put_nowait(msg["data"])
                        except queue.Full:
                            pass
            except Exception:
                log.exception("EventHub lost Redis connection; reconnecting in 2s")
                time.sleep(2)
            finally:
                for closable in (pubsub, client):
                    try:
                        if closable is not None:
                            closable.close()
                    except Exception:
                        pass


hub = EventHub()
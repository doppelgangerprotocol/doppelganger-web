"""
Redis-backed session store.

Each session is stored as a Redis Hash with a TTL.
Key structure: session:{session_id}
Pub/Sub channel: session:{session_id}:events

Session schema:
{
    "phase":              "WAITING_FOR_BOB" | "VERIFIED" | "FAILED"
    "alice_name":         str
    "memory_question":    str          # shown to Bob in plaintext
    "answer_embedding":   JSON str     # vector — NOT the raw answer
    "alice_pubkey_jwk":   JSON str     # only returned to Bob after PASS
    "bob_name":           str          # set after verification
    "bob_pubkey_jwk":     JSON str     # set after PASS
    "similarity_score":   str          # set after verification
    "created_at":         str
}
"""

import json
import time
import redis
import os
from typing import Optional


class SessionStore:

    def __init__(self):
        self.r = redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379"),
            decode_responses=True
        )

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}"

    def _channel(self, session_id: str) -> str:
        return f"session:{session_id}:events"

    def create(
        self,
        session_id: str,
        alice_name: str,
        memory_question: str,
        answer_embedding: list,
        alice_pubkey_jwk: dict,
        ttl: int = 1800
    ) -> dict:
        key = self._key(session_id)
        data = {
            "phase": "WAITING_FOR_BOB",
            "alice_name": alice_name,
            "memory_question": memory_question,
            "answer_embedding": json.dumps(answer_embedding),
            "alice_pubkey_jwk": json.dumps(alice_pubkey_jwk),
            "bob_name": "",
            "bob_pubkey_jwk": "",
            "similarity_score": "",
            "created_at": str(int(time.time()))
        }
        pipe = self.r.pipeline()
        pipe.hset(key, mapping=data)
        pipe.expire(key, ttl)
        pipe.execute()
        return data

    def get(self, session_id: str) -> Optional[dict]:
        data = self.r.hgetall(self._key(session_id))
        return data if data else None

    def update(self, session_id: str, updates: dict) -> bool:
        key = self._key(session_id)
        if not self.r.exists(key):
            return False
        # Preserve remaining TTL
        ttl = self.r.ttl(key)
        pipe = self.r.pipeline()
        pipe.hset(key, mapping=updates)
        if ttl > 0:
            pipe.expire(key, ttl)
        pipe.execute()
        return True

    def delete(self, session_id: str) -> bool:
        return bool(self.r.delete(self._key(session_id)))

    def publish(self, session_id: str, event: dict) -> None:
        self.r.publish(self._channel(session_id), json.dumps(event))

    def subscribe(self, session_id: str):
        pubsub = self.r.pubsub()
        pubsub.subscribe(self._channel(session_id))
        return pubsub
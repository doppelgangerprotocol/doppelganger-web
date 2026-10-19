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
from typing import Optional

from app.services.redis_client import get_redis

# Atomically move a session out of WAITING_FOR_BOB and announce the result.
# Returns -1 if the session expired, 0 if it was already completed, 1 on success.
# KEYS[1] = session key
# ARGV[1] = pub/sub channel, ARGV[2] = event JSON, ARGV[3..] = field/value pairs
_FINALIZE_LUA = """
if redis.call('EXISTS', KEYS[1]) == 0 then
    return -1
end
if redis.call('HGET', KEYS[1], 'phase') ~= 'WAITING_FOR_BOB' then
    return 0
end
redis.call('HSET', KEYS[1], unpack(ARGV, 3))
redis.call('PUBLISH', ARGV[1], ARGV[2])
return 1
"""


class SessionStore:

    def __init__(self):
        # Shared, capped pool. Constructing a SessionStore no longer opens connections.
        self.r = get_redis()
        self._finalize = self.r.register_script(_FINALIZE_LUA)

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
        ttl: int = 300
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
        pipe = self.r.pipeline(transaction=True)
        pipe.hset(key, mapping=data)
        pipe.expire(key, ttl)
        pipe.execute()
        return data

    def get(self, session_id: str) -> Optional[dict]:
        data = self.r.hgetall(self._key(session_id))
        return data if data else None

    def get_phase(self, session_id: str) -> Optional[str]:
        """Cheap existence/phase check — avoids pulling the 384-float embedding."""
        return self.r.hget(self._key(session_id), "phase")

    def finalize(self, session_id: str, updates: dict, event: dict) -> int:
        """
        Atomic WAITING_FOR_BOB -> VERIFIED/FAILED transition + publish.
        Only one Bob can ever win, even if two submit at the same instant.
        """
        args = [self._channel(session_id), json.dumps(event)]
        for field, value in updates.items():
            args += [field, value]
        return int(self._finalize(keys=[self._key(session_id)], args=args))

    def terminal_event(self, session_id: str) -> Optional[dict]:
        """
        Rebuild the final SSE event from the stored hash.
        Returns None while still WAITING_FOR_BOB, {"event": "EXPIRED"} if gone.
        """
        phase, bob_name, bob_pubkey_jwk, score = self.r.hmget(
            self._key(session_id),
            "phase", "bob_name", "bob_pubkey_jwk", "similarity_score"
        )
        if phase is None:
            return {"event": "EXPIRED"}
        if phase == "VERIFIED":
            return {
                "event": "VERIFIED",
                "bob_name": bob_name,
                "bob_pubkey_jwk": json.loads(bob_pubkey_jwk),
                "score": round(float(score) * 100),
            }
        if phase == "FAILED":
            return {"event": "FAILED", "score": round(float(score) * 100)}
        return None

    def delete(self, session_id: str) -> bool:
        return bool(self.r.delete(self._key(session_id)))
"""
conftest.py — shared fixtures for all tests.

Strategy:
  - Use a TestConfig with in-memory/test settings
  - Mock Redis at the SessionStore level
  - Mock EmbeddingClient at the method level
  - Disable rate limiting in tests
"""

import json
import pytest
from unittest.mock import patch, MagicMock


# ── Fake Redis ────────────────────────────────────────────────────────────────

class FakeRedis:
    """In-memory Redis substitute. No TTL enforcement."""

    def __init__(self):
        self._store = {}
        self._published = []

    def hset(self, key, mapping=None, **kwargs):
        if key not in self._store:
            self._store[key] = {}
        if mapping:
            self._store[key].update(mapping)

    def hgetall(self, key):
        return dict(self._store.get(key, {}))

    def expire(self, key, ttl):
        pass

    def ttl(self, key):
        return 300

    def exists(self, key):
        return 1 if key in self._store else 0

    def delete(self, key):
        removed = 1 if key in self._store else 0
        self._store.pop(key, None)
        return removed

    def publish(self, channel, message):
        self._published.append({"channel": channel, "message": message})

    def pipeline(self):
        return FakePipeline(self)

    def pubsub(self):
        return FakePubSub()


class FakePipeline:
    def __init__(self, redis):
        self._redis = redis
        self._commands = []

    def hset(self, key, mapping=None):
        self._commands.append(("hset", key, mapping))
        return self

    def expire(self, key, ttl):
        self._commands.append(("expire", key, ttl))
        return self

    def execute(self):
        for cmd in self._commands:
            if cmd[0] == "hset":
                self._redis.hset(cmd[1], mapping=cmd[2])
        return [True] * len(self._commands)


class FakePubSub:
    def subscribe(self, channel):
        pass

    def unsubscribe(self):
        pass

    def listen(self):
        return iter([])


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def app(fake_redis):
    """
    Flask test app with:
      - FakeRedis injected into SessionStore
      - Rate limiting disabled
    """
    # Patch redis.from_url before the app imports SessionStore
    with patch("redis.from_url", return_value=fake_redis):
        from app import create_app, limiter
        flask_app = create_app()

    flask_app.config["TESTING"] = True
    flask_app.config["BASE_URL"] = "http://localhost:5001"
    flask_app.config["SIMILARITY_THRESHOLD"] = 0.75
    flask_app.config["SESSION_TTL_SECONDS"] = 300

    # Disable rate limiting
    limiter.enabled = False

    yield flask_app

    limiter.enabled = True


@pytest.fixture
def client(app):
    return app.test_client()


# ── Shared test data ──────────────────────────────────────────────────────────

@pytest.fixture
def valid_alice_pubkey():
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": "f83OJ3D2xF1Bg8vub9tLe1gHMzV76e8Tus9uPHvRVEU",
        "y": "x_FEzRu9m36HLN_tue659LNpXW6pCyStikYjKIWI5a0"
    }


@pytest.fixture
def valid_bob_pubkey():
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": "abc123def456abc123def456abc123def456abc123de",
        "y": "def456abc123def456abc123def456abc123def456ab"
    }


@pytest.fixture
def session_payload(valid_alice_pubkey):
    return {
        "alice_name": "Alice",
        "memory_question": "What did we order at Chipotle?",
        "memory_answer": "Chicken burrito bowl with extra guac",
        "alice_pubkey_jwk": valid_alice_pubkey
    }


# Vectors
ALICE_VEC = [0.1] * 384
BOB_PASS_VEC = [0.1] * 383 + [0.101]   # high similarity — PASS
BOB_FAIL_VEC = [0.0] * 383 + [1.0]     # orthogonal — FAIL
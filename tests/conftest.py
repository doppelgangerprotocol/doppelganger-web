"""
conftest.py — shared fixtures for all tests.

Uses an in-memory fake Redis so tests never touch your real Redis instance.
Mocks the embedding service so tests never make real HTTP calls.
Rate limiting is disabled in tests.
"""

import json
import pytest
from unittest.mock import patch, MagicMock


# ── Fake Redis ────────────────────────────────────────────────────────────────

class FakeRedis:
    """
    In-memory Redis substitute for testing.
    Supports hset, hgetall, expire, exists, ttl, delete, publish, pipeline.
    No TTL enforcement — just stores data.
    """

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
        pass  # TTL not enforced in tests

    def ttl(self, key):
        return 1800

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
            elif cmd[0] == "expire":
                self._redis.expire(cmd[1], cmd[2])
        return [True] * len(self._commands)


class FakePubSub:
    def subscribe(self, channel):
        pass

    def unsubscribe(self):
        pass

    def listen(self):
        return iter([])


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def app(fake_redis):
    """
    Create a test Flask app with:
    - FakeRedis instead of real Redis
    - Embedding service mocked
    - Rate limiting disabled
    """
    # Patch Redis before app is created
    with patch("app.services.session_store.redis") as mock_redis_module, \
         patch("app") as _:

        mock_redis_module.from_url.return_value = fake_redis

        from app import create_app, limiter
        flask_app = create_app()
        flask_app.config["TESTING"] = True
        flask_app.config["FLASK_ENV"] = "development"
        flask_app.config["BASE_URL"] = "http://localhost:5001"
        flask_app.config["SIMILARITY_THRESHOLD"] = 0.75
        flask_app.config["SESSION_TTL_SECONDS"] = 1800

        # Disable rate limiting in tests
        limiter.enabled = False

        yield flask_app

        # Re-enable after test
        limiter.enabled = True


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def valid_pubkey_jwk():
    """A valid EC P-256 JWK for testing."""
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": "f83OJ3D2xF1Bg8vub9tLe1gHMzV76e8Tus9uPHvRVEU",
        "y": "x_FEzRu9m36HLN_tue659LNpXW6pCyStikYjKIWI5a0"
    }


@pytest.fixture
def mock_embed_pass():
    """
    Mock EmbeddingClient.embed to return consistent test vectors.
    Alice and Bob's answers will score ~0.97 (PASS).
    """
    # Two nearly identical unit vectors — high cosine similarity
    alice_vec = [0.1] * 384
    bob_vec   = [0.1] * 383 + [0.101]

    def fake_embed(text):
        # Bob's answer returns a slightly different vector
        if "no idea" in text.lower() or "wrong" in text.lower():
            return [0.0] * 383 + [1.0]   # orthogonal — low similarity
        return alice_vec

    return fake_embed, alice_vec, bob_vec


@pytest.fixture
def session_payload(valid_pubkey_jwk):
    """Standard Alice session creation payload."""
    return {
        "alice_name": "Alice",
        "memory_question": "What did we order at Chipotle?",
        "memory_answer": "Chicken burrito bowl with extra guac",
        "alice_pubkey_jwk": valid_pubkey_jwk
    }


@pytest.fixture
def created_session(client, session_payload, fake_redis):
    """
    Creates a session and returns the response data + fake_redis.
    Use this as a starting point for verify tests.
    """
    alice_vec = [0.1] * 384

    with patch("app.services.session_store.redis") as mock_redis_module, \
         patch("app.services.embedding_client.EmbeddingClient.embed", return_value=alice_vec):

        mock_redis_module.from_url.return_value = fake_redis

        resp = client.post(
            "/api/session",
            json=session_payload,
            content_type="application/json"
        )
        data = resp.get_json()
        return data, fake_redis
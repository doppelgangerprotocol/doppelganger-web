"""
test_embedding_client.py — Tests for EmbeddingClient

Tests the HTTP proxy + cosine similarity math.
Mocks requests so no real HTTP calls are made.
"""

import math
import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from app.services.embedding_client import EmbeddingClient


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_response(vector, success=True, status_code=200):
    """Build a mock requests.Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "success": success,
        "vector": vector,
        "dimension": len(vector)
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def unit_vector(size=384, value=0.1):
    """Return a normalized vector for testing."""
    v = np.array([value] * size, dtype=np.float32)
    return (v / np.linalg.norm(v)).tolist()


# ── embed() ───────────────────────────────────────────────────────────────────

class TestEmbed:

    def test_returns_vector_on_success(self):
        vec = unit_vector()
        with patch("app.services.embedding_client.requests.post",
                   return_value=make_response(vec)):
            result = EmbeddingClient.embed("chicken burrito bowl")
        assert result == vec

    def test_returns_list(self):
        vec = unit_vector()
        with patch("app.services.embedding_client.requests.post",
                   return_value=make_response(vec)):
            result = EmbeddingClient.embed("test")
        assert isinstance(result, list)

    def test_returns_384_dimensions(self):
        vec = unit_vector(384)
        with patch("app.services.embedding_client.requests.post",
                   return_value=make_response(vec)):
            result = EmbeddingClient.embed("test")
        assert len(result) == 384

    def test_returns_none_on_timeout(self):
        import requests
        with patch("app.services.embedding_client.requests.post",
                   side_effect=requests.Timeout):
            result = EmbeddingClient.embed("test")
        assert result is None

    def test_returns_none_on_connection_error(self):
        import requests
        with patch("app.services.embedding_client.requests.post",
                   side_effect=requests.ConnectionError):
            result = EmbeddingClient.embed("test")
        assert result is None

    def test_returns_none_when_success_false(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": False, "error": "something failed"}
        mock_resp.raise_for_status = MagicMock()
        with patch("app.services.embedding_client.requests.post",
                   return_value=mock_resp):
            result = EmbeddingClient.embed("test")
        assert result is None

    def test_sends_correct_api_key_header(self):
        vec = unit_vector()
        with patch("app.services.embedding_client.requests.post",
                   return_value=make_response(vec)) as mock_post:
            with patch.object(EmbeddingClient, "API_KEY", "test-api-key"):
                EmbeddingClient.embed("test")
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["headers"]["X-API-Key"] == "test-api-key"

    def test_sends_correct_endpoint(self):
        vec = unit_vector()
        with patch("app.services.embedding_client.requests.post",
                   return_value=make_response(vec)) as mock_post:
            with patch.object(EmbeddingClient, "BASE_URL", "http://localhost:8000"):
                EmbeddingClient.embed("test")
        call_args = mock_post.call_args[0]
        assert call_args[0] == "http://localhost:8000/embed"


# ── cosine_similarity() ───────────────────────────────────────────────────────

class TestCosineSimilarity:

    def test_identical_vectors_score_1(self):
        vec = unit_vector()
        score = EmbeddingClient.cosine_similarity(vec, vec)
        assert abs(score - 1.0) < 1e-5

    def test_orthogonal_vectors_score_0(self):
        a = [1.0] + [0.0] * 383
        b = [0.0] + [1.0] + [0.0] * 382
        score = EmbeddingClient.cosine_similarity(a, b)
        assert abs(score) < 1e-5

    def test_similar_vectors_score_high(self):
        """Slight variation should score well above threshold."""
        a = unit_vector(value=0.1)
        b = unit_vector(value=0.101)  # nearly identical
        score = EmbeddingClient.cosine_similarity(a, b)
        assert score > 0.90

    def test_different_vectors_score_low(self):
        """Very different vectors should score well below threshold."""
        a = [1.0] + [0.0] * 383
        b = [0.0] * 383 + [1.0]
        score = EmbeddingClient.cosine_similarity(a, b)
        assert score < 0.10

    def test_returns_float(self):
        vec = unit_vector()
        score = EmbeddingClient.cosine_similarity(vec, vec)
        assert isinstance(score, float)

    def test_score_between_0_and_1(self):
        import random
        random.seed(42)
        a = [random.gauss(0, 1) for _ in range(384)]
        b = [random.gauss(0, 1) for _ in range(384)]
        score = EmbeddingClient.cosine_similarity(a, b)
        assert -1.0 <= score <= 1.0

    def test_zero_vector_returns_0(self):
        a = [0.0] * 384
        b = unit_vector()
        score = EmbeddingClient.cosine_similarity(a, b)
        assert score == 0.0

    def test_symmetry(self):
        """cosine(a, b) == cosine(b, a)"""
        a = unit_vector(value=0.1)
        b = unit_vector(value=0.2)
        assert abs(
            EmbeddingClient.cosine_similarity(a, b) -
            EmbeddingClient.cosine_similarity(b, a)
        ) < 1e-6


# ── health() ──────────────────────────────────────────────────────────────────

class TestHealth:

    def test_returns_true_when_service_up(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("app.services.embedding_client.requests.get",
                   return_value=mock_resp):
            assert EmbeddingClient.health() is True

    def test_returns_false_when_service_down(self):
        import requests
        with patch("app.services.embedding_client.requests.get",
                   side_effect=requests.ConnectionError):
            assert EmbeddingClient.health() is False

    def test_returns_false_on_non_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch("app.services.embedding_client.requests.get",
                   return_value=mock_resp):
            assert EmbeddingClient.health() is False
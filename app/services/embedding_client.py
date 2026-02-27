"""
Proxy to the Doppelganger Protocol embedding microservice.

Service: embedding_service_web.py (FastAPI + all-MiniLM-L6-v2)
Auth:    Shared API key via X-API-Key header
Endpoint: POST /embed
Response field: "vector"
Dimensions: 384
"""

import os
import logging
import numpy as np
import requests
from typing import Optional

logger = logging.getLogger(__name__)


class EmbeddingClient:

    BASE_URL = os.environ.get("EMBEDDING_SERVICE_URL", "http://localhost:8000")
    API_KEY  = os.environ.get("EMBEDDING_API_KEY", "")
    TIMEOUT  = 15

    @classmethod
    def _headers(cls) -> dict:
        return {
            "Content-Type": "application/json",
            "X-API-Key": cls.API_KEY
        }

    @classmethod
    def embed(cls, text: str) -> Optional[list]:
        """
        Get 384-dim embedding vector for a text string.
        Returns a plain Python list (JSON-serializable for Redis storage).
        Returns None on failure.
        """
        try:
            resp = requests.post(
                f"{cls.BASE_URL}/embed",
                json={"text": text},
                headers=cls._headers(),
                timeout=cls.TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()

            if not data.get("success"):
                logger.error(f"[embedding] success=false: {data}")
                return None

            return data["vector"]  # plain list — safe to JSON serialize into Redis

        except requests.Timeout:
            logger.error("[embedding] Request timed out")
            return None
        except Exception as e:
            logger.error(f"[embedding] embed() failed: {e}")
            return None

    @classmethod
    def cosine_similarity(cls, vec_a: list, vec_b: list) -> float:
        """
        Cosine similarity between two 384-dim vectors using numpy.
        Vectors are already L2-normalized by the embedding service
        so this is effectively a dot product — but computed fully for safety.
        Returns 0.0–1.0.
        """
        a = np.array(vec_a, dtype=np.float32)
        b = np.array(vec_b, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    @classmethod
    def health(cls) -> bool:
        try:
            resp = requests.get(f"{cls.BASE_URL}/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False
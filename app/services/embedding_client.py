"""
Proxy to the existing realxreal embedding microservice.

Two operations:
  1. embed(text) → vector (list of floats)
  2. cosine_similarity(vec_a, vec_b) → float 0.0–1.0

The embedding service does the heavy lifting.
This client is a thin HTTP wrapper.
"""

import os
import math
import requests
from typing import Optional


class EmbeddingClient:

    BASE_URL = os.environ.get("EMBEDDING_SERVICE_URL", "http://localhost:8001")
    TIMEOUT = 10  # seconds

    @classmethod
    def embed(cls, text: str) -> Optional[list]:
        """
        Get embedding vector for a text string.
        Returns None if the service is unavailable.
        """
        try:
            resp = requests.post(
                f"{cls.BASE_URL}/embed",
                json={"text": text},
                timeout=cls.TIMEOUT
            )
            resp.raise_for_status()
            return resp.json()["embedding"]
        except Exception as e:
            print(f"[embedding] embed failed: {e}")
            return None

    @classmethod
    def cosine_similarity(cls, vec_a: list, vec_b: list) -> float:
        """
        Compute cosine similarity between two vectors locally.
        Avoids a second network call — the math is trivial.
        Returns a float between 0.0 (no match) and 1.0 (perfect match).
        """
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        mag_a = math.sqrt(sum(a * a for a in vec_a))
        mag_b = math.sqrt(sum(b * b for b in vec_b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)
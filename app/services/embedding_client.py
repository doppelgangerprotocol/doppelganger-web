"""
Proxy to the Doppelganger Protocol embedding microservice.

Service: embedding_service_web.py (FastAPI + all-MiniLM-L6-v2, micro-batched)
Auth:    Shared API key via X-API-Key header
Endpoint: POST /embed
Response field: "vector"
Dimensions: 384

Hardening:
  - One keep-alive HTTP session per worker (no new TCP/TLS handshake per call)
  - Explicit connect/read timeouts
  - Per-worker cap on in-flight requests (a concurrency cap, not a rate limit):
    bursts wait here briefly and arrive as nicely sized batches
  - One retry on connection errors / 502 / 504 (e.g. a container restarting).
    No retry on 503/timeouts: the service is overloaded, retrying adds load.
"""

import logging
import os
import threading
import time
from typing import Optional

import numpy as np
import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

_MAX_IN_FLIGHT = int(os.environ.get("EMBEDDING_MAX_IN_FLIGHT", 16))
_slots = threading.BoundedSemaphore(_MAX_IN_FLIGHT)   # cooperative under gevent

_http = requests.Session()
_http.trust_env = False   # don't consult system proxy/netrc settings: avoids the macOS
                          # fork crash, and a server-to-server call shouldn't use them anyway
_adapter = HTTPAdapter(pool_connections=1, pool_maxsize=_MAX_IN_FLIGHT)
_http.mount("http://", _adapter)
_http.mount("https://", _adapter)


class EmbeddingClient:

    BASE_URL     = os.environ.get("EMBEDDING_SERVICE_URL", "http://localhost:8000").rstrip("/")
    API_KEY      = os.environ.get("EMBEDDING_API_KEY", "")
    CONNECT_TIMEOUT = 3
    READ_TIMEOUT    = float(os.environ.get("EMBEDDING_TIMEOUT_SECONDS", 20))
    SLOT_WAIT       = 10   # max seconds to wait for a free in-flight slot

    @classmethod
    def _headers(cls) -> dict:
        return {"Content-Type": "application/json", "X-API-Key": cls.API_KEY}

    @classmethod
    def embed(cls, text: str) -> Optional[list]:
        """
        Get 384-dim embedding vector for a text string.
        Returns a plain Python list (JSON-serializable for Redis storage).
        Returns None on failure.
        """
        if not _slots.acquire(timeout=cls.SLOT_WAIT):
            logger.warning("[embedding] no free slot after %ss", cls.SLOT_WAIT)
            return None
        try:
            for attempt in (1, 2):
                try:
                    resp = _http.post(
                        f"{cls.BASE_URL}/embed",
                        json={"text": text},
                        headers=cls._headers(),
                        timeout=(cls.CONNECT_TIMEOUT, cls.READ_TIMEOUT),
                    )
                except requests.ConnectionError as e:   # includes connect timeouts
                    logger.warning("[embedding] connection error (attempt %d): %s", attempt, e)
                    if attempt == 1:
                        time.sleep(0.5)
                        continue
                    return None
                except requests.Timeout:
                    logger.error("[embedding] read timed out after %ss", cls.READ_TIMEOUT)
                    return None

                if resp.status_code in (502, 504) and attempt == 1:
                    time.sleep(0.5)
                    continue
                if resp.status_code != 200:
                    logger.error("[embedding] HTTP %s: %s", resp.status_code, resp.text[:200])
                    return None

                data = resp.json()
                if not data.get("success") or not data.get("vector"):
                    logger.error("[embedding] bad response: %s", str(data)[:200])
                    return None
                return data["vector"]  # plain list — safe to JSON serialize into Redis
            return None
        except Exception as e:
            logger.error(f"[embedding] embed() failed: {e}")
            return None
        finally:
            _slots.release()

    @classmethod
    def cosine_similarity(cls, vec_a: list, vec_b: list) -> float:
        """
        Cosine similarity between two 384-dim vectors.
        Vectors are already L2-normalized by the embedding service,
        but computed fully for safety.
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
            resp = _http.get(f"{cls.BASE_URL}/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False
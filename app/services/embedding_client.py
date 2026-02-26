"""
Proxy to the realxreal embedding microservice.

Service: secure_embedding_service.py (FastAPI + all-MiniLM-L6-v2)
Auth:    Firebase Bearer token (server-to-server via service account)
Endpoint: POST /embed
Response field: "vector" (not "embedding")
Dimensions: 384 (all-MiniLM-L6-v2)

Auth flow:
  Flask backend uses a Firebase service account to generate a short-lived
  ID token, which is passed as a Bearer token to the embedding service.
  Token is cached for 55 minutes (expires at 60).
"""

import os
import math
import time
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)


class EmbeddingClient:

    BASE_URL = os.environ.get("EMBEDDING_SERVICE_URL", "http://localhost:8000")
    TIMEOUT = 15  # seconds — model inference can take a moment on CPU

    # Token cache — avoid re-fetching on every request
    _cached_token: Optional[str] = None
    _token_expiry: float = 0

    # ── Auth ──────────────────────────────────────────────────────────────────

    @classmethod
    def _get_firebase_token(cls) -> Optional[str]:
        """
        Get a Firebase ID token for server-to-server auth.

        Uses google-auth to generate a token from the service account.
        Token is cached for 55 minutes.

        Requires in .env:
          FIREBASE_CREDENTIALS_JSON=<service account JSON as string>
          FIREBASE_TOKEN_AUDIENCE=<your Firebase project ID>
        """
        now = time.time()
        if cls._cached_token and now < cls._token_expiry:
            return cls._cached_token

        try:
            import google.auth
            import google.oauth2.service_account
            import google.auth.transport.requests

            creds_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
            if not creds_json:
                logger.warning("[embedding] FIREBASE_CREDENTIALS_JSON not set — skipping auth")
                return None

            import json
            creds_dict = json.loads(creds_json)

            # Build credentials that can generate ID tokens
            credentials = google.oauth2.service_account.IDTokenCredentials.from_service_account_info(
                creds_dict,
                target_audience=os.environ.get(
                    "FIREBASE_TOKEN_AUDIENCE",
                    f"https://{creds_dict.get('project_id', '')}.firebaseapp.com"
                )
            )

            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)

            cls._cached_token = credentials.token
            cls._token_expiry = now + (55 * 60)  # cache for 55 min
            logger.info("[embedding] Firebase token refreshed")
            return cls._cached_token

        except ImportError:
            logger.error("[embedding] google-auth not installed — run: pip install google-auth")
            return None
        except Exception as e:
            logger.error(f"[embedding] Token fetch failed: {e}")
            return None

    @classmethod
    def _headers(cls) -> dict:
        headers = {"Content-Type": "application/json"}
        token = cls._get_firebase_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    # ── Core methods ──────────────────────────────────────────────────────────

    @classmethod
    def embed(cls, text: str) -> Optional[list]:
        """
        Get embedding vector for a text string.
        Returns a 384-dimensional list of floats, or None on failure.
        """
        try:
            resp = requests.post(
                f"{cls.BASE_URL}/embed",
                json={"text": text},
                headers=cls._headers(),
                timeout=cls.TIMEOUT
            )

            if resp.status_code == 401:
                # Token may have expired mid-cache — force refresh and retry once
                cls._cached_token = None
                cls._token_expiry = 0
                resp = requests.post(
                    f"{cls.BASE_URL}/embed",
                    json={"text": text},
                    headers=cls._headers(),
                    timeout=cls.TIMEOUT
                )

            resp.raise_for_status()
            data = resp.json()

            if not data.get("success"):
                logger.error(f"[embedding] Service returned success=false: {data}")
                return None

            # Response field is "vector" (not "embedding")
            return data["vector"]

        except requests.Timeout:
            logger.error("[embedding] Request timed out")
            return None
        except Exception as e:
            logger.error(f"[embedding] embed() failed: {e}")
            return None

    @classmethod
    def cosine_similarity(cls, vec_a: list, vec_b: list) -> float:
        """
        Cosine similarity between two 384-dim vectors.
        Both vectors are already normalized (normalize_embeddings=True in service)
        so this reduces to a dot product — but we compute it fully for safety.
        Returns 0.0–1.0.
        """
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        mag_a = math.sqrt(sum(a * a for a in vec_a))
        mag_b = math.sqrt(sum(b * b for b in vec_b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    @classmethod
    def health(cls) -> bool:
        """Quick health check against the embedding service."""
        try:
            resp = requests.get(f"{cls.BASE_URL}/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False
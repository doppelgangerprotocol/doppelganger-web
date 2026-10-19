"""
One Redis connection pool per worker process, shared by every request.

Before: every SessionStore() called redis.from_url(), which builds a brand-new
uncapped pool, so connections were opened per request and piled up.
"""
import os
import threading

import redis

_lock = threading.Lock()
_client = None
_pid = None


def get_redis() -> redis.Redis:
    global _client, _pid
    if _client is not None and _pid == os.getpid():
        return _client
    with _lock:
        if _client is None or _pid != os.getpid():
            pool = redis.BlockingConnectionPool.from_url(
                os.environ.get("REDIS_URL", "redis://localhost:6379"),
                decode_responses=True,
                max_connections=int(os.environ.get("REDIS_MAX_CONNECTIONS", 20)),
                timeout=5,                 # wait up to 5s for a free connection instead of opening more
                socket_connect_timeout=5,
                socket_timeout=5,          # a hung command fails fast instead of pinning a request
                socket_keepalive=True,
                health_check_interval=30,  # PING idle connections before reuse; drop dead ones
            )
            _client = redis.Redis(connection_pool=pool)
            _pid = os.getpid()
    return _client
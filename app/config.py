import os


class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")
    PORT = int(os.environ.get("PORT", 5000))
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
    EMBEDDING_SERVICE_URL = os.environ.get("EMBEDDING_SERVICE_URL", "http://localhost:8001")
    SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", 600)) #### Change back after the conference
    SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", 0.75))
    RATELIMIT_STORAGE_URI = os.environ.get("REDIS_URL", "redis://localhost:6379")
    # Primary domain for generating one-time links
    BASE_URL = os.environ.get("BASE_URL", "https://doppelgangerprotocol.app")
    # Per REAL client IP (do-connecting-ip), per minute. At a conference the whole
    # room is usually ONE IP, so these are sized for ~200 people at once with
    # 2-3x headroom. The embedding concurrency cap is what actually protects capacity.
    CREATE_RATE_LIMIT = os.environ.get("CREATE_RATE_LIMIT", "600 per minute")
    VERIFY_RATE_LIMIT = os.environ.get("VERIFY_RATE_LIMIT", "600 per minute")
    READ_RATE_LIMIT   = os.environ.get("READ_RATE_LIMIT", "1200 per minute")

    # Kill switch: set RATELIMIT_ENABLED=false in App Platform to disable all limits
    RATELIMIT_ENABLED = os.environ.get("RATELIMIT_ENABLED", "true").lower() == "true"

class DevelopmentConfig(BaseConfig):
    ENV = "development"
    DEBUG = True
    ALLOWED_ORIGINS = [
        "http://localhost:5000",
        "http://127.0.0.1:5000"
    ]


class ProductionConfig(BaseConfig):
    ENV = "production"
    DEBUG = False
    ALLOWED_ORIGINS = [
        "https://doppelgangerprotocol.app",  # primary
        "https://doppelgangerprotocol.org",  # spec site
        "https://realxreal.app",             # mobile app companion
    ]
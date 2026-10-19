import os

import redis
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def client_ip() -> str:
    """
    Real client IP on DigitalOcean App Platform. remote_addr / X-Forwarded-For
    point at DO's ingress, so without this every visitor shared ONE bucket.
    Falls back to remote_addr for local dev.
    """
    return request.headers.get("do-connecting-ip") or get_remote_address()


limiter = Limiter(
    key_func=client_ip,
    default_limits=[],                # nothing is limited unless a route opts in
    storage_uri=os.environ.get("REDIS_URL", "redis://localhost:6379"),
    storage_options={
        "max_connections": 10,
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
        "health_check_interval": 30,
    },
    swallow_errors=True,              # Redis hiccup -> let the request through, don't 500
    in_memory_fallback_enabled=True,
)

def create_app():
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static"
    )

    app.config.from_object(
        "app.config.ProductionConfig"
        if os.environ.get("FLASK_ENV") == "production"
        else "app.config.DevelopmentConfig"
    )

    CORS(app, origins=app.config["ALLOWED_ORIGINS"])
    limiter.init_app(app)

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if app.config["ENV"] == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    # ── JSON errors, so the frontend can show what actually happened ──────────
    @app.errorhandler(429)
    def rate_limited(e):
        return jsonify(error="Lots of people on your network are using the demo. "
                             "Wait a few seconds and try again."), 429

    @app.errorhandler(redis.exceptions.RedisError)
    def store_unavailable(e):
        app.logger.exception("Redis error")
        return jsonify(error="Session store is busy. Please try again in a moment."), 503

    @app.errorhandler(500)
    def server_error(e):
        if request.path.startswith("/api/"):
            return jsonify(error="Internal server error. Please try again."), 500
        return "Internal server error", 500

    from app.routes.pages import pages_bp
    from app.routes.session import session_bp
    from app.routes.verify import verify_bp
    from app.routes.stream import stream_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(session_bp, url_prefix="/api")
    app.register_blueprint(verify_bp, url_prefix="/api")
    app.register_blueprint(stream_bp, url_prefix="/api")

    return app
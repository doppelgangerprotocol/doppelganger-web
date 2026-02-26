import os
from flask import Flask
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour"],
    storage_uri=os.environ.get("REDIS_URL", "redis://localhost:6379")
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

    # The Doppelganger Protocol has 3 API routes:
    #   POST /api/session             — Alice creates session (memory question + answer + pubkey)
    #   POST /api/session/{id}/verify — Bob answers + submits pubkey → scoring → key exchange if pass
    #   GET  /api/session/{id}/stream — SSE real-time updates for both Alice and Bob
    from app.routes.pages import pages_bp
    from app.routes.session import session_bp
    from app.routes.verify import verify_bp
    from app.routes.stream import stream_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(session_bp, url_prefix="/api")
    app.register_blueprint(verify_bp, url_prefix="/api")
    app.register_blueprint(stream_bp, url_prefix="/api")

    return app
import secrets


def generate_session_id() -> str:
    """
    Cryptographically secure session ID.
    43 characters of URL-safe base64 (256 bits of entropy).
    """
    return secrets.token_urlsafe(32)
import hashlib
import hmac
import os

SECRET = os.environ.get("ADMIN_PASSWORD", "VP2026")


def make_token(username: str) -> str:
    """Create a simple session token for a username."""
    return hmac.new(SECRET.encode(), username.encode(), hashlib.sha256).hexdigest()


def verify_token(username: str, token: str) -> bool:
    """Verify a session token matches the username."""
    expected = make_token(username)
    return hmac.compare_digest(expected, token)

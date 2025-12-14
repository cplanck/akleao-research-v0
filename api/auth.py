"""Authentication utilities for magic link auth with httpOnly cookies."""

import os
import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import Response

# Configuration
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7  # 1 week
MAGIC_LINK_EXPIRATION_MINUTES = 15
AUTH_COOKIE_NAME = "auth_token"


def generate_magic_token() -> tuple[str, str]:
    """Generate a magic link token.

    Returns:
        Tuple of (raw_token, hashed_token) - send raw in email, store hash in DB.
    """
    raw_token = secrets.token_urlsafe(32)
    hashed_token = hashlib.sha256(raw_token.encode()).hexdigest()
    return raw_token, hashed_token


def hash_token(token: str) -> str:
    """Hash a token for database lookup."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_jwt_token(user_id: str, email: str) -> str:
    """Create a JWT session token."""
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt_token(token: str) -> dict:
    """Decode and validate a JWT token.

    Raises:
        jwt.ExpiredSignatureError: If token has expired
        jwt.InvalidTokenError: If token is invalid
    """
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def set_auth_cookie(response: Response, token: str) -> None:
    """Set the httpOnly auth cookie on a response."""
    # Check if we're in development (localhost)
    is_localhost = os.getenv("FRONTEND_URL", "").startswith("http://localhost")

    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=not is_localhost,  # False for localhost, True for production
        samesite="lax",
        max_age=JWT_EXPIRATION_HOURS * 3600,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Clear the auth cookie (logout)."""
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
    )


def get_magic_link_expiry() -> datetime:
    """Get the expiry time for a magic link token."""
    return datetime.utcnow() + timedelta(minutes=MAGIC_LINK_EXPIRATION_MINUTES)

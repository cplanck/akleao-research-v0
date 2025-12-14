"""Auth middleware for FastAPI routes using httpOnly cookies."""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from api.database import get_db, User
from api.auth import decode_jwt_token, AUTH_COOKIE_NAME

import jwt


def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """Get the current authenticated user from cookie.

    Raises:
        HTTPException: 401 if not authenticated or token invalid
    """
    token = request.cookies.get(AUTH_COOKIE_NAME)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    try:
        payload = decode_jwt_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled",
        )

    return user


def get_optional_user(
    request: Request,
    db: Session = Depends(get_db)
) -> User | None:
    """Get the current user if authenticated, otherwise None.

    Useful for routes that work with or without authentication.
    """
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        return None

    try:
        payload = decode_jwt_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None

        user = db.query(User).filter(
            User.id == user_id,
            User.is_active == 1
        ).first()
        return user
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

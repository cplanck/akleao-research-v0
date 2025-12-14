"""Authentication API routes for magic link auth."""

import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from api.database import get_db, User, MagicLinkToken, Project
from api.auth import (
    generate_magic_token,
    hash_token,
    create_jwt_token,
    set_auth_cookie,
    clear_auth_cookie,
    get_magic_link_expiry,
)
from api.services.email import send_magic_link_email
from api.middleware.auth import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkVerifyRequest(BaseModel):
    token: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str | None
    is_admin: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    user: UserResponse


class UpdateProfileRequest(BaseModel):
    name: str | None = None


@router.post("/magic-link")
def request_magic_link(
    request: MagicLinkRequest,
    db: Session = Depends(get_db)
):
    """Request a magic link for authentication.

    Sends an email with a login link. Works for both new and existing users.
    """
    email = request.email.lower().strip()

    # Check if user exists
    user = db.query(User).filter(User.email == email).first()
    is_new_user = user is None

    # Generate token
    raw_token, hashed_token = generate_magic_token()

    # Create magic link token record
    magic_token = MagicLinkToken(
        user_id=user.id if user else None,
        email=email,
        token=hashed_token,
        expires_at=get_magic_link_expiry(),
    )
    db.add(magic_token)
    db.commit()

    # Build magic link URL
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    magic_link = f"{frontend_url}/auth/verify?token={raw_token}"

    # Send email
    try:
        send_magic_link_email(email, magic_link, is_new_user)
    except ValueError as e:
        # Mailgun not configured
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except RuntimeError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send email: {str(e)}"
        )

    return {"message": "Magic link sent", "email": email}


@router.post("/verify", response_model=AuthResponse)
def verify_magic_link(
    request: MagicLinkVerifyRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    """Verify a magic link token and set auth cookie.

    Returns user info. The JWT is set as an httpOnly cookie.
    """
    hashed_token = hash_token(request.token)

    # Find token
    magic_token = db.query(MagicLinkToken).filter(
        MagicLinkToken.token == hashed_token,
        MagicLinkToken.used_at.is_(None),
        MagicLinkToken.expires_at > datetime.utcnow()
    ).first()

    if not magic_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token"
        )

    # Mark token as used
    magic_token.used_at = datetime.utcnow()

    # Check if this will be the first user
    is_first_user = db.query(User).count() == 0

    # Get or create user
    user = db.query(User).filter(User.email == magic_token.email).first()

    if not user:
        # Create new user
        user = User(
            email=magic_token.email,
            is_admin=1 if is_first_user else 0,  # First user is admin
        )
        db.add(user)
        db.flush()  # Get user.id

        # CRITICAL: Assign all existing orphaned projects to first user
        if is_first_user:
            orphaned_count = db.query(Project).filter(
                Project.user_id.is_(None)
            ).update({"user_id": user.id})
            if orphaned_count:
                print(f"[Auth] Assigned {orphaned_count} existing projects to first user")

    # Update last login
    user.last_login_at = datetime.utcnow()
    db.commit()

    # Generate JWT and set cookie
    jwt_token = create_jwt_token(user.id, user.email)
    set_auth_cookie(response, jwt_token)

    return AuthResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            is_admin=bool(user.is_admin),
            created_at=user.created_at,
        )
    )


@router.get("/me", response_model=UserResponse)
def get_current_user_info(user: User = Depends(get_current_user)):
    """Get current authenticated user info."""
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        is_admin=bool(user.is_admin),
        created_at=user.created_at,
    )


@router.patch("/me", response_model=UserResponse)
def update_profile(
    updates: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update current user's profile."""
    if updates.name is not None:
        user.name = updates.name

    db.commit()
    db.refresh(user)

    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        is_admin=bool(user.is_admin),
        created_at=user.created_at,
    )


@router.post("/logout")
def logout(
    response: Response,
    user: User = Depends(get_current_user)
):
    """Logout by clearing the auth cookie."""
    clear_auth_cookie(response)
    return {"message": "Logged out"}

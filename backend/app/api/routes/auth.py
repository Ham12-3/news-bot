"""
Authentication API routes.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.db.models import User
from app.api.deps import get_current_user
from app.services.auth import get_auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    name: str | None = None


class AuthResponse(BaseModel):
    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    password: str | None = None


@router.post("/register", response_model=AuthResponse)
async def register(request: RegisterRequest):
    """Register a new user account."""
    if len(request.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters",
        )

    service = get_auth_service()
    result = await service.register(
        email=request.email,
        password=request.password,
        display_name=request.name,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    return result


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    """Login with email and password."""
    service = get_auth_service()
    result = await service.login(
        email=request.email,
        password=request.password,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result["error"],
        )

    return result


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(request: RefreshRequest):
    """Refresh access token using refresh token."""
    service = get_auth_service()
    result = await service.refresh_tokens(request.refresh_token)

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=result["error"],
        )

    return result


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    refresh_token: str | None = None,
):
    """Logout and revoke refresh tokens."""
    service = get_auth_service()
    await service.logout(current_user.id, refresh_token)
    return {"success": True}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "name": current_user.name,
    }


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    request: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
):
    """Update user profile."""
    if request.password and len(request.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters",
        )

    service = get_auth_service()
    result = await service.update_user(
        user_id=current_user.id,
        name=request.name,
        password=request.password,
    )

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["error"],
        )

    return result

"""
Authentication middleware for JWT and API keys
"""

from fastapi import HTTPException, status, Header, Depends
from typing import Optional, List
from sqlalchemy.orm import Session
import json
from app.database import get_db
from app.models import User, APIKey
from app.services.auth_service import verify_jwt_token
from app.config import settings


class AuthUser:
    """Authenticated user from JWT or API key"""
    def __init__(self, user_id: int, email: str, permissions: Optional[List[str]] = None):
        self.user_id = user_id
        self.email = email
        self.permissions = permissions or []  # For API keys
        self.is_api_key = permissions is not None


async def get_current_user(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> AuthUser:
    """
    Get current authenticated user from JWT or API key
    Priority: API key > JWT
    """
    # Check for API key first
    if x_api_key:
        return await get_user_from_api_key(x_api_key, db)
    
    # Check for JWT token
    if authorization:
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format"
            )
        token = authorization.replace("Bearer ", "")
        return await get_user_from_jwt(token, db)
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required"
    )


async def get_user_from_jwt(token: str, db: Session) -> AuthUser:
    """Get user from JWT token"""
    payload = verify_jwt_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    
    user_id = payload.get("user_id")
    email = payload.get("email")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    return AuthUser(user_id=user.id, email=user.email)


async def get_user_from_api_key(api_key: str, db: Session) -> AuthUser:
    """Get user from API key"""
    # Remove prefix if present
    if api_key.startswith(settings.API_KEY_PREFIX):
        key = api_key
    else:
        key = f"{settings.API_KEY_PREFIX}{api_key}"
    
    api_key_obj = db.query(APIKey).filter(APIKey.key == key).first()
    if not api_key_obj:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    if api_key_obj.is_revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key has been revoked"
        )
    
    if api_key_obj.is_expired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key has expired"
        )
    
    user = db.query(User).filter(User.id == api_key_obj.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    # Parse permissions
    permissions = []
    if api_key_obj.permissions:
        try:
            permissions = json.loads(api_key_obj.permissions)
        except:
            permissions = []
    
    return AuthUser(
        user_id=user.id,
        email=user.email,
        permissions=permissions
    )


def require_permission(permission: str):
    """Dependency to require specific permission"""
    async def permission_checker(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
        # JWT users have all permissions
        if not current_user.is_api_key:
            return current_user
        
        # API key users need explicit permission
        if permission not in current_user.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required"
            )
        return current_user
    
    return permission_checker


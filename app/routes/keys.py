"""
API key management routes
"""

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List
import json
import secrets
from app.database import get_db
from app.middleware.auth import get_current_user, AuthUser
from app.models import APIKey
from app.schemas import CreateAPIKeyRequest, CreateAPIKeyResponse, RolloverAPIKeyRequest
from app.config import settings

router = APIRouter(prefix="/keys", tags=["API Keys"])


def parse_expiry(expiry: str) -> datetime:
    """Parse expiry string (1H, 1D, 1M, 1Y) to datetime"""
    now = datetime.utcnow()
    if expiry == "1H":
        return now + timedelta(hours=1)
    elif expiry == "1D":
        return now + timedelta(days=1)
    elif expiry == "1M":
        return now + timedelta(days=30)
    elif expiry == "1Y":
        return now + timedelta(days=365)
    else:
        raise ValueError("Invalid expiry format")


def generate_api_key() -> str:
    """Generate a new API key"""
    random_part = secrets.token_urlsafe(32)
    return f"{settings.API_KEY_PREFIX}{random_part}"


@router.post(
    "/create", 
    response_model=CreateAPIKeyResponse, 
    status_code=201,
    dependencies=[Depends(get_current_user)],
    summary="Create API Key",
    description=(
        "Creates a new API key you can use instead of a JWT.\n"
        "Simple steps for non-technical users:\n"
        "1) Make sure you are logged in (use the Authorize button with your JWT token).\n"
        "2) Click 'Try it out'.\n"
        "3) Fill the body:\n"
        "   - name: any label you like (e.g., 'my service key')\n"
        "   - permissions: MUST include what you need! Options: 'deposit', 'transfer', 'read'\n"
        "     * To deposit money: MUST include 'deposit'\n"
        "     * To transfer money: MUST include 'transfer'\n"
        "     * To view balance/transactions: MUST include 'read'\n"
        "     * You can include all: ['deposit', 'transfer', 'read']\n"
        "   - expiry: how long it lasts (1H = 1 hour, 1D = 1 day, 1M = 1 month, 1Y = 1 year)\n"
        "4) Click Execute and copy the 'api_key' value from the response.\n"
        "Note: You can have at most 5 active keys at once."
    )
)
async def create_api_key(
    request: CreateAPIKeyRequest,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new API key with specified permissions
    Maximum 5 active keys per user
    """
    # Check active key count
    active_keys = db.query(APIKey).filter(
        APIKey.user_id == current_user.user_id,
        APIKey.is_revoked == False,
        APIKey.expires_at > datetime.utcnow()
    ).count()
    
    if active_keys >= settings.MAX_ACTIVE_KEYS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {settings.MAX_ACTIVE_KEYS_PER_USER} active API keys allowed per user"
        )
    
    # Validate permissions
    valid_permissions = ["deposit", "transfer", "read"]
    for perm in request.permissions:
        if perm not in valid_permissions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid permission: {perm}. Valid permissions: {valid_permissions}"
            )
    
    # Parse expiry
    try:
        expires_at = parse_expiry(request.expiry)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    # Generate API key
    api_key = generate_api_key()
    
    # Create API key record
    api_key_obj = APIKey(
        user_id=current_user.user_id,
        key=api_key,
        name=request.name,
        permissions=json.dumps(request.permissions),
        expires_at=expires_at,
    )
    db.add(api_key_obj)
    db.commit()
    db.refresh(api_key_obj)
    
    return CreateAPIKeyResponse(
        api_key=api_key,
        expires_at=expires_at,
    )


@router.post(
    "/rollover",
    response_model=CreateAPIKeyResponse,
    status_code=201,
    dependencies=[Depends(get_current_user)],
    summary="Rollover Expired API Key",
    description=(
        "Creates a fresh API key using the same permissions as an expired one.\n"
        "Steps:\n"
        "1) Make sure you are logged in (Authorize with JWT).\n"
        "2) Provide the expired key ID or the key value in 'expired_key_id'.\n"
        "3) Choose a new expiry (1H, 1D, 1M, 1Y).\n"
        "4) Execute and copy the new 'api_key'.\n"
        "Note: Only works if the key is actually expired."
    )
)
async def rollover_api_key(
    request: RolloverAPIKeyRequest,
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Rollover an expired API key
    Creates a new key with the same permissions as the expired one
    """
    # Find the expired key - try by ID first, then by key string
    expired_key = None
    if request.expired_key_id.isdigit():
        expired_key = db.query(APIKey).filter(
            APIKey.id == int(request.expired_key_id),
            APIKey.user_id == current_user.user_id
        ).first()
    
    if not expired_key:
        # Try finding by key string
        expired_key = db.query(APIKey).filter(
            APIKey.key == request.expired_key_id,
            APIKey.user_id == current_user.user_id
        ).first()
        
        # Also try with prefix if not found
        if not expired_key and not request.expired_key_id.startswith(settings.API_KEY_PREFIX):
            key_with_prefix = f"{settings.API_KEY_PREFIX}{request.expired_key_id}"
            expired_key = db.query(APIKey).filter(
                APIKey.key == key_with_prefix,
                APIKey.user_id == current_user.user_id
            ).first()
    
    if not expired_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expired API key not found"
        )
    
    # Verify it's actually expired
    if not expired_key.is_expired:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API key is not expired. Only expired keys can be rolled over"
        )
    
    # Check active key count
    active_keys = db.query(APIKey).filter(
        APIKey.user_id == current_user.user_id,
        APIKey.is_revoked == False,
        APIKey.expires_at > datetime.utcnow()
    ).count()
    
    if active_keys >= settings.MAX_ACTIVE_KEYS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {settings.MAX_ACTIVE_KEYS_PER_USER} active API keys allowed per user"
        )
    
    # Parse expiry
    try:
        expires_at = parse_expiry(request.expiry)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    
    # Get permissions from expired key
    permissions = []
    if expired_key.permissions:
        try:
            permissions = json.loads(expired_key.permissions)
        except:
            permissions = []
    
    # Generate new API key
    api_key = generate_api_key()
    
    # Create new API key with same permissions
    new_api_key = APIKey(
        user_id=current_user.user_id,
        key=api_key,
        name=f"{expired_key.name} (rolled over)",
        permissions=json.dumps(permissions),
        expires_at=expires_at,
    )
    db.add(new_api_key)
    db.commit()
    db.refresh(new_api_key)
    
    return CreateAPIKeyResponse(
        api_key=api_key,
        expires_at=expires_at,
    )


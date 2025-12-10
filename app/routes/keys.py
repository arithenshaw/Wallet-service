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
from app.schemas import CreateAPIKeyRequest, CreateAPIKeyResponse, RolloverAPIKeyRequest, APIKeyInfo
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


def generate_api_key_id() -> str:
    """Generate a random hexadecimal ID (12 characters)"""
    return secrets.token_hex(6)  # 6 bytes = 12 hex characters


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
    
    # Generate API key and ID
    api_key = generate_api_key()
    api_key_id = generate_api_key_id()
    
    # Ensure ID is unique
    while db.query(APIKey).filter(APIKey.id == api_key_id).first():
        api_key_id = generate_api_key_id()
    
    # Create API key record
    api_key_obj = APIKey(
        id=api_key_id,
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
        api_key_id=api_key_obj.id,
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
    # Find the expired key - try by ID first (hex string, 12 characters), then by key string
    expired_key = None
    # Try finding by ID (hex string, 12 characters)
    if len(request.expired_key_id) == 12 and all(c in '0123456789abcdef' for c in request.expired_key_id.lower()):
        expired_key = db.query(APIKey).filter(
            APIKey.id == request.expired_key_id.lower(),
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
    
    # Generate new API key and ID
    api_key = generate_api_key()
    api_key_id = generate_api_key_id()
    
    # Ensure ID is unique
    while db.query(APIKey).filter(APIKey.id == api_key_id).first():
        api_key_id = generate_api_key_id()
    
    # Create new API key with same permissions
    new_api_key = APIKey(
        id=api_key_id,
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
        api_key_id=new_api_key.id,
        api_key=api_key,
        expires_at=expires_at,
    )


@router.get(
    "/list",
    response_model=List[APIKeyInfo],
    summary="List All API Keys",
    description=(
        "Get a list of all your API keys (active, expired, and revoked).\n"
        "Steps:\n"
        "1) Make sure you're logged in (use Authorize button with JWT token).\n"
        "2) Click 'Try it out' → 'Execute'.\n"
        "3) View all your keys with their status.\n"
        "4) Use the 'id' field from expired keys for rollover."
    )
)
async def list_api_keys(
    current_user: AuthUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all API keys for the current user
    Returns active, expired, and revoked keys
    Use this to find expired key IDs for rollover
    """
    api_keys = db.query(APIKey).filter(
        APIKey.user_id == current_user.user_id
    ).order_by(APIKey.created_at.desc()).all()
    
    result = []
    for key in api_keys:
        permissions = []
        if key.permissions:
            try:
                permissions = json.loads(key.permissions)
            except:
                permissions = []
        
        # Mask the API key for security (show only first 8 and last 4 characters)
        masked_key = mask_api_key(key.key)
        
        result.append(APIKeyInfo(
            id=key.id,
            name=key.name,
            api_key=masked_key,
            permissions=permissions,
            expires_at=key.expires_at,
            is_revoked=key.is_revoked,
            is_expired=key.is_expired,
            created_at=key.created_at,
        ))
    
    return result


def mask_api_key(api_key: str) -> str:
    """
    Mask API key for display - shows only first 8 and last 4 characters
    Example: sk_live_abc123...xyz9
    """
    if len(api_key) <= 12:
        # If key is too short, mask everything except first 4 chars
        return api_key[:4] + "..." + "*" * (len(api_key) - 4)
    
    # Show first 8 characters and last 4 characters
    prefix = api_key[:8]
    suffix = api_key[-4:]
    masked_length = len(api_key) - 12  # Total length minus visible parts
    
    return f"{prefix}{'*' * min(masked_length, 20)}...{suffix}"

